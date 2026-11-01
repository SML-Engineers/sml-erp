"""Supplier returns and debit notes (backlog P16-12).

- The stores person makes a return from one GRN, lot by lot, of goods still in store:
  - **rejected or damaged goods** from the rejected store: confirmed by the stores person;
    they had no value, so nothing is posted;
  - **goods QC had accepted** (found faulty later) from the main store: with a reason,
    approved by the Director. Their stock value leaves the inventory account:
      - the part not yet invoiced: Dr Goods received not invoiced;
      - the part already invoiced: a **debit note** for each invoice, Dr Accounts payable
        (the supplier) at the invoice price and tax, Cr the recoverable tax;
      - any difference between the stock value and these: Purchase price variance.
    The goods returned can no longer be invoiced, and a debit note reduces what is still
    to pay on its invoice.
- Either way the goods leave the store ("returned" movements) and the PO expects them
  again, so the supplier can deliver replacements against it.
- A confirmed return and its debit notes never change (database guards).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.accounting import journal, taxes
from apps.accounting.models import Account, TaxComponent
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.inventory import receipts as grns
from apps.inventory.models import GoodsReceipt, GoodsReceiptLine, StockMovement, Store
from apps.inventory.stock import unit_cost

from .models import (
    DebitNote,
    PurchaseOrder,
    PurchaseOrderLine,
    SupplierInvoice,
    SupplierInvoiceLine,
    SupplierReturn,
    SupplierReturnLine,
)

DOC = "supplier_return"
St = SupplierReturn.Status
Kind = SupplierReturn.Kind
CENT = Decimal("0.01")
QTY = Decimal("0.001")


class ReturnError(Exception):
    pass


@dataclass
class LineInput:
    grn_line: int
    lot_no: str
    quantity: object


# --- Who may do what ---------------------------------------------------------------------


def can_enter(user: User) -> bool:
    return effective_access(user).has("stores", "enter")


def visible(user: User) -> QuerySet[SupplierReturn]:
    access = effective_access(user)
    if not (access.has("stores", "view") or access.has("vouchers", "view")):
        return SupplierReturn.objects.none()
    return SupplierReturn.objects.filter(division__in=division_scope(user)).select_related(
        "supplier", "division", "receipt", "created_by"
    )


def can_edit(user: User, ret: SupplierReturn) -> bool:
    return ret.status == St.DRAFT and ret.created_by_id == user.pk and can_enter(user)


def can_approve(user: User, ret: SupplierReturn) -> bool:
    if ret.status != St.AWAITING_APPROVAL:
        return False
    state = approvals.state_of(DOC, ret.pk)
    return state is not None and approvals.why_not(user, state) is None


# --- What can be returned ----------------------------------------------------------------


def _store_kind(kind: str) -> str:
    return Store.Kind.REJECTED if kind == Kind.REJECTED else Store.Kind.MAIN


def lots(grn: GoodsReceipt, kind: str) -> list[dict]:
    """The GRN's lots still in the rejected (or main) store, with quantity and value."""
    rows = (
        StockMovement.objects.filter(receipt_line__receipt=grn, store__kind=_store_kind(kind))
        .values("receipt_line", "lot_no", "store")
        .annotate(quantity=Sum("quantity"), value=Sum("value"))
        .order_by("receipt_line", "lot_no")
    )
    return [r for r in rows if r["quantity"] > 0]


def returned_accepted(line: GoodsReceiptLine) -> tuple[Decimal, Decimal]:
    """Confirmed returns of accepted goods on a GRN line: (quantity, of it invoiced)."""
    rows = SupplierReturnLine.objects.filter(
        grn_line=line,
        supplier_return__kind=Kind.ACCEPTED,
        supplier_return__status=St.CONFIRMED,
    ).aggregate(quantity=Sum("quantity"), invoiced=Sum("invoiced_quantity"))
    return rows["quantity"] or Decimal("0"), rows["invoiced"] or Decimal("0")


def debited(invoice: SupplierInvoice) -> Decimal:
    return invoice.debit_notes.aggregate(total=Sum("total_lkr"))["total"] or Decimal("0")


# --- Making and changing ----------------------------------------------------------------


def _number(value) -> Decimal:
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise ReturnError("The quantity is not a number.") from None
    if not result.is_finite() or result <= 0:
        raise ReturnError("The quantity must be more than 0.")
    if result != result.quantize(QTY):
        raise ReturnError("The quantity can have at most 3 decimal places.")
    return result


