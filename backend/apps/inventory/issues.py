"""Stock issues and returns to stores (backlog P2-18, spec 6, IAS 2).

- The stores person issues material from a main store to a division or one of its sections
  (to a job or production order in Phase 3). Lots are taken oldest first unless one is
  chosen, so every issue says which lot went where. The value is the weighted average cost of
  the item; issuing the last of an item takes exactly the value left. Posted at once: Dr the
  item's expense account (Raw materials used if it has none) for the division, Cr its
  inventory account.
- Material not used comes back against its issue, into the same store and lot, at the cost it
  was issued at, never more than was issued: Dr inventory, Cr the same expense.
- Issues and returns never change (database guard); a mistake is corrected by another one.
"""

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Min, QuerySet, Sum
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account
from apps.accounting.services import AccountingError
from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters.models import Section

from . import items as item_master
from .models import Item, StockIssue, StockIssueLine, StockMovement, Store
from .stock import StockError

ZERO = Decimal("0")
CENT = Decimal("0.01")
QTY = Decimal("0.001")
COST = Decimal("0.0001")
K = StockMovement.Kind
MAX_LINES = 100


def can_issue(user: User) -> bool:
    return effective_access(user).has("stores", "enter")


def _quantity(value, where: str) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise StockError(f"{where}: the quantity is not a number.") from None
    if not number.is_finite() or number <= 0 or number != number.quantize(QTY):
        raise StockError(f"{where}: the quantity must be more than 0, with at most 3 decimals.")
    return number


def main_store(user: User, store) -> Store:
    if not isinstance(store, Store) or not store.is_active or store.kind != Store.Kind.MAIN:
        raise StockError("Choose an active main store.")
    if not division_scope(user).filter(pk=store.division_id).exists():
        raise StockError(f"You do not work in division {store.division.code}.")
    return store


def _day(value) -> date:
    if not isinstance(value, date) or value > timezone.localdate():
        raise StockError("Give the date (not in the future).")
    return value


def system_account(role: str, name: str) -> Account:
    account = Account.objects.filter(system_role=role, is_active=True).first()
    if account is None:
        raise StockError(f"The chart of accounts has no active {name} account.")
    return account


def lots(item: Item, store: Store) -> list[tuple[str, Decimal]]:
    """The lots of an item in a store with something in them, oldest first."""
    rows = (
        StockMovement.objects.filter(item=item, store=store)
        .values("lot_no")
        .annotate(quantity=Sum("quantity"), first=Min("id"))
        .filter(quantity__gt=0)
        .order_by("first")
    )
    return [(r["lot_no"], r["quantity"]) for r in rows]


def main_totals(item: Item) -> tuple[Decimal, Decimal]:
    """Quantity and value of the item in all main stores."""
    found = StockMovement.objects.filter(item=item, store__kind=Store.Kind.MAIN).aggregate(
        q=Sum("quantity"), v=Sum("value")
    )
    return found["q"] or ZERO, found["v"] or ZERO


def cost_of(item: Item) -> Decimal:
    quantity, value = main_totals(item)
    if quantity <= 0:
        return ZERO
    return (value / quantity).quantize(COST, ROUND_HALF_UP)


def take_value(item: Item, quantity: Decimal, taken: tuple[Decimal, Decimal]) -> Decimal:
    """The value of `quantity` leaving the main stores at the average cost; the last of the
    item takes exactly the value left. `taken` is (quantity, value) this document has taken
    of the item so far."""
    on_hand, value = main_totals(item)
    if quantity == on_hand - taken[0]:
        return value - taken[1]
    return (quantity * cost_of(item)).quantize(CENT, ROUND_HALF_UP)


def expense_account(item: Item) -> Account:
    return item.expense_account or system_account("materials_used", "Raw materials used")


def inventory_account(item: Item) -> Account:
    if item.inventory_account is None:
        raise StockError(f"Item {item.code} has no inventory account (the Accountant sets it).")
    return item.inventory_account


@dataclass
class IssueLine:
    item: Item | None
    quantity: object
    lot_no: str = ""


