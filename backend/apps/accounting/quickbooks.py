"""Opening balances from QuickBooks at go-live (backlog P2-28, spec 6.1 "Migration at go-live").

The Accountant uploads QuickBooks' own Excel exports, as they come out of QuickBooks:
- the trial balance at the go-live date (required);
- the A/R aging detail (open invoices), needed when debtors have a balance;
- the A/P aging detail (open bills), needed when creditors have a balance;
- the item list (to compare the stock value with the trial balance).

Everything is checked first, and nothing is made while anything is wrong. The check lists:
- the trial balance balances (and agrees with its TOTAL row);
- every QuickBooks account is found in the chart of accounts (by its full name,
  "Parent:Child", by its number, or by its own name when that is unique);
- the open invoices add up to the debtors balance and the open bills to the creditors
  balance, and every customer and supplier is found in the masters (by name);
- the stock value of the item list against the stock accounts (a warning: stock is loaded on
  Stores → Opening stock, which posts its own value).

When all is in order, one "opening balances" document is made, as one entry dated the trial
balance's date:
- every balance sheet account at its balance;
- debtors per customer and creditors per supplier, so their statements start right;
- stock accounts against Opening balance equity, because the opening stock count posts the
  stock value itself (Opening balance equity then comes back to nil when the two agree);
- the income and cost accounts together as one line to Retained earnings: the profit of the
  years before go-live.
The Director approves it before it is posted; it is posted once and never changes.

The open invoices and bills themselves, for receipts and payments to be matched to, are
loaded in a second step.
"""

import io
import re
import zipfile
from collections import OrderedDict, defaultdict
from datetime import date, datetime
from decimal import Decimal

from django.db import transaction
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.core import approvals
from apps.core.access import effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User

from . import journal
from .catalogue import PROFIT_AND_LOSS, section_of
from .models import Account, OpeningBalance, OpeningBalanceLine
from .services import AccountingError

DOC = "opening_balances"
ZERO = Decimal("0")
MAX_BYTES = 10 * 1024 * 1024
St = OpeningBalance.Status


class MigrationError(AccountingError):
    pass


def can_enter(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


# --- Reading the files -------------------------------------------------------------------------


def _rows(content: bytes, what: str) -> list[list]:
    if len(content) > MAX_BYTES:
        raise MigrationError(f"The {what} is larger than 10 MB.")
    try:
        book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise MigrationError(f"The {what} is not an Excel workbook (.xlsx).") from None
    return [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]


def _text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value if value is not None else "").split())


def _money(value, where: str) -> Decimal:
    from apps.banking.parsing import StatementFileError, money

    try:
        return money(value, where=where) or ZERO
    except StatementFileError as error:
        raise MigrationError(str(error)) from None


def _header(rows, wanted: set[str], what: str) -> tuple[int, dict[str, int]]:
    for at, row in enumerate(rows[:15]):
        names = {_text(c).lower(): i for i, c in enumerate(row) if _text(c)}
        if wanted <= set(names):
            return at, names
    raise MigrationError(
        f"The {what} does not look like the QuickBooks report: no heading row with "
        + ", ".join(sorted(wanted))
        + "."
    )


def _as_at(rows) -> date | None:
    for row in rows[:8]:
        for cell in row:
            if isinstance(cell, datetime):
                return cell.date()
            text = _text(cell).replace("As of ", "").replace("as of ", "")
            for fmt in ("%b %d, %y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d/%m/%Y"):
                try:
                    return datetime.strptime(text, fmt).date()
                except ValueError:
                    continue
    return None


def read_trial_balance(content: bytes) -> dict:
    rows = _rows(content, "trial balance")
    at, names = _header(rows, {"debit", "credit"}, "trial balance")
    d_col, c_col = names["debit"], names["credit"]
    accounts: list[tuple[str, Decimal, Decimal]] = []
    total = None
    for n, row in enumerate(rows[at + 1 :], start=at + 2):
        cells = list(row) + [None] * (max(d_col, c_col) + 1)
        label = next((_text(c) for c in cells[: min(d_col, c_col)] if _text(c)), "")
        debit = _money(cells[d_col], f"Row {n}: ")
        credit = _money(cells[c_col], f"Row {n}: ")
        if not label and not debit and not credit:
            continue
        if label.upper() == "TOTAL":
            total = (debit, credit)
            continue
        if not label:
            raise MigrationError(f"Trial balance row {n} has amounts but no account.")
        accounts.append((label, debit, credit))
    return {"as_at": _as_at(rows), "accounts": accounts, "total": total}


