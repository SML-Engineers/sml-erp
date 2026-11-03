"""Tax invoices (backlog P2-05, spec 6.1).

- Made from the delivered quantities of one sales order: its issued (or signed) delivery
  notes that are not yet invoiced. Each delivery note line is invoiced once (database rule).
  Prices, discount and tax codes come from the order; the taxes are worked out at the
  invoice date's rates: SSCL on the net amount, then VAT on net plus SSCL, each rounded
  half-up to the cent (spec 6.1 example: 115,750.00 + 2,459.69 SSCL, VAT 21,277.74, total
  139,487.43).
- Sales or the Accountant prepare the draft. It is issued by the Director, the Accountant,
  or the salespeople the Admin gives the "Issue tax invoices" right to; not every
  salesperson (owner, 3 Nov 2026). Issuing:
  - needs the division's tax invoice code (Settings -> Divisions) and the company's TIN;
  - numbers it YYMMM_QQQQ_XX from the "tax_invoice" series of the invoice date's month, per
    division, inside the same transaction (rule 10), so drafts leave no gaps;
  - copies the supplier's and the customer's details onto it, as printed;
  - posts Dr Accounts receivable (with the customer), Cr Sales per division (the division's
    sales account, or its tooling account for tooling lines), Cr each tax's sales account.
  - sets off the approved advances of its order against it (P2-07).
- An issued invoice is never changed or deleted (database guard); a credit note corrects
  it (P2-06). A delivery note on an invoice cannot be cancelled.
- LKR only for now; invoices in the customer's currency come with P2-09.
"""

from collections import OrderedDict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounting import journal, taxes
from apps.accounting.models import Account, TaxCodeLine
from apps.accounting.services import AccountingError
from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import Company, Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters import customers

from . import words
from .models import (
    DeliveryNote,
    DeliveryNoteLine,
    SalesAccount,
    SalesOrder,
    TaxInvoice,
    TaxInvoiceLine,
    TaxInvoiceTax,
)
from .services import SalesError

DOC = "tax_invoice"
CENT = Decimal("0.01")
St = TaxInvoice.Status
OS = SalesOrder.Status
DELIVERED = (DeliveryNote.Status.ISSUED, DeliveryNote.Status.RECEIVED)


# --- Who may do what ---------------------------------------------------------------------


def can_view(user: User) -> bool:
    access = effective_access(user)
    return access.has("sales", "view") or access.has("accounting", "view")


def can_prepare(user: User) -> bool:
    access = effective_access(user)
    return access.has("sales", "enter") or access.has("accounting", "enter")


def can_issue_any(user: User) -> bool:
    """Issuing needs the "issue_tax_invoices" action: the Director and the Accountant by
    their roles, and the salespeople the Admin grants it to (owner, 3 Nov 2026)."""
    return can_view(user) and effective_access(user).can("issue_tax_invoices")


def _sees_all(user: User) -> bool:
    access = effective_access(user)
    if access.has("accounting", "view") or access.has("sales", "approve"):
        return True
    return not access.has("sales", "enter")


def visible(user: User) -> QuerySet[TaxInvoice]:
    if not can_view(user):
        return TaxInvoice.objects.none()
    rows = TaxInvoice.objects.filter(division__in=division_scope(user))
    return rows if _sees_all(user) else rows.filter(order__created_by=user)


def orders_to_invoice(user: User) -> QuerySet[SalesOrder]:
    """Orders with delivered quantities not yet on an invoice."""
    if not can_prepare(user):
        return SalesOrder.objects.none()
    waiting = DeliveryNoteLine.objects.filter(
        note__status__in=DELIVERED, invoice_line__isnull=True
    ).values("note__order_id")
    rows = SalesOrder.objects.filter(pk__in=waiting, division__in=division_scope(user)).exclude(
        status=OS.CANCELLED
    )
    return rows if _sees_all(user) else rows.filter(created_by=user)


def can_edit(user: User, invoice: TaxInvoice) -> bool:
    if invoice.status != St.DRAFT or not can_prepare(user):
        return False
    return invoice.created_by_id == user.pk or effective_access(user).has("accounting", "enter")


def can_issue(user: User, invoice: TaxInvoice) -> bool:
    return invoice.status == St.DRAFT and can_issue_any(user)


# --- Sales accounts --------------------------------------------------------------------------


