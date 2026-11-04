"""Month-end revaluation of foreign-currency balances (backlog P2-21, spec 5.5 and 6; IAS 21).

- At a month end, everything still open in a foreign currency is valued again at that day's
  rate (the latest rate on or before it, from Settings → Currencies and exchange rates):
  - customer tax invoices not fully received, credited or set off;
  - supplier invoices not fully paid, set off or debited;
  - the balances of the company's bank and cash accounts held in a foreign currency.
  Advances paid or received are not revalued: they are settled in goods or services, not in
  money (IAS 21 paragraph 16, IFRIC 22).
- The books carry an invoice in LKR at the rate of its date. The difference between that and
  the month-end value is an unrealised gain or loss: posted on the month's last day to
  Unrealised exchange gain or loss (per division, with the customer or supplier on the
  receivable or payable), and reversed on the first day of the next month. The invoice is
  then back at its own rate, so a later receipt or payment works out the realised difference
  as before (P2-09, P2-11).
- A bank or cash account in a foreign currency is valued at its balance in that currency
  times the month-end rate. The difference from its LKR ledger balance is posted to Exchange
  gain or Exchange loss and is not reversed: the money is held, so the books carry it at the
  latest rate. The balance in the currency comes from the bank statement imported for the
  month (its closing balance), or is typed by the Accountant.
- The month is a draft for the Accountant to check, then posted. A posted month never
  changes (database guard); it is revalued once.
"""

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.masters import currencies
from apps.masters.models import CompanyAccount, Currency
from apps.masters.services import MastersError

from . import journal
from .models import Account, JournalLine, Revaluation, RevaluationLine
from .services import AccountingError

ZERO = Decimal("0")
CENT = Decimal("0.01")
Kind = RevaluationLine.Kind


class RevaluationError(Exception):
    pass