def _post(user, document: StockIssue, pairs: list[tuple[Item, Decimal]], *, into_stock: bool):
    """Dr expense / Cr inventory per item (an issue), or the other way (a return)."""
    lines = []
    for item, value in pairs:
        if not value:
            continue
        cost_side = journal.Line(
            account=expense_account(item),
            division=document.division,
            description=f"{document.number} {item.code}",
        )
        stock_side = journal.Line(
            account=inventory_account(item),
            division=document.division,
            description=f"{document.number} {item.code} {item.name}",
        )
        if into_stock:
            stock_side.debit, cost_side.credit = value, value
        else:
            cost_side.debit, stock_side.credit = value, value
        lines += [cost_side, stock_side]
    if not lines:
        return None
    where = document.section.name if document.section_id else document.division.code
    text = "Return to stores" if into_stock else "Material issued"
    try:
        return journal.post(
            user,
            entry_date=document.issue_date,
            narration=f"{text} {document.number}, {document.store.code} ↔ {where}",
            lines=lines,
            source_type="stock_issue",
            source_id=document.number,
        )
    except AccountingError as error:
        raise StockError(str(error)) from None


def issue(
    user: User,
    *,
    store,
    issue_date,
    lines: list[IssueLine],
    section: Section | None = None,
    purpose: str = "",
) -> StockIssue:
    if not can_issue(user):
        raise StockError("Only the stores person issues material.")
    store = main_store(user, store)
    issue_date = _day(issue_date)
    if not lines:
        raise StockError("Add at least one item.")
    if len(lines) > MAX_LINES:
        raise StockError(f"An issue can have at most {MAX_LINES} lines.")
    if section is not None and (section.division_id != store.division_id or not section.is_active):
        raise StockError(f"Section {section.name} is not an active section of {store.division}.")
    with audit_context("stock_issued"), transaction.atomic():
        Store.objects.select_for_update().filter(pk=store.pk).first()
        plan = []  # (item, lot, quantity, value)
        taken: dict[int, tuple[Decimal, Decimal]] = {}
        for i, wanted in enumerate(lines, start=1):
            where = f"Line {i}"
            item = wanted.item
            if not isinstance(item, Item) or not item.is_stock:
                raise StockError(f"{where}: choose a stock item.")
            quantity = _quantity(wanted.quantity, where)
            available = lots(item, store)
            if wanted.lot_no:
                available = [(lot, q) for lot, q in available if lot == wanted.lot_no.strip()]
                if not available:
                    raise StockError(f"{where}: lot {wanted.lot_no} of {item.code} is not here.")
            used: dict[str, Decimal] = {}
            for row_item, lot, part, _ in plan:
                if row_item.pk == item.pk:
                    used[lot] = used.get(lot, ZERO) + part
            left = quantity
            for lot, on_hand in available:
                free = on_hand - used.get(lot, ZERO)
                if left <= 0 or free <= 0:
                    continue
                part = min(free, left)
                so_far = taken.get(item.pk, (ZERO, ZERO))
                value = take_value(item, part, so_far)
                plan.append((item, lot, part, value))
                taken[item.pk] = (so_far[0] + part, so_far[1] + value)
                left -= part
            if left > 0:
                raise StockError(
                    f"{where}: only {quantity - left:,.3f} {item.unit} of {item.code} is in "
                    f"{store.code}."
                )
        try:
            number = allocate("stock_issue", on_date=issue_date)
        except NumberSeriesError as error:
            raise StockError(str(error)) from None
        document = StockIssue(
            number=number,
            kind=StockIssue.Kind.ISSUE,
            store=store,
            division=store.division,
            section=section,
            issue_date=issue_date,
            purpose=(purpose or "").strip()[:300],
            created_by=user,
        )
        items = {item.pk: item for item, *_ in plan}
        entry = _post(
            user, document, [(items[pk], v) for pk, (_, v) in taken.items()], into_stock=False
        )
        document.journal_entry = entry
        document.total_value = sum((v for *_, v in plan), ZERO)
        document.save()
        for n, (item, lot, part, value) in enumerate(plan, start=1):
            line = StockIssueLine.objects.create(
                issue=document,
                line_no=n,
                item=item,
                lot_no=lot,
                quantity=part,
                unit_cost=(value / part).quantize(COST, ROUND_HALF_UP),
                value=value,
            )
            StockMovement.objects.create(
                item=item,
                store=store,
                division=store.division,
                lot_no=lot,
                kind=K.ISSUED,
                movement_date=issue_date,
                quantity=-part,
                value=-value,
                issue_line=line,
                journal_entry=entry if value else None,
                created_by=user,
            )
            item_master.mark_used(item)
        return document


