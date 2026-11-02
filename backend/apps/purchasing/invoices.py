"""Supplier invoices and the three-way match (backlog P16-10, spec 5A.4).

- The Accounts Clerk (Vouchers: Enter) enters the supplier's invoice with its scan, and bills
  GRN lines of that supplier and division: goods QC accepted and not yet invoiced.
- Matching compares every line with its GRN and PO, with no tolerance (owner, 31 Oct 2026):
  - the quantity can never be more than accepted and not yet invoiced: refused outright,
    because goods not received or not accepted can never be invoiced for payment;
  - the price must be the PO price and the tax code the PO's;
  - the total printed on the invoice must be the total worked out.
  With no difference the invoice is posted at once. Otherwise it is **Held: discrepancy**
  with the differences listed: the Accountant asks the Director to approve the exception
  with a reason, the Clerk corrects a typing mistake, or the invoice is cancelled for the
  supplier's credit note or new invoice.
- Posting (rule 2, in the same transaction): Dr Goods received not invoiced at the PO price
  (or the item's expense account for a non-stock item), Dr the recoverable taxes (e.g. VAT
  input), Dr/Cr Purchase price variance for any approved difference, Cr Accounts payable
  for the supplier. In LKR at the PO's exchange rate.
- Supplier + invoice number is unique across supplier invoices and vouchers (decision 5;
  service and database). A posted or cancelled invoice never changes (database guard).
"""

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.accounting import journal, taxes
from apps.accounting.models import Account, TaxCode, TaxComponent
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.inventory.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    IncomingInspection,
    StockMovement,
    Store,
)
from apps.inventory.stock import receipt_rate
from apps.masters import currencies
from apps.masters.models import Supplier
from apps.masters.services import MastersError
from apps.vouchers.services import FILE_TYPES, INVOICE_FREED, MAX_FILE_BYTES, invoice_key

from .models import SupplierInvoice, SupplierInvoiceAttachment, SupplierInvoiceLine

DOC = "invoice_exception"
St = SupplierInvoice.Status
CENT = Decimal("0.01")
QTY = Decimal("0.001")
COUNTING = (St.HELD, St.EXCEPTION_REQUESTED, St.POSTED)
MAX_LINES = 200
MAX_FILES = 10


class InvoiceError(Exception):
    pass


@dataclass
class LineInput:
    grn_line: int
    quantity: object
    unit_price: object
    tax_code: TaxCode | None = None


# --- Who may do what ---------------------------------------------------------------------


def can_enter(user: User) -> bool:
    return effective_access(user).has("vouchers", "enter")