def read_receivables(content: bytes) -> dict:
    """A/R aging detail: customer name rows, their lines and "Total <customer>" rows."""
    rows = _rows(content, "A/R aging")
    at, names = _header(rows, {"type", "num", "open balance"}, "A/R aging")
    type_col, open_col = names["type"], names["open balance"]
    per: OrderedDict[str, Decimal] = OrderedDict()
    current = None
    lines = 0
    for n, row in enumerate(rows[at + 1 :], start=at + 2):
        cells = list(row) + [None] * (open_col + 1)
        kind = _text(cells[type_col])
        first = next((_text(c) for c in cells[:type_col] if _text(c)), "")
        if kind:
            if current is None:
                raise MigrationError(f"A/R aging row {n} comes before any customer name.")
            per[current] += _money(cells[open_col], f"A/R aging row {n}: ")
            lines += 1
        elif first.upper() == "TOTAL" or first.startswith("Total "):
            continue
        elif first:
            current = first
            per.setdefault(current, ZERO)
    return {"customers": per, "lines": lines}


def read_payables(content: bytes) -> dict:
    """A/P aging detail: lines grouped by age band; the supplier is in the Name column."""
    rows = _rows(content, "A/P aging")
    at, names = _header(rows, {"type", "name", "open balance"}, "A/P aging")
    type_col, name_col, open_col = names["type"], names["name"], names["open balance"]
    per: OrderedDict[str, Decimal] = OrderedDict()
    lines = 0
    for n, row in enumerate(rows[at + 1 :], start=at + 2):
        cells = list(row) + [None] * (max(name_col, open_col) + 1)
        if not _text(cells[type_col]):
            continue
        name = _text(cells[name_col])
        if not name:
            raise MigrationError(f"A/P aging row {n} has no supplier name.")
        per[name] = per.get(name, ZERO) + _money(cells[open_col], f"A/P aging row {n}: ")
        lines += 1
    return {"suppliers": per, "lines": lines}


def read_items(content: bytes) -> dict:
    rows = _rows(content, "item list")
    at, names = _header(rows, {"item", "type", "cost", "quantity on hand"}, "item list")
    value, count = ZERO, 0
    for n, row in enumerate(rows[at + 1 :], start=at + 2):
        cells = list(row) + [None] * (len(names) + 10)
        kind = _text(cells[names["type"]]).lower()
        if "stock" not in kind and "inventory" not in kind:
            continue
        if "non-stock" in kind:
            continue
        qty = _money(cells[names["quantity on hand"]], f"Item list row {n}: ")
        cost = _money(cells[names["cost"]], f"Item list row {n}: ")
        if qty:
            value += (qty * cost).quantize(Decimal("0.01"))
            count += 1
    return {"value": value, "items": count}


# --- Matching to the masters -------------------------------------------------------------------


def _full_names() -> dict[str, Account]:
    accounts = list(Account.objects.filter(merged_into=None))
    by_id = {a.pk: a for a in accounts}

    def full(a: Account) -> str:
        parts, seen = [a.name], {a.pk}
        while a.parent_id and a.parent_id in by_id and a.parent_id not in seen:
            a = by_id[a.parent_id]
            seen.add(a.pk)
            parts.append(a.name)
        return ":".join(reversed(parts))

    return {full(a).lower(): a for a in accounts}


def match_account(label: str, full: dict[str, Account], by_name: dict, by_number: dict):
    # QuickBooks shows "1010 · Cash in hand" when account numbers are switched on.
    number, name = None, label
    m = re.match(r"^\s*([0-9A-Z.-]+)\s*·\s*(.+)$", label)
    if m:
        number, name = m.group(1), m.group(2)
    name = ":".join(re.sub(r"^[0-9A-Z.-]+\s*·\s*", "", p).strip() for p in name.split(":"))
    if name.lower() in full:
        return full[name.lower()]
    if number and number.upper() in by_number:
        return by_number[number.upper()]
    leaf = name.split(":")[-1].strip().lower()
    found = by_name.get(leaf, [])
    return found[0] if len(found) == 1 else None


