"""Opening stock (backlog P16-15; owner's decision of 2 Nov 2026: the stores are counted and
the balances loaded at go-live).

- The Accountant (Accounting: Enter) loads the count from an Excel sheet: item code, main
  store, quantity, cost per unit in LKR and, if wanted, the lot or heat number. The file is
  checked first and is all or nothing; every refused row is listed. Loading it again
  replaces the draft's lines.
- Opening stock is only for an item and store with no stock movement yet: anything that has
  already moved through a GRN is not "opening" any more. An item and store can be on only one
  opening stock that is not rejected.
- The Director approves it (approval engine, "opening_stock"); nobody approves their own.
  Approval puts the quantities into the main stores as "Opening stock" movements at that cost
  and posts Dr each item's inventory account, Cr Opening balance equity, per division, in the
  same transaction. Returned, it is a draft again; rejected, it stays rejected.
- Once sent it never changes (database guard); only a draft is deleted.
"""

import io
import zipfile
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.accounting import journal
from apps.accounting.models import Account
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.access import effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters import excel

from .models import Item, OpeningStock, OpeningStockLine, StockMovement, Store

DOC = "opening_stock"
St = OpeningStock.Status
SHEET = "Opening stock"
COLUMNS = ["Item code", "Store", "Quantity", "Cost per unit (LKR)", "Lot or heat no."]
CENT = Decimal("0.01")
QTY = Decimal("0.001")
COST = Decimal("0.0001")


class OpeningError(Exception):
    pass


# --- Who may do what -----------------------------------------------------------------------


def can_view(user: User) -> bool:
    access = effective_access(user)
    return access.has("accounting", "view") or access.has("stores", "view")