def sales_accounts() -> list[SalesAccount]:
    return list(
        SalesAccount.objects.select_related("division", "account", "tooling_account").order_by(
            "division__code"
        )
    )


def set_sales_account(user: User, division: Division, account: Account, tooling: Account):
    if not effective_access(user).has("accounting", "manage"):
        raise SalesError("Only the Accountant sets the sales accounts.")
    for chosen in (account, tooling):
        if chosen.account_type not in ("income", "other_income"):
            raise SalesError(f"{chosen.name} is not an income account.")
        if not chosen.is_active or chosen.merged_into_id:
            raise SalesError(f"{chosen.name} is inactive or merged.")
    with audit_context("sales_account_set"), transaction.atomic():
        row, _ = SalesAccount.objects.update_or_create(
            division=division, defaults={"account": account, "tooling_account": tooling}
        )
        return row


# --- Figures ---------------------------------------------------------------------------------


def _round(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def _compute(invoice: TaxInvoice) -> None:
    """Each line's taxes at the invoice date's rates, the taxes by component and rate, and
    the totals. Saved on the draft (and again when it is issued)."""
    groups: OrderedDict = OrderedDict()
    subtotal = discount_total = Decimal("0")
    try:
        for line in invoice.lines.select_related("tax_code"):
            tax = Decimal("0")
            if line.tax_code is not None:
                bases = dict(
                    TaxCodeLine.objects.filter(tax_code=line.tax_code).values_list(
                        "component_id", "base"
                    )
                )
                for part in taxes.calculate(line.tax_code, line.net, invoice.invoice_date).lines:
                    on_tax = bases.get(part.component.pk) == TaxCodeLine.Base.NET_AND_TAX
                    key = (part.component.pk, part.rate, on_tax)
                    if key not in groups:
                        groups[key] = [part.component, Decimal("0")]
                    groups[key][1] += part.amount
                    tax += part.amount
            if line.tax_amount != tax:
                line.tax_amount = tax
                line.save(update_fields=["tax_amount"])
            subtotal += line.amount
            discount_total += line.discount
    except AccountingError as error:
        raise SalesError(str(error)) from None
    invoice.taxes.all().delete()
    ordered = sorted(groups.items(), key=lambda item: item[0][2])  # on the net amount first
    for seq, ((_, rate, on_tax), (component, amount)) in enumerate(ordered, start=1):
        TaxInvoiceTax.objects.create(
            invoice=invoice,
            seq=seq,
            component=component,
            label=component.label,
            rate=rate,
            on_tax=on_tax,
            amount=amount,
        )
    invoice.subtotal = subtotal
    invoice.discount_total = discount_total
    invoice.tax_total = sum((amount for _, amount in groups.values()), Decimal("0"))
    invoice.total_amount = subtotal - discount_total + invoice.tax_total
    invoice.amount_in_words = words.amount(invoice.total_amount)


# --- Making a draft -------------------------------------------------------------------------


@dataclass
class Header:
    invoice_date: date | None = None
    supply_date: date | None = None
    place_of_supply: str | None = None
    terms: str | None = None
    notes: str | None = None


def _one_line(text: str) -> str:
    return ", ".join(x.strip() for x in (text or "").splitlines() if x.strip())[:200]


def _header(invoice: TaxInvoice, values: Header) -> None:
    today = timezone.localdate()
    if values.invoice_date is not None:
        if values.invoice_date > today:
            raise SalesError("The invoice date cannot be in the future.")
        invoice.invoice_date = values.invoice_date
    if values.supply_date is not None:
        if values.supply_date > today:
            raise SalesError("The date of supply cannot be in the future.")
        invoice.supply_date = values.supply_date
    if values.place_of_supply is not None:
        invoice.place_of_supply = _one_line(values.place_of_supply)
    if values.terms is not None:
        invoice.terms = " ".join(values.terms.split())[:200]
    if values.notes is not None:
        invoice.notes = values.notes.strip()[:2000]
    days = invoice.customer.payment_terms_days
    invoice.due_date = invoice.invoice_date + timedelta(days=days)


def _accounts(division: Division) -> SalesAccount:
    row = SalesAccount.objects.filter(division=division).select_related(
        "account", "tooling_account"
    )
    if not row.exists():
        raise SalesError(
            f"Division {division.code} has no sales account: the Accountant sets it on "
            "Accounts -> Sales accounts."
        )
    return row.get()


def create(user: User, order: SalesOrder, notes: list[DeliveryNote] | None = None) -> TaxInvoice:
    """A draft from the order's delivery notes that are not yet invoiced (all of them, or
    the ones chosen)."""
    if not can_prepare(user):
        raise SalesError("Only Sales or the Accountant prepare tax invoices.")
    with audit_context("tax_invoice_created"), transaction.atomic():
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)
        if not orders_to_invoice(user).filter(pk=order.pk).exists():
            raise SalesError("The order has no delivered quantities waiting to be invoiced.")
        base = Company.objects.filter(pk=1).values_list("base_currency", flat=True).first()
        if order.currency.code != (base or "LKR"):
            raise SalesError(
                "Invoices in the customer's currency come with export invoicing (P2-09)."
            )
        waiting = DeliveryNoteLine.objects.filter(
            note__order=order, note__status__in=DELIVERED, invoice_line__isnull=True
        ).select_related("note", "order_line__tax_code")
        if notes:
            waiting = waiting.filter(note__in=[n.pk for n in notes])
        rows = list(waiting.order_by("note__delivery_date", "note__number", "order_line__line_no"))
        if not rows:
            raise SalesError("The chosen delivery notes have nothing left to invoice.")
        accounts = _accounts(order.division)
        latest = max(r.note.delivery_date for r in rows)
        today = timezone.localdate()
        invoice = TaxInvoice(
            order=order,
            customer=order.customer,
            division=order.division,
            invoice_date=today,
            supply_date=latest,
            place_of_supply=_one_line(rows[-1].note.delivery_address or order.delivery_address),
            terms=order.payment_terms or f"{order.customer.payment_terms_days} days",
            customer_po=order.customer_po,
            created_by=user,
        )
        _header(invoice, Header())
        invoice.save()
        for n, row in enumerate(rows, start=1):
            ol = row.order_line
            amount = _round(row.quantity * ol.unit_price)
            TaxInvoiceLine.objects.create(
                invoice=invoice,
                line_no=n,
                delivery_line=row,
                product_code=ol.drawing_no,
                description=ol.description,
                po_no=order.customer_po,
                unit=ol.unit,
                quantity=row.quantity,
                rate=ol.unit_price,
                amount=amount,
                discount=_round(amount * order.discount_pct / Decimal("100")),
                tax_code=ol.tax_code,
                account=accounts.tooling_account if ol.is_tooling else accounts.account,
            )
        _compute(invoice)
        invoice.save()
        return invoice