def returned_already(line: StockIssueLine) -> Decimal:
    return line.returns.aggregate(q=Sum("quantity"))["q"] or ZERO


def give_back(
    user: User, original: StockIssue, *, return_date, lines: list[tuple[StockIssueLine, object]]
) -> StockIssue:
    """Bring unused material back against its issue, into the same store and lot."""
    if not can_issue(user):
        raise StockError("Only the stores person takes material back.")
    if original.kind != StockIssue.Kind.ISSUE:
        raise StockError("Material comes back against an issue.")
    main_store(user, original.store)
    return_date = _day(return_date)
    if return_date < original.issue_date:
        raise StockError("Material comes back on or after the day it was issued.")
    if not lines:
        raise StockError("Say what comes back.")
    with audit_context("stock_returned"), transaction.atomic():
        StockIssue.objects.select_for_update().filter(pk=original.pk).first()
        checked = []
        for issue_line, quantity in lines:
            where = f"{issue_line.item.code} lot {issue_line.lot_no}"
            if issue_line.issue_id != original.pk:
                raise StockError(f"{where} is not on issue {original.number}.")
            quantity = _quantity(quantity, where)
            left = issue_line.quantity - returned_already(issue_line)
            if quantity > left:
                raise StockError(f"{where}: only {left:,.3f} was issued and not yet returned.")
            if quantity == left:
                value = issue_line.value - (
                    issue_line.returns.aggregate(v=Sum("value"))["v"] or ZERO
                )
            else:
                value = (quantity * issue_line.unit_cost).quantize(CENT, ROUND_HALF_UP)
            checked.append((issue_line, quantity, value))
        try:
            number = allocate("stock_issue", on_date=return_date)
        except NumberSeriesError as error:
            raise StockError(str(error)) from None
        document = StockIssue(
            number=number,
            kind=StockIssue.Kind.RETURN,
            store=original.store,
            division=original.division,
            section=original.section,
            issue_date=return_date,
            purpose=f"Return against {original.number}",
            returns=original,
            created_by=user,
        )
        totals: dict[int, list] = {}
        for issue_line, _, value in checked:
            totals.setdefault(issue_line.item_id, [issue_line.item, ZERO])[1] += value
        entry = _post(user, document, list(map(tuple, totals.values())), into_stock=True)
        document.journal_entry = entry
        document.total_value = sum((v for *_, v in checked), ZERO)
        document.save()
        for n, (issue_line, quantity, value) in enumerate(checked, start=1):
            line = StockIssueLine.objects.create(
                issue=document,
                line_no=n,
                item=issue_line.item,
                lot_no=issue_line.lot_no,
                quantity=quantity,
                unit_cost=issue_line.unit_cost,
                value=value,
                returned_from=issue_line,
            )
            StockMovement.objects.create(
                item=issue_line.item,
                store=original.store,
                division=original.division,
                lot_no=issue_line.lot_no,
                kind=K.BACK,
                movement_date=return_date,
                quantity=quantity,
                value=value,
                issue_line=line,
                journal_entry=entry if value else None,
                created_by=user,
            )
        return document


def visible(user: User) -> QuerySet[StockIssue]:
    access = effective_access(user)
    if not (access.has("stores", "view") or access.has("accounting", "view")):
        return StockIssue.objects.none()
    return StockIssue.objects.filter(division__in=division_scope(user))