def can_enter(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def visible(user: User) -> QuerySet[OpeningStock]:
    return OpeningStock.objects.all() if can_view(user) else OpeningStock.objects.none()


def can_edit(user: User, opening: OpeningStock) -> bool:
    return opening.status == St.DRAFT and opening.created_by_id == user.pk and can_enter(user)


def can_approve(user: User, opening: OpeningStock) -> bool:
    if opening.status != St.AWAITING_APPROVAL:
        return False
    state = approvals.state_of(DOC, opening.pk)
    return state is not None and approvals.why_not(user, state) is None


# --- The Excel sheet --------------------------------------------------------------------------


def template() -> bytes:
    """The sheet to fill in, with the active stock items and main stores to choose from."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    excel._sheet(workbook, SHEET, COLUMNS, [])
    items = Item.objects.filter(is_active=True, is_stock=True).order_by("code")
    excel._sheet(
        workbook,
        "Items",
        ["Item code", "Name", "Unit", "Division"],
        [[i.code, i.name, i.unit, i.division.code if i.division_id else ""] for i in items],
    )
    stores = Store.objects.filter(is_active=True, kind=Store.Kind.MAIN).select_related("division")
    excel._sheet(
        workbook,
        "Stores",
        ["Store", "Name", "Division"],
        [[s.code, s.name, s.division.code] for s in stores.order_by("code")],
    )
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _number(value, what: str, step: Decimal) -> Decimal:
    raw = excel._number(value)
    if raw in (None, ""):
        raise OpeningError(f"Enter the {what}.")
    try:
        number = Decimal(str(raw).replace(",", "").strip())
    except InvalidOperation:
        raise OpeningError(f"The {what} is not a number.") from None
    if not number.is_finite() or number <= 0:
        raise OpeningError(f"The {what} must be more than 0.")
    if number != number.quantize(step):
        places = len(str(step).split(".")[1])
        raise OpeningError(f"The {what} can have at most {places} decimal places.")
    return number


def _already_moved(item: Item, store: Store) -> bool:
    return StockMovement.objects.filter(item=item, store=store).exists()


def _elsewhere(item: Item, store: Store, opening: OpeningStock | None) -> str | None:
    other = (
        OpeningStockLine.objects.filter(item=item, store=store)
        .exclude(opening__status=St.REJECTED)
        .select_related("opening")
    )
    if opening is not None and opening.pk:
        other = other.exclude(opening=opening)
    found = other.first()
    return found.opening.number if found else None


def _row(row: dict, opening: OpeningStock | None) -> dict:
    code = excel._text(row.get("Item code")).upper()
    item = Item.objects.filter(code=code).select_related("division").first()
    if item is None:
        raise OpeningError(f"There is no item {code or '(blank)'}.")
    if not item.is_active or not item.is_stock:
        raise OpeningError(f"Item {code} is not an active stock item.")
    store_code = excel._text(row.get("Store")).upper()
    store = Store.objects.filter(code=store_code).select_related("division").first()
    if store is None or not store.is_active or store.kind != Store.Kind.MAIN:
        raise OpeningError(f"{store_code or '(blank)'} is not an active main store.")
    if item.division_id and item.division_id != store.division_id:
        raise OpeningError(f"Item {code} belongs to {item.division.code}, not {store.code}.")
    if _already_moved(item, store):
        raise OpeningError(
            f"{code} has already moved in or out of {store.code}: opening stock is only for "
            "stock that was there before the ERP."
        )
    clash = _elsewhere(item, store, opening)
    if clash:
        raise OpeningError(f"{code} in {store.code} is already on opening stock {clash}.")
    quantity = _number(row.get("Quantity"), "quantity", QTY)
    cost = _number(row.get("Cost per unit (LKR)"), "cost per unit", COST)
    lot = excel._text(row.get("Lot or heat no."))
    if len(lot) > 30:
        raise OpeningError("The lot or heat number can have at most 30 characters.")
    return {
        "item": item,
        "store": store,
        "lot": lot,
        "quantity": quantity,
        "unit_cost": cost,
        "value": (quantity * cost).quantize(CENT, ROUND_HALF_UP),
    }


def read(content: bytes, opening: OpeningStock | None = None) -> list[dict]:
    """The rows of the sheet, checked. Raises excel.ImportRefused listing every bad row."""
    if len(content) > excel.MAX_BYTES:
        raise excel.ImportRefused(["The file must be 5 MB or smaller."])
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise excel.ImportRefused(["The file is not an Excel workbook (.xlsx)."]) from None
    rows = excel._rows(workbook, SHEET, COLUMNS)
    if not rows:
        raise excel.ImportRefused([f"The workbook has no rows on a sheet called {SHEET}."])
    found, errors, seen = [], [], {}
    for number, row in rows:
        try:
            checked = _row(row, opening)
        except OpeningError as error:
            errors.append(f"Row {number}: {error}")
            continue
        key = (checked["item"].pk, checked["store"].pk, checked["lot"].upper())
        if key in seen:
            errors.append(f"Row {number}: the same item, store and lot as row {seen[key]}.")
            continue
        seen[key] = number
        found.append(checked)
    if errors:
        raise excel.ImportRefused(errors)
    return found


def _header(opening: OpeningStock, count_date, notes) -> None:
    if not isinstance(count_date, date):
        raise excel.ImportRefused(["Give the date the stores were counted."])
    if count_date > timezone.localdate():
        raise excel.ImportRefused(["The count date cannot be in the future."])
    if journal.is_closed(count_date):
        raise excel.ImportRefused([f"The period {count_date:%Y-%m} is closed."])
    opening.count_date = count_date
    opening.notes = (notes or "").strip()[:5000]


def _fill(opening: OpeningStock, rows: list[dict]) -> None:
    opening.lines.all().delete()
    for n, r in enumerate(rows, start=1):
        OpeningStockLine.objects.create(
            opening=opening,
            line_no=n,
            item=r["item"],
            store=r["store"],
            lot_no=f"{opening.number}-{r['lot'] or n}"[:40],
            quantity=r["quantity"],
            unit_cost=r["unit_cost"],
            value=r["value"],
        )


def load(
    user: User,
    opening: OpeningStock | None,
    *,
    content: bytes,
    count_date,
    notes: str = "",
    dry_run: bool = False,
) -> tuple[OpeningStock | None, dict]:
    """Make a draft from the sheet, or replace a draft's lines. `dry_run` only checks.
    Returns the opening stock (None for a dry run) and the count of rows and their value."""
    if not can_enter(user):
        raise excel.ImportRefused(["Only the Accountant loads opening stock."])
    if opening is not None and not can_edit(user, opening):
        raise excel.ImportRefused(["Only the person who made a draft opening stock changes it."])
    rows = read(content, opening)
    summary = {"rows": len(rows), "value": f"{sum((r['value'] for r in rows), Decimal('0')):.2f}"}
    if dry_run:
        probe = OpeningStock()
        _header(probe, count_date, notes)
        return None, summary
    event = "opening_stock_changed" if opening else "opening_stock_created"
    with audit_context(event), transaction.atomic():
        if opening is None:
            today = timezone.localdate()
            opening = OpeningStock(created_by=user)
            _header(opening, count_date, notes)
            try:
                opening.number = allocate(DOC, on_date=today)
            except NumberSeriesError as error:
                raise excel.ImportRefused([str(error)]) from None
        else:
            opening = OpeningStock.objects.select_for_update().get(pk=opening.pk)
            _header(opening, count_date, notes)
            opening.updated_at = timezone.now()
        opening.save()
        _fill(opening, rows)
        return opening, summary


def total(opening: OpeningStock) -> Decimal:
    return sum((x.value for x in opening.lines.all()), Decimal("0"))


def delete(user: User, opening: OpeningStock) -> None:
    with audit_context("opening_stock_deleted"), transaction.atomic():
        opening = OpeningStock.objects.select_for_update().get(pk=opening.pk)
        if not can_edit(user, opening):
            raise OpeningError("Only the person who made a draft opening stock deletes it.")
        try:
            approvals.withdraw(user, DOC, opening.pk, "The draft opening stock was deleted.")
        except ApprovalError as error:
            raise OpeningError(str(error)) from None
        opening.delete()


# --- Approval and posting -------------------------------------------------------------------


def _recheck(opening: OpeningStock) -> None:
    for x in opening.lines.select_related("item", "store"):
        if _already_moved(x.item, x.store):
            raise OpeningError(
                f"Line {x.line_no}: {x.item.code} has moved in or out of {x.store.code} since "
                "this was loaded; load the sheet again without it."
            )
        if not x.item.is_active or not x.store.is_active:
            raise OpeningError(f"Line {x.line_no}: {x.item.code} or {x.store.code} is inactive.")


def submit(user: User, opening: OpeningStock, comment: str = "") -> OpeningStock:
    with audit_context("opening_stock_submitted", comment), transaction.atomic():
        opening = OpeningStock.objects.select_for_update().get(pk=opening.pk)
        if not can_edit(user, opening):
            raise OpeningError("Only the person who made a draft opening stock sends it.")
        if not opening.lines.exists():
            raise OpeningError("Load the counted stock first.")
        _recheck(opening)
        try:
            approvals.submit(
                user,
                DOC,
                opening.pk,
                created_by=opening.created_by,
                amount=total(opening),
                comment=comment,
                title=f"Opening stock {opening.number} counted on {opening.count_date}",
                link=f"/opening-stock/{opening.pk}",
            )
        except ApprovalError as error:
            raise OpeningError(str(error)) from None
        opening.status = St.AWAITING_APPROVAL
        opening.updated_at = timezone.now()
        opening.save(update_fields=["status", "updated_at"])
        return opening


def _equity() -> Account:
    account = Account.objects.filter(system_role="opening_balance_equity", is_active=True).first()
    if account is None:
        raise OpeningError("There is no active Opening balance equity account.")
    return account


def _post(user: User, opening: OpeningStock) -> None:
    lines = list(opening.lines.select_related("item__inventory_account", "store__division"))
    debits = defaultdict(Decimal)  # (inventory account, division) -> value
    for x in lines:
        if x.item.inventory_account is None:
            raise OpeningError(
                f"Item {x.item.code} has no inventory account (the Accountant sets it)."
            )
        debits[(x.item.inventory_account, x.store.division)] += x.value
    credits = defaultdict(Decimal)
    for (_, division), value in debits.items():
        credits[division] += value
    equity = _equity()
    ledger = [
        journal.Line(account=account, debit=value, division=division, description="Opening stock")
        for (account, division), value in sorted(
            debits.items(), key=lambda kv: (kv[0][1].code, kv[0][0].number)
        )
    ] + [
        journal.Line(account=equity, credit=value, division=division, description="Opening stock")
        for division, value in sorted(credits.items(), key=lambda kv: kv[0].code)
    ]
    try:
        entry = journal.post(
            user,
            entry_date=opening.count_date,
            narration=f"Opening stock {opening.number} counted on {opening.count_date}",
            lines=ledger,
            source_type=DOC,
            source_id=opening.number,
        )
    except AccountingError as error:
        raise OpeningError(str(error)) from None
    for x in lines:
        StockMovement.objects.create(
            item=x.item,
            store=x.store,
            division=x.store.division,
            lot_no=x.lot_no,
            kind=StockMovement.Kind.OPENING,
            movement_date=opening.count_date,
            quantity=x.quantity,
            value=x.value,
            opening_line=x,
            journal_entry=entry,
            created_by=user,
        )
    opening.status = St.POSTED
    opening.journal_entry = entry
    opening.updated_at = timezone.now()
    opening.save(update_fields=["status", "journal_entry", "updated_at"])


def approve(user: User, opening: OpeningStock, comment: str = "") -> OpeningStock:
    with transaction.atomic():
        opening = OpeningStock.objects.select_for_update().get(pk=opening.pk)
        if opening.status != St.AWAITING_APPROVAL:
            raise OpeningError("The opening stock is not waiting for approval.")
        try:
            state = approvals.approve(user, DOC, opening.pk, comment)
        except ApprovalError as error:
            raise OpeningError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            _recheck(opening)
            with audit_context("opening_stock_posted", comment):
                _post(user, opening)
        return opening


def send_back(user: User, opening: OpeningStock, reason: str) -> OpeningStock:
    with transaction.atomic():
        opening = OpeningStock.objects.select_for_update().get(pk=opening.pk)
        if opening.status != St.AWAITING_APPROVAL:
            raise OpeningError("The opening stock is not waiting for approval.")
        try:
            approvals.send_back(user, DOC, opening.pk, reason)
        except ApprovalError as error:
            raise OpeningError(str(error)) from None
        with audit_context("opening_stock_returned", reason):
            opening.status = St.DRAFT
            opening.updated_at = timezone.now()
            opening.save(update_fields=["status", "updated_at"])
        return opening


def reject(user: User, opening: OpeningStock, reason: str) -> OpeningStock:
    with transaction.atomic():
        opening = OpeningStock.objects.select_for_update().get(pk=opening.pk)
        if opening.status != St.AWAITING_APPROVAL:
            raise OpeningError("The opening stock is not waiting for approval.")
        try:
            approvals.reject(user, DOC, opening.pk, reason)
        except ApprovalError as error:
            raise OpeningError(str(error)) from None
        with audit_context("opening_stock_rejected", reason):
            opening.status = St.REJECTED
            opening.updated_at = timezone.now()
            opening.save(update_fields=["status", "updated_at"])
        return opening