def save(user: User, invoice: TaxInvoice, values: Header) -> TaxInvoice:
    with audit_context("tax_invoice_changed"), transaction.atomic():
        invoice = TaxInvoice.objects.select_for_update().get(pk=invoice.pk)
        if not can_edit(user, invoice):
            raise SalesError("Only a draft invoice is changed, by its maker or the Accountant.")
        _header(invoice, values)
        _compute(invoice)
        invoice.updated_at = timezone.now()
        invoice.save()
        return invoice


def delete(user: User, invoice: TaxInvoice) -> None:
    with audit_context("tax_invoice_deleted"), transaction.atomic():
        invoice = TaxInvoice.objects.select_for_update().get(pk=invoice.pk)
        if not can_edit(user, invoice):
            raise SalesError("Only a draft invoice is deleted, by its maker or the Accountant.")
        invoice.delete()


# --- Issuing ---------------------------------------------------------------------------------


def _journal_lines(invoice: TaxInvoice) -> list[journal.Line]:
    receivable = Account.objects.filter(system_role="accounts_receivable").first()
    if receivable is None:
        raise SalesError("The chart of accounts has no accounts receivable account.")
    division = invoice.division
    text = f"Tax invoice {invoice.number}"
    lines = [
        journal.Line(
            account=receivable,
            debit=invoice.total_amount,
            division=division,
            customer=invoice.customer,
            description=text,
        )
    ]
    income: OrderedDict = OrderedDict()
    for line in invoice.lines.select_related("account"):
        income[line.account] = income.get(line.account, Decimal("0")) + line.net
    for account, amount in income.items():
        if amount:
            lines.append(
                journal.Line(account=account, credit=amount, division=division, description=text)
            )
    for tax in invoice.taxes.select_related("component__sales_account"):
        if not tax.amount:
            continue
        account = tax.component.sales_account
        if account is None:
            raise SalesError(
                f"Tax {tax.component.code} has no sales account: the Accountant sets it on "
                "Accounts -> Taxes."
            )
        lines.append(
            journal.Line(
                account=account,
                credit=tax.amount,
                division=division,
                description=f"{text}: {tax.label} {tax.rate.normalize():f}%",
            )
        )
    return lines