def _by_name(model):
    out = defaultdict(list)
    for row in model.objects.filter(is_active=True):
        out[_text(row.name).lower()].append(row)
    return out


def _party(name: str, index: dict):
    for key in (_text(name).lower(), _text(name.split(":")[0]).lower()):
        found = index.get(key, [])
        if len(found) == 1:
            return found[0]
    return None


def _system(role: str, name: str) -> Account:
    found = Account.objects.filter(system_role=role, is_active=True).first()
    if found is None:
        raise MigrationError(f"The chart of accounts has no active {name} account.")
    return found


# --- The check ---------------------------------------------------------------------------------


def check(
    *,
    trial_balance: bytes,
    receivables: bytes | None = None,
    payables: bytes | None = None,
    items: bytes | None = None,
) -> dict:
    """Read and check the files. Returns the report and, when nothing is wrong, the lines."""
    from apps.inventory.models import Item
    from apps.masters.models import Customer, Supplier

    errors: list[str] = []
    warnings: list[str] = []
    tb = read_trial_balance(trial_balance)
    debits = sum((d for _, d, _ in tb["accounts"]), ZERO)
    credits = sum((c for _, _, c in tb["accounts"]), ZERO)
    if not tb["as_at"]:
        errors.append("The trial balance's date was not found in its title.")
    if debits != credits:
        errors.append(
            f"The trial balance does not balance: debits {debits:,.2f}, credits {credits:,.2f} "
            f"(out by {abs(debits - credits):,.2f}). Correct it in QuickBooks first."
        )
    if tb["total"] and tb["total"] != (debits, credits):
        errors.append("The trial balance's TOTAL row does not agree with its lines.")

    full = _full_names()
    all_accounts = list(Account.objects.filter(merged_into=None))
    by_name = defaultdict(list)
    for a in all_accounts:
        by_name[a.name.lower()].append(a)
    by_number = {a.number.upper(): a for a in all_accounts if a.number}
    matched: list[tuple[str, Account, Decimal]] = []  # label, account, debit - credit
    missing = []
    for label, debit, credit in tb["accounts"]:
        account = match_account(label, full, by_name, by_number)
        if account is None:
            missing.append(label)
        elif not account.is_active:
            errors.append(f"{label}: the account {account.name} is inactive.")
        else:
            matched.append((label, account, debit - credit))
    if missing:
        errors.append(
            "These QuickBooks accounts are not in the chart of accounts (add them, or import the "
            "chart first): " + "; ".join(missing) + "."
        )

    receivable = sum((v for _, a, v in matched if a.account_type == "accounts_receivable"), ZERO)
    payable = -sum((v for _, a, v in matched if a.account_type == "accounts_payable"), ZERO)
    stock_ids = set(Item.objects.values_list("inventory_account_id", flat=True))
    stock = sum((v for _, a, v in matched if a.pk in stock_ids), ZERO)

    customers: list[tuple[object, Decimal]] = []
    if receivable or receivables:
        if receivables is None:
            errors.append(
                f"Debtors stand at {receivable:,.2f}: upload the A/R aging detail as well."
            )
        else:
            ar = read_receivables(receivables)
            ar_total = sum(ar["customers"].values(), ZERO)
            if ar_total != receivable:
                errors.append(
                    f"The open invoices add up to {ar_total:,.2f} but debtors in the trial "
                    f"balance are {receivable:,.2f} (out by {abs(ar_total - receivable):,.2f})."
                )
            index = _by_name(Customer)
            unknown = []
            for name, amount in ar["customers"].items():
                if not amount:
                    continue
                found = _party(name, index)
                if found is None:
                    unknown.append(name)
                else:
                    customers.append((found, amount))
            if unknown:
                errors.append(
                    "These customers are not in the customer list (add them first, with the "
                    "same name): " + "; ".join(unknown) + "."
                )
    suppliers: list[tuple[object, Decimal]] = []
    if payable or payables:
        if payables is None:
            errors.append(f"Creditors stand at {payable:,.2f}: upload the A/P aging detail too.")
        else:
            ap = read_payables(payables)
            ap_total = sum(ap["suppliers"].values(), ZERO)
            if ap_total != payable:
                errors.append(
                    f"The open bills add up to {ap_total:,.2f} but creditors in the trial "
                    f"balance are {payable:,.2f} (out by {abs(ap_total - payable):,.2f})."
                )
            index = _by_name(Supplier)
            unknown = []
            for name, amount in ap["suppliers"].items():
                if not amount:
                    continue
                found = _party(name, index)
                if found is None:
                    unknown.append(name)
                else:
                    suppliers.append((found, amount))
            if unknown:
                errors.append(
                    "These suppliers are not in the supplier list (add them first, with the "
                    "same name): " + "; ".join(unknown) + "."
                )
    item_value = None
    if items is not None:
        item_value = read_items(items)["value"]
        if item_value != stock:
            warnings.append(
                f"The item list values the stock at {item_value:,.2f}; the stock accounts in "
                f"the trial balance are {stock:,.2f}. Opening balance equity will show the "
                "difference until the stock count and the trial balance agree."
            )

    report = {
        "as_at": tb["as_at"].isoformat() if tb["as_at"] else None,
        "accounts": len(tb["accounts"]),
        "debits": f"{debits:.2f}",
        "credits": f"{credits:.2f}",
        "receivables": f"{receivable:.2f}",
        "payables": f"{payable:.2f}",
        "stock_in_trial_balance": f"{stock:.2f}",
        "stock_in_item_list": None if item_value is None else f"{item_value:.2f}",
        "customers": len(customers),
        "suppliers": len(suppliers),
        "errors": errors,
        "warnings": warnings,
    }
    lines = [] if errors else _lines(matched, customers, suppliers, stock_ids)
    return {"report": report, "lines": lines, "as_at": tb["as_at"]}


