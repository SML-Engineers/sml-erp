"""Cash flow planner (backlog P2-25, spec 7A): the company's bank and cash balance projected
day by day for 13 weeks. Nothing here is ever posted.

- It starts from today's balance of the Bank-type accounts (bank, cash, petty cash).
- Money in:
  - what customers owe on issued invoices, expected on the due date moved by how late (on
    average, over the last year) that customer has paid; anything expected before today is
    counted today;
  - post-dated cheques received, on the cheque's date, and cheques received but not yet
    banked, today (their invoices are not counted twice).
- Money out:
  - what we owe suppliers (invoices and lines of vouchers not yet paid), on the due date, or
    today when overdue;
  - recurring journals that move money in or out of a bank or cash account, on each date of
    their schedule.
- "What-if" items typed by the Accountant (a machine to buy, a loan to take) change the
  projection and can be switched off on the page; they are never posted.
- Payroll is added when Phase 2b builds it.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import User

from .cash_flow import CASH_TYPES, _cash
from .models import CashPlanItem, RecurringJournal
from .recurring import STEP, _add_months, first_on_or_after
from .services import AccountingError

ZERO = Decimal("0")
CENT = Decimal("0.01")
WEEKS = 13


@dataclass
class Flow:
    day: date
    amount: Decimal  # in is positive, out negative
    kind: str  # receivable, cheque, payable, recurring, what_if
    label: str
    link: str = ""
    item_id: int | None = None


def can_plan(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


# --- Customers -------------------------------------------------------------------------------


def days_late(today: date) -> dict[int, int]:
    """Per customer, how many days after the due date they paid on average over the last
    year, weighted by amount (never less than nil)."""
    from apps.sales.models import CustomerReceipt, ReceiptAllocation

    rows = ReceiptAllocation.objects.filter(
        receipt__status=CustomerReceipt.Status.POSTED,
        receipt__receipt_date__gte=today - timedelta(days=365),
    ).select_related("receipt", "invoice")
    weight: dict[int, Decimal] = defaultdict(Decimal)
    total: dict[int, Decimal] = defaultdict(Decimal)
    for a in rows:
        amount = a.amount * (a.invoice.exchange_rate or 1)
        late = (a.receipt.receipt_date - a.invoice.due_date).days
        weight[a.invoice.customer_id] += amount
        total[a.invoice.customer_id] += amount * late
    return {
        c: max(0, int((total[c] / w).to_integral_value(ROUND_HALF_UP)))
        for c, w in weight.items()
        if w
    }


def _money_in(user: User, today: date, end: date) -> list[Flow]:
    from apps.sales import receivables
    from apps.sales.models import CustomerReceipt, ReceiptAllocation

    flows: list[Flow] = []
    held = CustomerReceipt.objects.filter(
        method="cheque",
        status__in=[CustomerReceipt.Status.POST_DATED, CustomerReceipt.Status.POSTED],
        deposit_line__isnull=True,
        returned_on__isnull=True,
    ).select_related("customer")
    for r in held:
        day = max(today, r.cheque_date or today)
        if day <= end:
            amount = r.amount_lkr or (r.amount * r.exchange_rate).quantize(CENT, ROUND_HALF_UP)
            flows.append(
                Flow(
                    day,
                    amount,
                    "cheque",
                    f"Cheque {r.reference} from {r.customer.name}".replace("  ", " "),
                    f"/receipts/{r.pk}",
                )
            )
    # A post-dated cheque has not yet taken anything off its invoices: take it off here.
    promised: dict[int, Decimal] = defaultdict(Decimal)
    for a in ReceiptAllocation.objects.filter(
        receipt__status=CustomerReceipt.Status.POST_DATED
    ).select_related("invoice"):
        promised[a.invoice_id] += (a.amount * (a.invoice.exchange_rate or 1)).quantize(
            CENT, ROUND_HALF_UP
        )
    late = days_late(today)
    for item in receivables.open_items(user, today):
        invoice = item["invoice"]
        amount = item["open_lkr"] - promised.get(invoice.pk, ZERO)
        if amount <= 0:
            continue
        day = max(today, invoice.due_date + timedelta(days=late.get(invoice.customer_id, 0)))
        if day <= end:
            flows.append(
                Flow(
                    day,
                    amount,
                    "receivable",
                    f"{invoice.customer.name}: {invoice.number}",
                    f"/tax-invoices/{invoice.pk}",
                )
            )
    return flows


# --- Suppliers and recurring payments ----------------------------------------------------------


def _money_out(user: User, today: date, end: date) -> list[Flow]:
    from apps.purchasing import payables

    flows = []
    for item in payables.open_items(today, user=user):
        day = max(today, item["due_date"])
        if day <= end:
            flows.append(
                Flow(
                    day,
                    -item["open"],
                    "payable",
                    f"{item['supplier'].name}: {item['reference'] or item['document']}",
                    item["link"],
                )
            )
    return flows


def _recurring(today: date, end: date) -> list[Flow]:
    flows = []
    for template in RecurringJournal.objects.filter(is_active=True).prefetch_related(
        "lines__account"
    ):
        effect = sum(
            (
                x.debit - x.credit
                for x in template.lines.all()
                if x.account.account_type in CASH_TYPES
            ),
            ZERO,
        )
        if not effect:
            continue
        day = first_on_or_after(template, max(today, template.next_date))
        while day <= end and (template.end_date is None or day <= template.end_date):
            flows.append(
                Flow(day, effect, "recurring", template.name, f"/journals/recurring/{template.pk}")
            )
            day = _add_months(day, STEP[template.frequency], template.day_of_month)
    return flows


def _what_ifs(today: date, end: date, without: set[int]) -> list[Flow]:
    return [
        Flow(max(today, i.on_date), i.amount, "what_if", i.description, item_id=i.pk)
        for i in CashPlanItem.objects.filter(on_date__lte=end).exclude(pk__in=without)
    ]


# --- The projection ----------------------------------------------------------------------------


def projection(user: User, today: date | None = None, without: set[int] = frozenset()) -> dict:
    today = today or timezone.localdate()
    end = today + timedelta(weeks=WEEKS) - timedelta(days=1)
    flows = (
        _money_in(user, today, end)
        + _money_out(user, today, end)
        + _recurring(today, end)
        + _what_ifs(today, end, set(without))
    )
    flows.sort(key=lambda f: (f.day, -f.amount))
    by_day: dict[date, list[Flow]] = defaultdict(list)
    for f in flows:
        by_day[f.day].append(f)
    balance = opening = _cash(today - timedelta(days=1))
    days, weeks = [], []
    lowest = (opening, today)
    for n in range(WEEKS * 7):
        day = today + timedelta(days=n)
        money_in = sum((f.amount for f in by_day[day] if f.amount > 0), ZERO)
        money_out = -sum((f.amount for f in by_day[day] if f.amount < 0), ZERO)
        start = balance
        balance = start + money_in - money_out
        days.append(
            {"day": day, "opening": start, "in": money_in, "out": money_out, "closing": balance}
        )
        if balance < lowest[0]:
            lowest = (balance, day)
        if n % 7 == 6:
            week = days[-7:]
            weeks.append(
                {
                    "from": week[0]["day"],
                    "to": day,
                    "opening": week[0]["opening"],
                    "in": sum((d["in"] for d in week), ZERO),
                    "out": sum((d["out"] for d in week), ZERO),
                    "closing": balance,
                    "lowest": min(d["closing"] for d in week),
                }
            )
    return {
        "today": today,
        "end": end,
        "opening": opening,
        "closing": balance,
        "lowest": {"amount": lowest[0], "day": lowest[1]},
        "weeks": weeks,
        "days": days,
        "flows": flows,
        "what_ifs": list(CashPlanItem.objects.select_related("created_by")),
        "payment_days_late": days_late(today),
    }


# --- What-if items -----------------------------------------------------------------------------


def _amount(value) -> Decimal:
    if isinstance(value, float):
        raise AccountingError("The amount must be exact.")
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise AccountingError("The amount is not a number.") from None
    if not amount.is_finite() or amount != amount.quantize(CENT) or not amount:
        raise AccountingError("Give an amount to the cent, not nil.")
    return amount


def add_what_if(user: User, *, description: str, on_date: date, amount, money_in: bool):
    if not can_plan(user):
        raise AccountingError("Only the Accountant adds what-if items.")
    description = " ".join((description or "").split())
    if not description:
        raise AccountingError("Say what the item is.")
    value = abs(_amount(amount))
    with audit_context("cash_plan_item_added"):
        return CashPlanItem.objects.create(
            description=description[:200],
            on_date=on_date,
            amount=value if money_in else -value,
            created_by=user,
        )


def remove_what_if(user: User, item: CashPlanItem) -> None:
    if not can_plan(user):
        raise AccountingError("Only the Accountant removes what-if items.")
    with audit_context("cash_plan_item_removed"):
        item.delete()