def issue(user: User, invoice: TaxInvoice) -> TaxInvoice:
    """Issue the draft. A customer over its credit limit or with overdue invoices is stopped
    until the Director allows this invoice (P2-08)."""
    from . import receivables

    try:
        return _issue(user, invoice)
    except receivables.CreditBlocked as blocked:
        receivables.hold(user, blocked)
        raise SalesError(str(blocked)) from None


def _issue(user: User, invoice: TaxInvoice) -> TaxInvoice:
    from . import receivables

    with audit_context("tax_invoice_issued"), transaction.atomic():
        invoice = TaxInvoice.objects.select_for_update().get(pk=invoice.pk)
        if not can_issue(user, invoice):
            raise SalesError(
                "Issuing tax invoices needs the right to issue them: the Director, the "
                "Accountant, or a salesperson the Admin has given it to."
            )
        division = Division.objects.get(pk=invoice.division_id)
        if not division.tax_invoice_code:
            raise SalesError(
                f"Division {division.code} has no tax invoice code: the Admin sets it on "
                "Settings -> Divisions before any invoice is issued."
            )
        company = Company.objects.filter(pk=1).first()
        if company is None or not company.tin:
            raise SalesError("The company's TIN is required on a tax invoice: Settings -> Company.")
        if invoice.invoice_date > timezone.localdate():
            raise SalesError("The invoice date cannot be in the future.")
        cancelled = invoice.lines.exclude(delivery_line__note__status__in=DELIVERED)
        if cancelled.exists():
            raise SalesError(
                "A delivery note on this invoice has been cancelled: delete the draft."
            )
        _compute(invoice)
        if invoice.total_amount <= 0:
            raise SalesError("The invoice total must be more than zero.")
        receivables.require(
            user,
            kind="tax_invoice",
            document_id=invoice.pk,
            label=f"the invoice for order {invoice.order.number}",
            customer=invoice.customer,
            amount_lkr=invoice.total_amount,
        )
        customer = invoice.customer
        invoice.supplier_name = company.name
        invoice.supplier_tin = company.tin
        invoice.supplier_address = company.address
        invoice.supplier_phone = company.phone
        invoice.supplier_email = company.email
        invoice.customer_name = customer.name
        invoice.customer_tin = customer.tin
        invoice.customer_address = customer.billing_address
        try:
            invoice.number = allocate(DOC, division=division, on_date=invoice.invoice_date)
        except NumberSeriesError as error:
            raise SalesError(str(error)) from None
        try:
            entry = journal.post(
                user,
                entry_date=invoice.invoice_date,
                narration=f"Tax invoice {invoice.number} to {customer.name}"
                + (f" (PO {invoice.customer_po})" if invoice.customer_po else ""),
                lines=_journal_lines(invoice),
                source_type=DOC,
                source_id=invoice.number,
            )
        except AccountingError as error:
            raise SalesError(str(error)) from None
        invoice.journal_entry = entry
        invoice.status = St.ISSUED
        invoice.issued_by = user
        invoice.issued_at = timezone.now()
        invoice.updated_at = invoice.issued_at
        invoice.save()
        customers.mark_used(customer)
        _complete_order(invoice.order_id)
        # The order's advances are set off against it (spec 5.2; P2-07).
        from . import receipts

        receipts.set_off_advances(user, invoice)
        return invoice


def _complete_order(order_id: int) -> None:
    """A delivered order whose every delivered line is invoiced is completed."""
    order = SalesOrder.objects.select_for_update().get(pk=order_id)
    if order.status != OS.DELIVERED:
        return
    open_lines = DeliveryNoteLine.objects.filter(
        note__order=order, note__status__in=DELIVERED
    ).exclude(invoice_line__invoice__status=St.ISSUED)
    if not open_lines.exists():
        with audit_context("sales_order_invoiced"):
            order.status = OS.COMPLETED
            order.save(update_fields=["status"])
