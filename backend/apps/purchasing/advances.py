"""Advance payments on purchase orders (backlog P16-11a, spec 5A.5).

- A voucher line can pay an advance on an approved PO before the goods arrive. It is an
  exception: the voucher shows it to the Accountant and the Director, who approves it as
  every voucher (rule 6). The line is coded to Advances to suppliers; the advances on a PO
  never add up to more than the PO (service and database).
- Once the voucher is fully paid, the advance is set off against the supplier's invoices
  for that PO: Dr Accounts payable, Cr Advances to suppliers, never more than is still
  unpaid on the invoice. This happens when the invoice is posted, or later when the
  Accountant clicks "Set off advances" (an advance paid after the invoice was posted).
- Set-offs are never changed or deleted (database guard).
"""

from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from apps.accounting import journal
from apps.accounting.models import Account
from apps.accounting.services import AccountingError
from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import User

from .models import AdvanceSetOff, PurchaseOrder, SupplierInvoice


class AdvanceError(Exception):
    pass


def can_set_off(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def set_off_total(invoice: SupplierInvoice) -> Decimal:
    return invoice.set_offs.aggregate(total=Sum("amount"))["total"] or Decimal("0")


def available(line) -> Decimal:
    """What a paid advance line still has to set off."""
    from apps.vouchers.models import Voucher

    if line.voucher.status != Voucher.Status.PAID:
        return Decimal("0")
    used = line.set_offs.aggregate(total=Sum("amount"))["total"] or Decimal("0")
    return max(line.amount + line.tax_amount - used, Decimal("0"))


def advance_lines(orders):
    from apps.vouchers.models import VoucherLine

    return (
        VoucherLine.objects.filter(advance_order__in=orders)
        .select_related("voucher")
        .order_by("voucher__voucher_date", "voucher__number", "line_no")
    )


def orders_of(invoice: SupplierInvoice) -> list[PurchaseOrder]:
    return list(
        PurchaseOrder.objects.filter(receipts__lines__invoice_lines__invoice=invoice).distinct()
    )


def waiting(invoice: SupplierInvoice) -> Decimal:
    """Paid advances on the invoice's POs not yet set off."""
    return sum((available(line) for line in advance_lines(orders_of(invoice))), Decimal("0"))


def apply(user: User, invoice: SupplierInvoice) -> list[AdvanceSetOff]:
    """Set off the paid advances on the invoice's POs, oldest first, up to what is unpaid."""
    from . import invoices

    if invoice.status != SupplierInvoice.Status.POSTED:
        return []
    made = []
    payable = Account.objects.filter(system_role="accounts_payable", is_active=True).first()
    advances = Account.objects.filter(system_role="supplier_advances", is_active=True).first()
    for line in advance_lines(orders_of(invoice)).select_for_update(of=("self",)):
        left = invoices.unpaid(invoice)
        amount = min(available(line), left)
        if amount <= 0:
            continue
        if payable is None or advances is None:
            raise AdvanceError(
                "The Accounts payable and Advances to suppliers accounts must be active."
            )
        try:
            entry = journal.post(
                user,
                entry_date=max(invoice.invoice_date, line.voucher.voucher_date),
                narration=(
                    f"Advance paid on voucher {line.voucher.number} set off against supplier "
                    f"invoice {invoice.invoice_no} ({invoice.number})"
                ),
                lines=[
                    journal.Line(
                        account=payable,
                        debit=amount,
                        division=invoice.division,
                        supplier=invoice.supplier,
                        description=invoice.invoice_no,
                    ),
                    journal.Line(
                        account=advances,
                        credit=amount,
                        division=invoice.division,
                        supplier=invoice.supplier,
                        description=line.voucher.number,
                    ),
                ],
                source_type="advance_set_off",
                source_id=invoice.number,
            )
        except AccountingError as error:
            raise AdvanceError(str(error)) from None
        made.append(
            AdvanceSetOff.objects.create(
                invoice=invoice,
                voucher_line=line,
                amount=amount,
                journal_entry=entry,
                created_by=user,
            )
        )
    return made


def set_off_later(user: User, invoice: SupplierInvoice) -> list[AdvanceSetOff]:
    """The Accountant sets off an advance paid after the invoice was posted."""
    if not can_set_off(user):
        raise AdvanceError("The Accountant sets off advances.")
    with audit_context("advance_set_off"), transaction.atomic():
        invoice = SupplierInvoice.objects.select_for_update().get(pk=invoice.pk)
        made = apply(user, invoice)
        if not made:
            raise AdvanceError("There is no paid advance on these purchase orders to set off.")
        return made