def _fill(ret: SupplierReturn, lines: list[LineInput]) -> None:
    if not lines:
        raise ReturnError("Choose the lots to return.")
    available = {
        (r["receipt_line"], r["lot_no"]): r["quantity"] for r in lots(ret.receipt, ret.kind)
    }
    rows = []
    seen = set()
    for n, given in enumerate(lines, start=1):
        key = (given.grn_line, (given.lot_no or "").strip())
        if key not in available:
            raise ReturnError(f"Line {n}: lot {key[1]} of this GRN is not in the store.")
        if key in seen:
            raise ReturnError(f"Line {n}: each lot can appear once.")
        seen.add(key)
        try:
            quantity = _number(given.quantity)
        except ReturnError as error:
            raise ReturnError(f"Line {n}: {error}") from None
        if quantity > available[key]:
            raise ReturnError(
                f"Line {n}: only {available[key].normalize():f} of lot {key[1]} is in the store."
            )
        rows.append(
            SupplierReturnLine(
                supplier_return=ret,
                line_no=n,
                grn_line_id=key[0],
                lot_no=key[1],
                quantity=quantity,
            )
        )
    ret.lines.all().delete()
    for row in rows:
        row.save()


def _header(ret: SupplierReturn, values: dict) -> None:
    if "reason" in values:
        ret.reason = (values["reason"] or "").strip()[:2000]
    if not ret.reason:
        raise ReturnError("Give the reason for returning the goods.")
    if "vehicle_no" in values:
        ret.vehicle_no = (values["vehicle_no"] or "").strip()[:30]
    if "return_date" in values:
        when = values["return_date"]
        if not isinstance(when, date) or when > timezone.localdate():
            raise ReturnError("The return date cannot be in the future.")
        if when < ret.receipt.receipt_date:
            raise ReturnError("Goods cannot be returned before they were received.")
        ret.return_date = when


def create(user: User, grn: GoodsReceipt, *, kind: str, lines: list[LineInput], **values):
    if not can_enter(user):
        raise ReturnError("Only the stores person returns goods to the supplier.")
    if kind not in Kind.values:
        raise ReturnError("Choose what is returned: rejected goods or goods QC had accepted.")
    if (
        grn.status != GoodsReceipt.Status.CONFIRMED
        or not division_scope(user).filter(pk=grn.division_id).exists()
    ):
        raise ReturnError("Goods are returned from a confirmed GRN of your division.")
    with audit_context("supplier_return_created"), transaction.atomic():
        today = timezone.localdate()
        ret = SupplierReturn(
            receipt=grn,
            supplier=grn.supplier,
            division=grn.division,
            kind=kind,
            return_date=today,
            created_by=user,
        )
        _header(ret, values)
        try:
            ret.number = allocate("supplier_return", division=grn.division, on_date=today)
        except NumberSeriesError as error:
            raise ReturnError(str(error)) from None
        ret.save()
        _fill(ret, lines)
        return ret


def save(user: User, ret: SupplierReturn, *, lines: list[LineInput], **values):
    with audit_context("supplier_return_changed"), transaction.atomic():
        ret = SupplierReturn.objects.select_for_update().get(pk=ret.pk)
        if not can_edit(user, ret):
            raise ReturnError("Only the person who made a draft return changes it.")
        _header(ret, values)
        ret.save()
        _fill(ret, lines)
        return ret


def delete(user: User, ret: SupplierReturn) -> None:
    with audit_context("supplier_return_deleted"), transaction.atomic():
        ret = SupplierReturn.objects.select_for_update().get(pk=ret.pk)
        if not can_edit(user, ret):
            raise ReturnError("Only the person who made a draft return deletes it.")
        ret.delete()


# --- Confirming -------------------------------------------------------------------------------


def confirm(user: User, ret: SupplierReturn, comment: str = "") -> SupplierReturn:
    """Rejected goods go back at once; goods QC had accepted first go to the Director."""
    with audit_context("supplier_return_confirmed", comment), transaction.atomic():
        ret = SupplierReturn.objects.select_for_update().get(pk=ret.pk)
        if not can_edit(user, ret):
            raise ReturnError("Only the person who made a draft return confirms it.")
        _fill(ret, [LineInput(r.grn_line_id, r.lot_no, r.quantity) for r in ret.lines.all()])
        if ret.kind == Kind.REJECTED:
            _apply(user, ret)
            return ret
        total = sum((_lot_value(r) for r in ret.lines.all()), Decimal("0"))
        try:
            approvals.submit(
                user,
                DOC,
                ret.pk,
                created_by=ret.created_by,
                amount=total,
                division=ret.division,
                comment="; ".join(filter(None, [comment, ret.reason])),
                title=f"Return accepted goods of {ret.receipt.number} to {ret.supplier.name}",
                link=f"/supplier-returns/{ret.pk}",
            )
        except ApprovalError as error:
            raise ReturnError(str(error)) from None
        ret.status = St.AWAITING_APPROVAL
        ret.save(update_fields=["status"])
        return ret