def _lines(matched, customers, suppliers, stock_ids) -> list[dict]:
    retained = _system("retained_earnings", "Retained earnings")
    equity = _system("opening_balance_equity", "Opening balance equity")
    ar = _system("accounts_receivable", "Accounts receivable")
    ap = _system("accounts_payable", "Accounts payable")
    out: list[dict] = []

    def add(account, amount, description, customer=None, supplier=None):
        if amount:
            out.append(
                {
                    "account": account,
                    "debit": max(amount, ZERO),
                    "credit": max(-amount, ZERO),
                    "description": description[:300],
                    "customer": customer,
                    "supplier": supplier,
                }
            )

    profit = ZERO
    for label, account, amount in matched:
        if section_of(account.account_type) == PROFIT_AND_LOSS:
            profit -= amount
        elif account.account_type in ("accounts_receivable", "accounts_payable"):
            continue  # per customer and supplier below
        elif account.pk in stock_ids:
            add(equity, amount, f"Stock in QuickBooks ({label}); the opening stock count posts it")
        else:
            add(account, amount, f"QuickBooks: {label}")
    for customer, amount in customers:
        add(ar, amount, "Open invoices brought over from QuickBooks", customer=customer)
    for supplier, amount in suppliers:
        add(ap, -amount, "Open bills brought over from QuickBooks", supplier=supplier)
    add(retained, -profit, "Profit before go-live (QuickBooks income and costs)")
    return out


# --- The document ------------------------------------------------------------------------------


def make(user: User, **files) -> OpeningBalance:
    """Check the files and, if nothing is wrong, make the opening balances as a draft."""
    if not can_enter(user):
        raise MigrationError("Only the Accountant brings over the opening balances.")
    if OpeningBalance.objects.filter(status=St.POSTED).exists():
        raise MigrationError("The opening balances are posted already.")
    found = check(**files)
    if found["report"]["errors"]:
        raise MigrationError("Correct what the check found first.")
    with audit_context("opening_balances_made"), transaction.atomic():
        if OpeningBalance.objects.filter(status=St.AWAITING_APPROVAL).exists():
            raise MigrationError("Opening balances are waiting for the Director already.")
        doc = OpeningBalance.objects.filter(status=St.DRAFT, created_by=user).first()
        if doc is None:
            doc = OpeningBalance.objects.create(
                as_at=found["as_at"], report=found["report"], created_by=user
            )
        else:  # a draft, or one the Director returned: filled in again
            doc.lines.all().delete()
            doc.as_at, doc.report = found["as_at"], found["report"]
            doc.save(update_fields=["as_at", "report"])
        OpeningBalanceLine.objects.bulk_create(
            OpeningBalanceLine(opening=doc, line_no=n, **line)
            for n, line in enumerate(found["lines"], start=1)
        )
        return doc