def can_request_exception(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def visible(user: User) -> QuerySet[SupplierInvoice]:
    if not effective_access(user).has("vouchers", "view"):
        return SupplierInvoice.objects.none()
    return SupplierInvoice.objects.filter(division__in=division_scope(user)).select_related(
        "supplier", "division", "currency", "created_by"
    )


def can_edit(user: User, invoice: SupplierInvoice) -> bool:
    return invoice.status == St.DRAFT and invoice.created_by_id == user.pk and can_enter(user)


def can_approve(user: User, invoice: SupplierInvoice) -> bool:
    if invoice.status != St.EXCEPTION_REQUESTED:
        return False
    state = approvals.state_of(DOC, invoice.pk)
    return state is not None and approvals.why_not(user, state) is None


# --- Quantities ----------------------------------------------------------------------------


def accepted(line: GoodsReceiptLine) -> Decimal:
    """What QC accepted on the GRN line; nothing until QC has decided."""
    from .returns import returned_accepted  # returns reads this module

    inspection = IncomingInspection.objects.filter(
        line=line, status=IncomingInspection.Status.DECIDED
    ).first()
    if inspection is None:
        return Decimal("0")
    # Accepted goods sent back (P16-12) can no longer be invoiced; the part already invoiced
    # is cleared by a debit note instead.
    returned, debited = returned_accepted(line)
    return inspection.accepted_quantity - returned + debited


def invoiced(line: GoodsReceiptLine, *, excluding: SupplierInvoice | None = None) -> Decimal:
    rows = SupplierInvoiceLine.objects.filter(grn_line=line, invoice__status__in=COUNTING)
    if excluding is not None:
        rows = rows.exclude(invoice=excluding)
    return rows.aggregate(total=Sum("quantity"))["total"] or Decimal("0")


def open_lines(user: User, supplier: Supplier, division) -> list[dict]:
    """GRN lines of the supplier with accepted goods not yet invoiced."""
    lines = (
        GoodsReceiptLine.objects.filter(
            receipt__supplier=supplier,
            receipt__division=division,
            receipt__division__in=division_scope(user),
            receipt__status=GoodsReceipt.Status.CONFIRMED,
            inspection__status=IncomingInspection.Status.DECIDED,
            inspection__accepted_quantity__gt=0,
        )
        .select_related("receipt__purchase_order__currency", "item", "po_line__tax_code")
        .order_by("receipt__receipt_date", "receipt__number", "line_no")
    )
    result = []
    for line in lines:
        left = accepted(line) - invoiced(line)
        if left > 0:
            result.append({"line": line, "open": left})
    return result


# --- Checking -----------------------------------------------------------------------------


def _number(value, what: str, places: Decimal) -> Decimal:
    try:
        result = Decimal(str(value if value not in (None, "") else "").replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise InvoiceError(f"The {what} is not a number.") from None
    if not result.is_finite() or result <= 0:
        raise InvoiceError(f"The {what} must be more than 0.")
    if result != result.quantize(places):
        raise InvoiceError(f"The {what} has too many decimal places.")
    return result


def _duplicate(supplier: Supplier, invoice_no: str, pk=None) -> str | None:
    from apps.vouchers.models import VoucherLine

    key = invoice_key(invoice_no)
    others = SupplierInvoice.objects.filter(supplier=supplier).exclude(status=St.CANCELLED)
    if pk:
        others = others.exclude(pk=pk)
    for other in others:
        if invoice_key(other.invoice_no) == key:
            return f"supplier invoice {other.number}"
    lines = (
        VoucherLine.objects.filter(voucher__payee=supplier, supplier_invoice__isnull=True)
        .exclude(voucher__status__in=INVOICE_FREED)
        .exclude(invoice_no="")
        .select_related("voucher")
    )
    for line in lines:
        if invoice_key(line.invoice_no) == key:
            return f"voucher {line.voucher.number}"
    return None


def _header(invoice: SupplierInvoice, values: dict) -> None:
    if "invoice_no" in values:
        invoice.invoice_no = " ".join((values["invoice_no"] or "").split())[:50]
    if not invoice.invoice_no:
        raise InvoiceError("Enter the supplier's invoice number.")
    clash = _duplicate(invoice.supplier, invoice.invoice_no, invoice.pk)
    if clash:
        raise InvoiceError(
            f"Invoice {invoice.invoice_no} of this supplier is already on {clash}. The same "
            "supplier invoice cannot be entered twice."
        )
    if "invoice_date" in values:
        when = values["invoice_date"]
        if not isinstance(when, date):
            raise InvoiceError("The invoice date is not a date.")
        if when > timezone.localdate():
            raise InvoiceError("The invoice date cannot be in the future.")
        invoice.invoice_date = when
        invoice.due_date = when + timedelta(days=invoice.supplier.payment_terms_days)
    if "stated_total" in values:
        raw = values["stated_total"]
        invoice.stated_total = None if raw in (None, "") else _number(raw, "invoice total", CENT)
    if "notes" in values:
        invoice.notes = (values["notes"] or "").strip()[:5000]


def _fill(invoice: SupplierInvoice, lines: list[LineInput]) -> None:
    if not lines:
        raise InvoiceError("Add the GRN lines this invoice bills.")
    if len(lines) > MAX_LINES:
        raise InvoiceError(f"An invoice can have at most {MAX_LINES} lines.")
    grn_lines = GoodsReceiptLine.objects.select_related(
        "receipt__purchase_order__currency", "po_line__tax_code", "item"
    ).in_bulk([line.grn_line for line in lines])
    rows = []
    seen = set()
    currency = None
    for n, given in enumerate(lines, start=1):
        where = f"Line {n}: "
        grn_line = grn_lines.get(given.grn_line)
        grn = grn_line.receipt if grn_line else None
        if (
            grn_line is None
            or grn.supplier_id != invoice.supplier_id
            or grn.division_id != invoice.division_id
            or grn.status != GoodsReceipt.Status.CONFIRMED
        ):
            raise InvoiceError(where + "choose a confirmed GRN line of this supplier and division.")
        if grn_line.pk in seen:
            raise InvoiceError(where + "each GRN line can be billed once on an invoice.")
        seen.add(grn_line.pk)
        order = grn.purchase_order
        if currency and order.currency_id != currency.pk:
            raise InvoiceError(where + "all the lines of an invoice are in one currency.")
        currency = order.currency
        try:
            quantity = _number(given.quantity, "quantity", QTY)
            price = _number(given.unit_price, "price", CENT)
        except InvoiceError as error:
            raise InvoiceError(where + str(error)) from None
        amount = (quantity * price).quantize(CENT, ROUND_HALF_UP)
        tax = Decimal("0")
        if given.tax_code is not None:
            try:
                tax = taxes.calculate(given.tax_code, amount, invoice.invoice_date).tax
            except AccountingError as error:
                raise InvoiceError(where + str(error)) from None
        rows.append(
            SupplierInvoiceLine(
                invoice=invoice,
                line_no=n,
                grn_line=grn_line,
                item=grn_line.item,
                quantity=quantity,
                unit_price=price,
                tax_code=given.tax_code,
                amount=amount,
                tax_amount=tax,
                total=amount + tax,
                po_unit_price=grn_line.po_line.unit_price,
                po_tax_code=grn_line.po_line.tax_code,
            )
        )
    invoice.currency = currency
    invoice.subtotal = sum((r.amount for r in rows), Decimal("0"))
    invoice.tax_total = sum((r.tax_amount for r in rows), Decimal("0"))
    invoice.total_amount = invoice.subtotal + invoice.tax_total
    invoice.save()
    invoice.lines.all().delete()
    for row in rows:
        row.save()


# --- Making and changing ----------------------------------------------------------------


def create(user: User, *, supplier: Supplier, division, lines: list[LineInput], **values):
    if not can_enter(user):
        raise InvoiceError("Only Accounts enter supplier invoices.")
    if supplier is None:
        raise InvoiceError("Choose the supplier.")
    if division is None or not division_scope(user).filter(pk=division.pk).exists():
        raise InvoiceError("Choose one of your divisions.")
    with audit_context("supplier_invoice_created"), transaction.atomic():
        today = timezone.localdate()
        invoice = SupplierInvoice(
            supplier=supplier,
            division=division,
            invoice_date=today,
            due_date=today + timedelta(days=supplier.payment_terms_days),
            created_by=user,
        )
        _header(invoice, {"invoice_date": today, **values})
        if not lines:
            raise InvoiceError("Add the GRN lines this invoice bills.")
        first = (
            GoodsReceiptLine.objects.filter(pk=lines[0].grn_line)
            .select_related("receipt__purchase_order")
            .first()
        )
        invoice.currency_id = first.receipt.purchase_order.currency_id if first else None
        if invoice.currency_id is None:
            raise InvoiceError("Line 1: choose a confirmed GRN line of this supplier and division.")
        try:
            invoice.number = allocate("supplier_invoice", division=division, on_date=today)
        except NumberSeriesError as error:
            raise InvoiceError(str(error)) from None
        invoice.save()
        _fill(invoice, lines)
        return invoice


def save(user: User, invoice: SupplierInvoice, *, lines: list[LineInput], **values):
    with audit_context("supplier_invoice_changed"), transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if not can_edit(user, invoice):
            raise InvoiceError("Only the person who entered a draft invoice changes it.")
        _header(invoice, values)
        _fill(invoice, lines)
        return invoice


def delete(user: User, invoice: SupplierInvoice) -> None:
    with audit_context("supplier_invoice_deleted"), transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if not can_edit(user, invoice):
            raise InvoiceError("Only the person who entered a draft invoice deletes it.")
        for attachment in invoice.attachments.all():
            attachment.file.delete(save=False)
        invoice.attachments.all().delete()
        invoice.delete()


# --- The three-way match --------------------------------------------------------------------


def differences(invoice: SupplierInvoice) -> list[str]:
    """What does not match. Raises InvoiceError for what can never be invoiced."""
    found = []
    for line in invoice.lines.select_related(
        "grn_line__receipt", "item", "tax_code", "po_tax_code"
    ):
        grn_line = line.grn_line
        where = f"Line {line.line_no} ({line.item.code}, {grn_line.receipt.number})"
        left = accepted(grn_line) - invoiced(grn_line, excluding=invoice)
        if line.quantity > left:
            raise InvoiceError(
                f"{where}: {line.quantity.normalize():f} invoiced, but only "
                f"{max(left, Decimal('0')).normalize():f} accepted by QC and not yet invoiced. "
                "Goods not received or not accepted can never be invoiced for payment."
            )
        if line.unit_price != line.po_unit_price:
            found.append(
                f"{where}: price {line.unit_price:,.2f}, PO price {line.po_unit_price:,.2f}."
            )
        if line.tax_code_id != line.po_tax_code_id:
            code = line.tax_code.code if line.tax_code else "no tax"
            po_code = line.po_tax_code.code if line.po_tax_code else "no tax"
            found.append(f"{where}: tax {code}, PO tax {po_code}.")
    if invoice.stated_total is not None and invoice.stated_total != invoice.total_amount:
        found.append(
            f"Total printed on the invoice {invoice.stated_total:,.2f}, worked out "
            f"{invoice.total_amount:,.2f}."
        )
    return found


def match(user: User, invoice: SupplierInvoice) -> SupplierInvoice:
    """Run the three-way match: post a matching invoice, hold one that does not."""
    with audit_context("supplier_invoice_matched"), transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if not can_edit(user, invoice):
            raise InvoiceError("Only the person who entered a draft invoice matches it.")
        if invoice.stated_total is None:
            raise InvoiceError("Enter the total printed on the invoice.")
        if not invoice.attachments.exists():
            raise InvoiceError("Attach the scanned invoice first.")
        # Lock the GRN lines so two invoices cannot bill the same goods at the same moment.
        list(
            GoodsReceiptLine.objects.select_for_update()
            .filter(invoice_lines__invoice=invoice)
            .values_list("pk", flat=True)
        )
        found = differences(invoice)
        invoice.discrepancies = found
        if found:
            invoice.status = St.HELD
            invoice.save(update_fields=["discrepancies", "status"])
            return invoice
        _post(user, invoice)
        return invoice


def back_to_draft(user: User, invoice: SupplierInvoice) -> SupplierInvoice:
    """A held invoice goes back to the Clerk to correct a typing mistake."""
    with audit_context("supplier_invoice_reopened"), transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != St.HELD or not can_enter(user):
            raise InvoiceError("Only a held invoice goes back to draft.")
        invoice.status = St.DRAFT
        invoice.save(update_fields=["status"])
        return invoice


def request_exception(user: User, invoice: SupplierInvoice, reason: str) -> SupplierInvoice:
    reason = (reason or "").strip()
    with audit_context("supplier_invoice_exception_requested", reason), transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != St.HELD:
            raise InvoiceError("Only a held invoice can go to the Director as an exception.")
        if not can_request_exception(user):
            raise InvoiceError("The Accountant investigates and asks for the exception.")
        if not reason:
            raise InvoiceError("Give the reason for accepting the difference.")
        found = differences(invoice)  # quantities may have changed since it was held
        if not found:
            raise InvoiceError("The invoice now matches: send it back to draft and match it.")
        try:
            approvals.submit(
                user,
                DOC,
                invoice.pk,
                created_by=user,
                amount=invoice.total_amount,
                division=invoice.division,
                comment=reason,
                title=(
                    f"Supplier invoice {invoice.invoice_no} of {invoice.supplier.name} does not "
                    "match"
                )[:200],
                link=f"/supplier-invoices/{invoice.pk}",
            )
        except ApprovalError as error:
            raise InvoiceError(str(error)) from None
        invoice.discrepancies = found
        invoice.exception_reason = reason[:5000]
        invoice.status = St.EXCEPTION_REQUESTED
        invoice.save(update_fields=["discrepancies", "exception_reason", "status"])
        return invoice


def approve_exception(user: User, invoice: SupplierInvoice, comment: str = ""):
    with transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != St.EXCEPTION_REQUESTED:
            raise InvoiceError("No exception of this invoice is waiting for the Director.")
        list(
            GoodsReceiptLine.objects.select_for_update()
            .filter(invoice_lines__invoice=invoice)
            .values_list("pk", flat=True)
        )
        differences(invoice)  # quantities are never an exception
        try:
            state = approvals.approve(user, DOC, invoice.pk, comment)
        except ApprovalError as error:
            raise InvoiceError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("supplier_invoice_exception_approved", comment):
                _post(user, invoice)
        return invoice


def send_back(user: User, invoice: SupplierInvoice, reason: str):
    with transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != St.EXCEPTION_REQUESTED:
            raise InvoiceError("No exception of this invoice is waiting for the Director.")
        try:
            approvals.send_back(user, DOC, invoice.pk, reason)
        except ApprovalError as error:
            raise InvoiceError(str(error)) from None
        with audit_context("supplier_invoice_exception_returned", reason):
            invoice.status = St.HELD
            invoice.save(update_fields=["status"])
        return invoice


def cancel(user: User, invoice: SupplierInvoice, reason: str) -> SupplierInvoice:
    """A held invoice is cancelled when the supplier sends a credit note or a new invoice; its
    number is then free again."""
    reason = (reason or "").strip()
    with audit_context("supplier_invoice_cancelled", reason), transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if invoice.status != St.HELD or not can_enter(user):
            raise InvoiceError("Only a held invoice is cancelled; a draft is deleted.")
        if not reason:
            raise InvoiceError("Give a reason for cancelling the invoice.")
        invoice.status = St.CANCELLED
        invoice.cancel_reason = reason[:5000]
        invoice.save(update_fields=["status", "cancel_reason"])
        return invoice


# --- Posting ---------------------------------------------------------------------------------


def _system(role: str, name: str) -> Account:
    account = Account.objects.filter(system_role=role, is_active=True).first()
    if account is None:
        raise InvoiceError(f"There is no active {name} account (Chart of accounts).")
    return account


def _lkr(amount: Decimal, rate: Decimal) -> Decimal:
    return (amount * rate).quantize(CENT, ROUND_HALF_UP)


def _in_stock(grn_line: GoodsReceiptLine) -> list[tuple[str, int, Decimal]]:
    """The lots of a GRN line still in a main store: (lot, store, quantity)."""
    rows = (
        StockMovement.objects.filter(receipt_line=grn_line, store__kind=Store.Kind.MAIN)
        .values("lot_no", "store")
        .annotate(quantity=Sum("quantity"))
        .order_by("lot_no", "store")
    )
    return [(r["lot_no"], r["store"], r["quantity"]) for r in rows if r["quantity"] > 0]


def _split(amount: Decimal, lots: list[tuple[str, int, Decimal]]) -> list[tuple[str, int, Decimal]]:
    """Share an amount over lots by quantity, to the cent; the last lot takes the rounding."""
    total = sum((q for _, _, q in lots), Decimal("0"))
    shares, given = [], Decimal("0")
    for index, (lot, store, quantity) in enumerate(lots):
        share = (
            amount - given
            if index == len(lots) - 1
            else (amount * quantity / total).quantize(CENT, ROUND_HALF_UP)
        )
        given += share
        if share:
            shares.append((lot, store, share))
    return shares


def _post(user: User, invoice: SupplierInvoice) -> None:
    """Post the invoice: Dr Goods received not invoiced at the PO price (expense, for a
    non-stock item), recoverable tax, and the price difference; Cr Accounts payable.

    The price difference (with any tax that cannot be recovered) is part of what the goods
    cost (IAS 2): for goods of the GRN line still in a main store it adjusts their value, lot
    by lot; only the part of the goods no longer in stock goes to Purchase price variance. For a
    non-stock item it goes to the item's expense account.

    In a foreign currency (IAS 21) the goods were put into stock, and Goods received not
    invoiced credited, at the rate of the receipt date; the invoice is posted at the rate of
    its own date. Goods received not invoiced is cleared at the receipt's rate and the payable
    taken at the invoice's: the difference between the two is an exchange gain or loss."""
    division = invoice.division
    debits: dict[tuple, Decimal] = {}
    adjustments = []  # (grn line, [(lot, store, value)]) for goods still in stock
    try:
        lookup = currencies.rate_on(invoice.currency, invoice.invoice_date)
    except MastersError as error:
        raise InvoiceError(str(error)) from None
    rate = lookup.rate
    exchange = Decimal("0")

    def add(account, amount, line_division=None, description=""):
        key = (account.pk, line_division.pk if line_division else None, description)
        account_amount = debits.get(key, (account, Decimal("0"), line_division, description))
        debits[key] = (account, account_amount[1] + amount, line_division, description)

    variance = None
    for line in invoice.lines.select_related(
        "item__expense_account", "grn_line__receipt__purchase_order", "tax_code"
    ):
        at_po = _lkr(line.quantity * line.po_unit_price, rate)
        if line.item.is_stock:
            at_receipt = _lkr(
                line.quantity * line.po_unit_price, receipt_rate(line.grn_line.receipt)
            )
            add(
                _system("grni", "Goods received not invoiced"), at_receipt, division, invoice.number
            )
            exchange += at_po - at_receipt
        else:
            if line.item.expense_account is None:
                raise InvoiceError(
                    f"Item {line.item.code} has no expense account (the Accountant sets it)."
                )
            add(line.item.expense_account, at_po, division, line.item.code)
        difference = _lkr(line.amount, rate) - at_po
        recoverable = Decimal("0")
        if line.tax_code is not None and line.tax_amount:
            result = taxes.calculate(line.tax_code, line.amount, invoice.invoice_date)
            for part in result.lines:
                component = part.component
                if (
                    part.amount
                    and component.purchase_account_id
                    and component.kind == TaxComponent.Kind.CHARGED
                ):
                    add(component.purchase_account, _lkr(part.amount, rate), None, "Tax")
                    recoverable += part.amount
        difference += _lkr(line.tax_amount - recoverable, rate)
        if not difference:
            continue
        if not line.item.is_stock:
            add(line.item.expense_account, difference, division, line.item.code)
            continue
        lots = _in_stock(line.grn_line)
        on_hand = sum((q for _, _, q in lots), Decimal("0"))
        share = min(line.quantity, on_hand)
        to_stock = (difference * share / line.quantity).quantize(CENT, ROUND_HALF_UP)
        if to_stock:
            if line.item.inventory_account is None:
                raise InvoiceError(
                    f"Item {line.item.code} has no inventory account (the Accountant sets it)."
                )
            add(line.item.inventory_account, to_stock, division, line.item.code)
            adjustments.append((line.grn_line, _split(to_stock, lots)))
        if difference - to_stock:
            variance = variance or _system("price_variance", "Purchase price variance")
            add(variance, difference - to_stock, division, line.item.code)
    if exchange > 0:
        add(_system("exchange_loss", "Exchange loss"), exchange, division, "Exchange difference")
    elif exchange < 0:
        add(_system("exchange_gain", "Exchange gain"), exchange, division, "Exchange difference")
    lines = [
        journal.Line(
            account=account,
            debit=amount if amount > 0 else Decimal("0"),
            credit=-amount if amount < 0 else Decimal("0"),
            division=line_division,
            supplier=invoice.supplier,
            description=description,
        )
        for account, amount, line_division, description in debits.values()
        if amount
    ]
    payable = sum((amount for _, amount, _, _ in debits.values()), Decimal("0"))
    lines.append(
        journal.Line(
            account=_system("accounts_payable", "Accounts payable"),
            credit=payable,
            division=division,
            supplier=invoice.supplier,
            description=f"{invoice.invoice_no} due {invoice.due_date:%d-%b-%Y}",
        )
    )
    try:
        entry = journal.post(
            user,
            entry_date=invoice.invoice_date,
            narration=f"Supplier invoice {invoice.invoice_no} of {invoice.supplier.name} "
            f"({invoice.number})",
            lines=lines,
            source_type="supplier_invoice",
            source_id=invoice.number,
        )
    except AccountingError as error:
        raise InvoiceError(str(error)) from None
    for grn_line, shares in adjustments:
        for lot, store, value in shares:
            StockMovement.objects.create(
                item=grn_line.item,
                store_id=store,
                division=grn_line.receipt.division,
                lot_no=lot,
                kind=StockMovement.Kind.PRICE,
                movement_date=invoice.invoice_date,
                quantity=Decimal("0"),
                value=value,
                receipt_line=grn_line,
                journal_entry=entry,
                created_by=user,
            )
    currencies.mark_rate_used(lookup)
    invoice.journal_entry = entry
    invoice.total_lkr = payable
    invoice.exchange_rate = rate
    invoice.rate_date = lookup.rate_date
    invoice.status = St.POSTED
    invoice.posted_at = timezone.now()
    invoice.save(
        update_fields=[
            "journal_entry",
            "total_lkr",
            "exchange_rate",
            "rate_date",
            "status",
            "posted_at",
        ]
    )
    from . import advances  # advances reads this module

    try:
        advances.apply(user, invoice)
    except advances.AdvanceError as error:
        raise InvoiceError(str(error)) from None


# --- Scans -----------------------------------------------------------------------------------


def add_attachment(user: User, invoice: SupplierInvoice, uploaded) -> SupplierInvoiceAttachment:
    with audit_context("supplier_invoice_attachment_added"), transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        if not can_edit(user, invoice):
            raise InvoiceError("The scan is added while the invoice is a draft.")
        if invoice.attachments.count() >= MAX_FILES:
            raise InvoiceError(f"An invoice can have at most {MAX_FILES} files.")
        if uploaded.size > MAX_FILE_BYTES:
            raise InvoiceError("The file is larger than 20 MB.")
        content = uploaded.read()
        kind = next((k for magic, k in FILE_TYPES.items() if content.startswith(magic)), None)
        if kind is None:
            raise InvoiceError("Only JPG, PNG and PDF files can be added.")
        content_type, extension = kind
        digest = hashlib.sha256(content).hexdigest()
        name = (uploaded.name or f"invoice{extension}").replace("/", "_").replace("\\", "_")
        uploaded.seek(0)
        attachment = SupplierInvoiceAttachment(
            invoice=invoice,
            file_name=name[-200:],
            content_type=content_type,
            size=len(content),
            sha256=digest,
            uploaded_by=user,
        )
        attachment.file.save(f"{invoice.number}-{digest[:12]}{extension}", uploaded, save=False)
        attachment.save()
        return attachment


def remove_attachment(user: User, attachment: SupplierInvoiceAttachment) -> None:
    with audit_context("supplier_invoice_attachment_removed"), transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=attachment.invoice_id)
        if not can_edit(user, invoice):
            raise InvoiceError("A scan is removed only from a draft.")
        attachment.file.delete(save=False)
        attachment.delete()


# --- Payment (P16-11) ----------------------------------------------------------------------


def on_vouchers(invoice: SupplierInvoice, *, excluding=None) -> Decimal:
    """What the vouchers that still count pay on the invoice (approved or not, paid or not)."""
    from apps.vouchers.models import VoucherLine
    from apps.vouchers.services import INVOICE_FREED

    rows = VoucherLine.objects.filter(supplier_invoice=invoice).exclude(
        voucher__status__in=INVOICE_FREED
    )
    if excluding is not None and excluding.pk:
        rows = rows.exclude(voucher=excluding)
    total = sum((line.amount + line.tax_amount for line in rows), Decimal("0"))
    return total


def unpaid(invoice: SupplierInvoice, *, excluding=None) -> Decimal:
    """What is left to put on a voucher: the invoice total in LKR less the advances set off
    against it (P16-11a) and the vouchers on it."""
    from .advances import set_off_total

    if invoice.status != St.POSTED:
        return Decimal("0")
    from .returns import debited

    left = (
        invoice.total_lkr
        - set_off_total(invoice)
        - debited(invoice)
        - on_vouchers(invoice, excluding=excluding)
    )
    return max(left, Decimal("0"))


def payable(supplier: Supplier, division) -> list[SupplierInvoice]:
    """Posted invoices of the supplier and division with something left to pay, oldest due
    first."""
    rows = SupplierInvoice.objects.filter(
        supplier=supplier, division=division, status=St.POSTED
    ).order_by("due_date", "number")
    return [i for i in rows if unpaid(i) > 0]


def match_summary(invoice: SupplierInvoice) -> list[dict]:
    """PO, GRN and invoice side by side, line by line, for the approvers of a voucher."""
    rows = []
    for line in invoice.lines.select_related(
        "grn_line__receipt__purchase_order", "grn_line__po_line", "item"
    ):
        grn_line = line.grn_line
        rows.append(
            {
                "item": {"code": line.item.code, "name": line.item.name, "unit": line.item.unit},
                "po": {
                    "id": grn_line.receipt.purchase_order_id,
                    "label": grn_line.receipt.purchase_order.label,
                    "quantity": str(grn_line.po_line.quantity),
                    "unit_price": str(line.po_unit_price),
                },
                "grn": {
                    "id": grn_line.receipt_id,
                    "number": grn_line.receipt.number,
                    "received": str(grn_line.received_quantity),
                    "accepted": str(accepted(grn_line)),
                },
                "invoice": {
                    "quantity": str(line.quantity),
                    "unit_price": str(line.unit_price),
                    "total": str(line.total),
                },
                "matches": line.unit_price == line.po_unit_price
                and line.tax_code_id == line.po_tax_code_id,
            }
        )
    return rows