def approve(user: User, ret: SupplierReturn, comment: str = "") -> SupplierReturn:
    with transaction.atomic():
        ret = SupplierReturn.objects.select_for_update().get(pk=ret.pk)
        if ret.status != St.AWAITING_APPROVAL:
            raise ReturnError("This return is not waiting for the Director.")
        try:
            state = approvals.approve(user, DOC, ret.pk, comment)
        except ApprovalError as error:
            raise ReturnError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("supplier_return_approved", comment):
                _apply(user, ret)
        return ret


def send_back(user: User, ret: SupplierReturn, reason: str) -> SupplierReturn:
    with transaction.atomic():
        ret = SupplierReturn.objects.select_for_update().get(pk=ret.pk)
        if ret.status != St.AWAITING_APPROVAL:
            raise ReturnError("This return is not waiting for the Director.")
        try:
            approvals.send_back(user, DOC, ret.pk, reason)
        except ApprovalError as error:
            raise ReturnError(str(error)) from None
        with audit_context("supplier_return_returned", reason):
            ret.status = St.DRAFT
            ret.save(update_fields=["status"])
        return ret


def _lot_value(line: SupplierReturnLine) -> Decimal:
    """The stock value of the quantity returned, at the lot's own value per unit."""
    if line.supplier_return.kind == Kind.REJECTED:
        return Decimal("0")
    found = StockMovement.objects.filter(
        receipt_line_id=line.grn_line_id, lot_no=line.lot_no, store__kind=Store.Kind.MAIN
    ).aggregate(quantity=Sum("quantity"), value=Sum("value"))
    quantity, value = found["quantity"] or Decimal("0"), found["value"] or Decimal("0")
    if quantity <= 0:
        return Decimal("0")
    if line.quantity >= quantity:
        return value
    return (value * line.quantity / quantity).quantize(CENT, ROUND_HALF_UP)


def _account(role: str, name: str) -> Account:
    account = Account.objects.filter(system_role=role, is_active=True).first()
    if account is None:
        raise ReturnError(f"There is no active {name} account (Chart of accounts).")
    return account