def can_manage(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def _accountant(user: User) -> None:
    if not can_manage(user):
        raise RevaluationError("Only the Accountant revalues foreign-currency balances.")


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def suggested_month(today: date | None = None) -> date:
    """The last month that has ended."""
    today = today or timezone.localdate()
    return today.replace(day=1) - timedelta(days=1)


def _lkr(amount: Decimal, rate: Decimal) -> Decimal:
    return (Decimal(amount) * rate).quantize(CENT, ROUND_HALF_UP)


def _balance_amount(value, code: str) -> Decimal:
    if isinstance(value, float):
        raise RevaluationError(f"The balance of {code} must be an exact amount.")
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise RevaluationError(f"The balance of {code} is not a number.") from None
    if not amount.is_finite() or amount != amount.quantize(CENT):
        raise RevaluationError(f"The balance of {code} is an amount to the cent.")
    return amount


def _rate(currency: Currency, end: date, rates: dict):
    if currency.pk not in rates:
        try:
            rates[currency.pk] = currencies.rate_on(currency, end)
        except MastersError as error:
            raise RevaluationError(str(error)) from None
    return rates[currency.pk]


# --- What is open ----------------------------------------------------------------------------


def receivables(end: date, rates: dict) -> list[dict]:
    """Customer tax invoices in a foreign currency with something open at `end`."""
    from apps.sales.models import TaxInvoice
    from apps.sales.receivables import open_at

    rows = list(
        TaxInvoice.objects.filter(status=TaxInvoice.Status.ISSUED, invoice_date__lte=end)
        .exclude(currency__is_base=True)
        .select_related("customer", "division", "currency")
        .order_by("number")
    )
    amounts = open_at(rows, end)
    found = []
    for invoice in rows:
        left = amounts[invoice.pk]
        if not left:
            continue
        carried = (
            invoice.total_lkr if left == invoice.total_amount else _lkr(left, invoice.exchange_rate)
        )
        lookup = _rate(invoice.currency, end, rates)
        found.append(
            {
                "kind": Kind.RECEIVABLE,
                "document": invoice.number,
                "link": f"/tax-invoices/{invoice.pk}",
                "customer": invoice.customer,
                "division": invoice.division,
                "currency": invoice.currency,
                "open_amount": left,
                "carried_lkr": carried,
                "rate": lookup.rate,
                "rate_date": lookup.rate_date,
                "revalued_lkr": _lkr(left, lookup.rate),
            }
        )
    return found


def payables(end: date, rates: dict) -> list[dict]:
    """Supplier invoices in a foreign currency with something open at `end`. What is open is
    kept in LKR at the invoice's rate (P2-10); in its currency it is the same share of the
    invoice's total."""
    from apps.purchasing.payables import open_items

    found = []
    for item in open_items(end):
        invoice = item.get("invoice")
        if invoice is None or invoice.currency.is_base or not invoice.total_lkr:
            continue
        carried = item["open"]
        left = (carried * invoice.total_amount / invoice.total_lkr).quantize(CENT, ROUND_HALF_UP)
        if not left:
            continue
        lookup = _rate(invoice.currency, end, rates)
        found.append(
            {
                "kind": Kind.PAYABLE,
                "document": invoice.number,
                "link": item["link"],
                "supplier": invoice.supplier,
                "division": invoice.division,
                "currency": invoice.currency,
                "open_amount": left,
                "carried_lkr": carried,
                "rate": lookup.rate,
                "rate_date": lookup.rate_date,
                "revalued_lkr": _lkr(left, lookup.rate),
            }
        )
    return found


def ledger_balance(account: Account, end: date) -> Decimal:
    """Debits less credits on the account up to and including `end`, in LKR."""
    totals = JournalLine.objects.filter(account=account, entry__entry_date__lte=end).aggregate(
        d=Sum("debit"), c=Sum("credit")
    )
    return (totals["d"] or ZERO) - (totals["c"] or ZERO)


def foreign_accounts():
    return (
        CompanyAccount.objects.filter(ledger_account__isnull=False)
        .exclude(currency__is_base=True)
        .select_related("currency", "ledger_account", "division")
        .order_by("code")
    )


def statement_balance(account: CompanyAccount, end: date) -> tuple[Decimal, date] | None:
    """The closing balance of the last statement imported for the account that ends in the
    month of `end`, with its date."""
    from apps.banking.models import BankStatement

    found = (
        BankStatement.objects.filter(
            account=account,
            to_date__lte=end,
            to_date__gte=end.replace(day=1),
            closing_balance__isnull=False,
        )
        .order_by("-to_date", "-id")
        .first()
    )
    return (found.closing_balance, found.to_date) if found else None


def _head_office() -> Division | None:
    return Division.objects.filter(code="HO").first()


def balances(end: date, rates: dict, given: dict, user: User | None) -> list[dict]:
    """The company's foreign-currency bank and cash accounts at `end`. `given` holds the
    balances typed by the Accountant, {account id: amount in its currency}; otherwise the
    month's bank statement gives it. An account with neither and nothing in the books is left
    out; one with entries needs a balance."""
    found, missing = [], []
    for account in foreign_accounts():
        carried = ledger_balance(account.ledger_account, end)
        if account.pk in given and given[account.pk] not in (None, ""):
            amount = _balance_amount(given[account.pk], account.code)
            source = f"Typed by {user.full_name}" if user else "Typed"
        elif (statement := statement_balance(account, end)) is not None:
            amount, to_date = statement
            source = f"Bank statement to {to_date:%d %b %Y}"
        elif (
            carried == 0
            and not JournalLine.objects.filter(
                account=account.ledger_account, entry__entry_date__lte=end
            ).exists()
        ):
            continue
        else:
            missing.append(account.code)
            continue
        if amount == 0 and carried == 0:
            continue
        division = account.division or _head_office()
        if division is None:
            raise RevaluationError(
                f"{account.code} has no division and there is no Head Office division."
            )
        lookup = _rate(account.currency, end, rates)
        found.append(
            {
                "kind": Kind.BALANCE,
                "document": account.code,
                "link": "",
                "company_account": account,
                "division": division,
                "currency": account.currency,
                "open_amount": amount,
                "carried_lkr": carried,
                "rate": lookup.rate,
                "rate_date": lookup.rate_date,
                "revalued_lkr": _lkr(amount, lookup.rate),
                "balance_from": source,
            }
        )
    if missing:
        raise RevaluationError(
            "Give the balance at the month end, in the account's currency, of: "
            + ", ".join(missing)
            + " (or import the month's bank statement)."
        )
    return found


# --- The month -------------------------------------------------------------------------------


def _difference(row: dict) -> Decimal:
    """A gain is positive: an asset worth more in LKR, or a payable worth less."""
    change = row["revalued_lkr"] - row["carried_lkr"]
    return -change if row["kind"] == Kind.PAYABLE else change


def prepare(user: User, end: date, given_balances: dict | None = None) -> Revaluation:
    """Work the month out as a draft for the Accountant to check (again, if it was)."""
    _accountant(user)
    end = month_end(end)
    if end > month_end(timezone.localdate()):
        raise RevaluationError("That month has not come yet.")
    given = {int(k): v for k, v in (given_balances or {}).items()}
    rates: dict = {}
    rows = receivables(end, rates) + payables(end, rates) + balances(end, rates, given, user)
    with audit_context("revaluation_prepared"), transaction.atomic():
        run = Revaluation.objects.select_for_update().filter(month_end=end).first()
        if run is not None and run.status == Revaluation.Status.POSTED:
            raise RevaluationError(f"{end:%B %Y} is revalued and posted already.")
        if run is None:
            run = Revaluation.objects.create(month_end=end, prepared_by=user)
        else:
            run.lines.all().delete()
        open_total = balance_total = ZERO
        for row in rows:
            difference = _difference(row)
            RevaluationLine.objects.create(revaluation=run, difference=difference, **row)
            if row["kind"] == Kind.BALANCE:
                balance_total += difference
            else:
                open_total += difference
        run.open_items_total = open_total
        run.balances_total = balance_total
        run.prepared_by = user
        run.prepared_at = timezone.now()
        run.save(update_fields=["open_items_total", "balances_total", "prepared_by", "prepared_at"])
        return run


def _system(role: str, name: str) -> Account:
    account = Account.objects.filter(system_role=role, is_active=True).first()
    if account is None:
        raise RevaluationError(f"The chart of accounts has no active {name} account.")
    return account


def _what(text: str, name: str, line: RevaluationLine) -> str:
    amount = f"{line.currency.code} {line.open_amount:,.2f}"
    return f"{text}: {name} {amount} at {line.rate.normalize():f}"


def _open_items_entry(lines: list[RevaluationLine], end: date) -> list[journal.Line]:
    receivable = _system("accounts_receivable", "Accounts receivable")
    payable = _system("accounts_payable", "Accounts payable")
    unrealised = _system("unrealised_exchange", "Unrealised exchange gain or loss")
    text = f"Revaluation {end:%B %Y}"
    out: list[journal.Line] = []
    per_division: dict[int, Decimal] = {}
    divisions: dict[int, Division] = {}
    for line in lines:
        if not line.difference:
            continue
        what = _what(text, line.document, line)
        change = line.revalued_lkr - line.carried_lkr  # more owed to us, or more we owe
        if line.kind == Kind.RECEIVABLE:
            out.append(
                journal.Line(
                    account=receivable,
                    debit=max(change, ZERO),
                    credit=max(-change, ZERO),
                    division=line.division,
                    customer=line.customer,
                    description=what,
                )
            )
        else:
            out.append(
                journal.Line(
                    account=payable,
                    debit=max(-change, ZERO),
                    credit=max(change, ZERO),
                    division=line.division,
                    supplier=line.supplier,
                    description=what,
                )
            )
        per_division[line.division_id] = per_division.get(line.division_id, ZERO) + line.difference
        divisions[line.division_id] = line.division
    for key, gain in per_division.items():
        if gain:
            out.append(
                journal.Line(
                    account=unrealised,
                    debit=max(-gain, ZERO),
                    credit=max(gain, ZERO),
                    division=divisions[key],
                    description=f"{text}: unrealised exchange difference",
                )
            )
    return out


def _balances_entry(lines: list[RevaluationLine], end: date) -> list[journal.Line]:
    text = f"Revaluation {end:%B %Y}"
    out: list[journal.Line] = []
    for line in lines:
        gain = line.difference
        if not gain:
            continue
        account = line.company_account
        what = _what(text, account.code, line)
        out.append(
            journal.Line(
                account=account.ledger_account,
                debit=max(gain, ZERO),
                credit=max(-gain, ZERO),
                division=line.division,
                description=what,
            )
        )
        if gain > 0:
            out.append(
                journal.Line(
                    account=_system("exchange_gain", "Exchange gain"),
                    credit=gain,
                    division=line.division,
                    description=what,
                )
            )
        else:
            out.append(
                journal.Line(
                    account=_system("exchange_loss", "Exchange loss"),
                    debit=-gain,
                    division=line.division,
                    description=what,
                )
            )
    return out


def post(user: User, run: Revaluation) -> Revaluation:
    """The Accountant has checked the month: post it, and reverse the open invoices' part on
    the first day of the next month."""
    _accountant(user)
    with audit_context("revaluation_posted"), transaction.atomic():
        run = Revaluation.objects.select_for_update().get(pk=run.pk)
        if run.status != Revaluation.Status.DRAFT:
            raise RevaluationError("This month is posted already.")
        lines = list(
            run.lines.select_related(
                "division", "currency", "customer", "supplier", "company_account__ledger_account"
            )
        )
        if not any(line.difference for line in lines):
            raise RevaluationError("Nothing changes in value this month; there is nothing to post.")
        end = run.month_end
        open_items = [x for x in lines if x.kind != Kind.BALANCE]
        held = [x for x in lines if x.kind == Kind.BALANCE]
        try:
            entry_lines = _open_items_entry(open_items, end)
            if entry_lines:
                run.journal_entry = journal.post(
                    user,
                    entry_date=end,
                    narration=f"Revaluation {end:%B %Y}: open foreign-currency invoices",
                    lines=entry_lines,
                    source_type="revaluation",
                    source_id=f"{end:%Y-%m}",
                )
                run.reversal_entry = journal.reverse(
                    user,
                    run.journal_entry,
                    reason=f"revaluation of {end:%B %Y} reversed on the next day",
                    on_date=end + timedelta(days=1),
                )
            entry_lines = _balances_entry(held, end)
            if entry_lines:
                run.balances_entry = journal.post(
                    user,
                    entry_date=end,
                    narration=f"Revaluation {end:%B %Y}: foreign-currency bank and cash balances",
                    lines=entry_lines,
                    source_type="revaluation",
                    source_id=f"{end:%Y-%m}",
                )
        except AccountingError as error:
            raise RevaluationError(str(error)) from None
        run.status = Revaluation.Status.POSTED
        run.posted_by = user
        run.posted_at = timezone.now()
        run.save(
            update_fields=[
                "status",
                "journal_entry",
                "reversal_entry",
                "balances_entry",
                "posted_by",
                "posted_at",
            ]
        )
        return run


def discard(user: User, run: Revaluation) -> None:
    _accountant(user)
    if run.status != Revaluation.Status.DRAFT:
        raise RevaluationError("A posted revaluation is never removed.")
    with audit_context("revaluation_discarded"):
        run.delete()