def _draft(user: User, doc: OpeningBalance) -> OpeningBalance:
    doc = OpeningBalance.objects.select_for_update().get(pk=doc.pk)
    if doc.status != St.DRAFT or doc.created_by_id != user.pk:
        raise MigrationError("Only the person who made the draft sends or deletes it.")
    return doc


def delete(user: User, doc: OpeningBalance) -> None:
    with audit_context("opening_balances_deleted"), transaction.atomic():
        doc = _draft(user, doc)
        if approvals.state_of(DOC, doc.pk) is not None:
            raise MigrationError("Opening balances sent for approval are kept.")
        doc.delete()


def submit(user: User, doc: OpeningBalance, comment: str = "") -> OpeningBalance:
    with audit_context("opening_balances_submitted", comment), transaction.atomic():
        doc = _draft(user, doc)
        try:
            approvals.submit(
                user,
                DOC,
                doc.pk,
                created_by=doc.created_by,
                comment=comment,
                title=f"Opening balances from QuickBooks at {doc.as_at:%d %b %Y}",
                link="/migration",
            )
        except ApprovalError as error:
            raise MigrationError(str(error)) from None
        doc.status = St.AWAITING_APPROVAL
        doc.save(update_fields=["status"])
        return doc


def _waiting(doc: OpeningBalance) -> OpeningBalance:
    doc = OpeningBalance.objects.select_for_update().get(pk=doc.pk)
    if doc.status != St.AWAITING_APPROVAL:
        raise MigrationError("The opening balances are not waiting for approval.")
    return doc


def approve(user: User, doc: OpeningBalance, comment: str = "") -> OpeningBalance:
    with transaction.atomic():
        doc = _waiting(doc)
        if OpeningBalance.objects.filter(status=St.POSTED).exists():
            raise MigrationError("Opening balances are posted already.")
        try:
            state = approvals.approve(user, DOC, doc.pk, comment)
        except ApprovalError as error:
            raise MigrationError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("opening_balances_posted", comment):
                lines = [
                    journal.Line(
                        account=x.account,
                        debit=x.debit,
                        credit=x.credit,
                        customer=x.customer,
                        supplier=x.supplier,
                        description=x.description,
                    )
                    for x in doc.lines.select_related("account", "customer", "supplier")
                ]
                doc.journal_entry = journal.post(
                    user,
                    entry_date=doc.as_at,
                    narration=f"Opening balances from QuickBooks at {doc.as_at:%d %b %Y}",
                    lines=lines,
                    source_type="opening_balances",
                    source_id=f"{doc.as_at:%Y-%m-%d}",
                    max_lines=20000,  # one line per customer and supplier with a balance
                )
                doc.status = St.POSTED
                doc.save(update_fields=["status", "journal_entry"])
        return doc


def send_back(user: User, doc: OpeningBalance, reason: str) -> OpeningBalance:
    with transaction.atomic():
        doc = _waiting(doc)
        try:
            approvals.send_back(user, DOC, doc.pk, reason)
        except ApprovalError as error:
            raise MigrationError(str(error)) from None
        doc.status = St.DRAFT
        doc.save(update_fields=["status"])
        return doc


def reject(user: User, doc: OpeningBalance, reason: str) -> OpeningBalance:
    with transaction.atomic():
        doc = _waiting(doc)
        try:
            approvals.reject(user, DOC, doc.pk, reason)
        except ApprovalError as error:
            raise MigrationError(str(error)) from None
        doc.status = St.REJECTED
        doc.save(update_fields=["status"])
        return doc


def can_approve(user: User, doc: OpeningBalance) -> bool:
    if doc.status != St.AWAITING_APPROVAL:
        return False
    state = approvals.state_of(DOC, doc.pk)
    return state is not None and approvals.why_not(user, state) is None