def _apply(user: User, ret: SupplierReturn) -> None:
    """The goods leave the store; the PO expects them again; accepted goods are posted."""
    from . import invoices  # invoices reads this module

    lines = list(ret.lines.select_related("grn_line__item__inventory_account", "grn_line__po_line"))
    stores = {(m["receipt_line"], m["lot_no"]): m["store"] for m in lots(ret.receipt, ret.kind)}
    postings = defaultdict(Decimal)  # account pk -> amount; positive = debit
    accounts = {}
    debit_rows = []

    def post(account, amount):
        accounts[account.pk] = account
        postings[account.pk] += amount

    values = {}
    taken = defaultdict(Decimal)  # open quantity already used by earlier lines of this return
    for line in lines:
        grn_line = line.grn_line
        if (grn_line.pk, line.lot_no) not in stores:
            raise ReturnError(f"Line {line.line_no}: lot {line.lot_no} is no longer in the store.")
        values[line.pk] = _lot_value(line)
        if ret.kind != Kind.ACCEPTED:
            continue
        open_qty = invoices.accepted(grn_line) - invoices.invoiced(grn_line) - taken[grn_line.pk]
        line.uninvoiced_quantity = min(line.quantity, max(open_qty, Decimal("0")))
        taken[grn_line.pk] += line.uninvoiced_quantity
        line.invoiced_quantity = line.quantity - line.uninvoiced_quantity
        line.value = values[line.pk]
        line.save(update_fields=["uninvoiced_quantity", "invoiced_quantity", "value"])
        item = grn_line.item
        if item.inventory_account is None:
            raise ReturnError(f"Item {item.code} has no inventory account.")
        post(item.inventory_account, -line.value)
        if line.uninvoiced_quantity:
            post(
                _account("grni", "Goods received not invoiced"),
                (line.uninvoiced_quantity * unit_cost(grn_line)).quantize(CENT, ROUND_HALF_UP),
            )
        if line.invoiced_quantity:
            debit_rows += _debit(line, post, debit_rows)

    entry = None
    if ret.kind == Kind.ACCEPTED and any(postings.values()):
        difference = -sum(postings.values(), Decimal("0"))
        if difference:
            post(_account("price_variance", "Purchase price variance"), difference)
        with_supplier = {
            _account("accounts_payable", "Accounts payable").pk,
            _account("grni", "Goods received not invoiced").pk,
        }
        try:
            entry = journal.post(
                user,
                entry_date=timezone.localdate(),
                narration=f"Goods returned to {ret.supplier.name}: {ret.number} "
                f"(GRN {ret.receipt.number})",
                lines=[
                    journal.Line(
                        account=accounts[pk],
                        debit=amount if amount > 0 else Decimal("0"),
                        credit=-amount if amount < 0 else Decimal("0"),
                        division=ret.division,
                        supplier=ret.supplier if pk in with_supplier else None,
                        description=ret.number,
                    )
                    for pk, amount in postings.items()
                    if amount
                ],
                source_type="supplier_return",
                source_id=ret.number,
            )
        except AccountingError as error:
            raise ReturnError(str(error)) from None
        for row in debit_rows:
            try:
                row.number = allocate("debit_note", division=ret.division)
            except NumberSeriesError as error:
                raise ReturnError(str(error)) from None
            row.journal_entry = entry
            row.save()

    for line in lines:
        grn_line = line.grn_line
        StockMovement.objects.create(
            item=grn_line.item,
            store_id=stores[(grn_line.pk, line.lot_no)],
            division=ret.division,
            lot_no=line.lot_no,
            kind=StockMovement.Kind.RETURNED,
            movement_date=ret.return_date,
            quantity=-line.quantity,
            value=-values[line.pk],
            receipt_line=grn_line,
            journal_entry=entry if values[line.pk] else None,
            created_by=user,
        )
        po_line = PurchaseOrderLine.objects.select_for_update().get(pk=grn_line.po_line_id)
        po_line.received_quantity = max(po_line.received_quantity - line.quantity, Decimal("0"))
        po_line.save(update_fields=["received_quantity"])
    grns._po_status(PurchaseOrder.objects.select_for_update().get(pk=ret.receipt.purchase_order_id))
    ret.journal_entry = entry
    ret.status = St.CONFIRMED
    ret.confirmed_at = timezone.now()
    ret.save(update_fields=["journal_entry", "status", "confirmed_at"])


def _debit(line: SupplierReturnLine, post, pending: list[DebitNote]) -> list[DebitNote]:
    """Debit notes for the invoiced part of a returned line, newest invoice first."""
    left = line.invoiced_quantity
    rows = []
    invoice_lines = SupplierInvoiceLine.objects.filter(
        grn_line=line.grn_line, invoice__status=SupplierInvoice.Status.POSTED
    ).select_related("invoice", "tax_code", "grn_line__receipt__purchase_order")
    for inv_line in invoice_lines.order_by("-invoice__invoice_date", "-invoice__number"):
        if left <= 0:
            break
        done = DebitNote.objects.filter(
            invoice=inv_line.invoice, return_line__grn_line=line.grn_line
        ).aggregate(total=Sum("quantity"))["total"] or Decimal("0")
        done += sum(
            (
                p.quantity
                for p in pending
                if p.invoice_id == inv_line.invoice_id
                and p.return_line.grn_line_id == line.grn_line_id
            ),
            Decimal("0"),
        )
        quantity = min(left, inv_line.quantity - done)
        if quantity <= 0:
            continue
        left -= quantity
        rate = inv_line.grn_line.receipt.purchase_order.exchange_rate
        net = (quantity * inv_line.unit_price).quantize(CENT, ROUND_HALF_UP)
        tax = Decimal("0")
        recoverable = Decimal("0")
        if inv_line.tax_code is not None:
            result = taxes.calculate(inv_line.tax_code, net, inv_line.invoice.invoice_date)
            tax = result.tax
            for part in result.lines:
                component = part.component
                if (
                    part.amount
                    and component.purchase_account_id
                    and component.kind == TaxComponent.Kind.CHARGED
                ):
                    post(component.purchase_account, -(part.amount * rate).quantize(CENT))
                    recoverable += part.amount
        total_lkr = ((net + tax) * rate).quantize(CENT, ROUND_HALF_UP)
        post(_account("accounts_payable", "Accounts payable"), total_lkr)
        rows.append(
            DebitNote(
                supplier_return=line.supplier_return,
                invoice=inv_line.invoice,
                return_line=line,
                quantity=quantity,
                amount=net,
                tax_amount=tax,
                total_lkr=total_lkr,
            )
        )
    if left > 0:
        raise ReturnError(f"Line {line.line_no}: the invoices for these goods were not found.")
    return rows
