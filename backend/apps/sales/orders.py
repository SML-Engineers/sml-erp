"""Sales orders (backlog P15-10, spec 5.3).

- Made from an accepted quotation, or with one click from an issued proforma, with the
  prices carried over (the quotation's price for each quantity, as on proformas); or entered
  directly for a repeat order, when the prices are typed and the Director approves the order
  before it is confirmed (owner's decision pending: the default chosen on 31 Oct 2026).
- Numbered SO{YY}{MM}{DD}{XX} on creation, in the saving transaction (rule 10).
- The customer's PO number is required to confirm. Each line has a delivery schedule: one
  date or several (moulding call-offs), adding up to the line's quantity.
- Status: Draft → (Awaiting approval, direct orders) → Open → Completed; Partly delivered comes
  with deliveries in Phase 2; Cancelled with a reason. Once confirmed nothing on the order
  changes (database guard), only its status.
- Every document links back to the one it came from and forward to those made from it.
"""

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode
from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters import currencies, customers
from apps.masters.models import Customer, CustomerContact
from apps.masters.services import MastersError

from .models import (
    CustomerAdvance,
    DeliverySchedule,
    ProformaInvoice,
    Quotation,
    QuotationLine,
    SalesOrder,
    SalesOrderLine,
)
from .proformas import price_for
from .proformas import visible as visible_proformas
from .services import SalesError, _decimal, can_enter, sees_all
from .services import visible as visible_quotations

DOC = "sales_order"
CENT = Decimal("0.01")
QTY = Decimal("0.001")
St = SalesOrder.Status
MAX_LINES = 200
MAX_DELIVERIES = 60


@dataclass
class Delivery:
    due_date: object
    quantity: object


@dataclass
class LineInput:
    quantity: object
    quotation_line: QuotationLine | None = None
    # Typed only for a direct (repeat) order.
    description: str = ""
    unit_price: object = None
    unit: str = "pcs"
    drawing_no: str = ""
    tax_code: TaxCode | None = None
    schedule: list[Delivery] = field(default_factory=list)


# --- Who may do what --------------------------------------------------------------------


def visible(user: User) -> QuerySet[SalesOrder]:
    if not effective_access(user).has("sales", "view"):
        return SalesOrder.objects.none()
    rows = SalesOrder.objects.filter(division__in=division_scope(user))
    return rows if sees_all(user) else rows.filter(created_by=user)


def can_edit(user: User, order: SalesOrder) -> bool:
    return order.status == St.DRAFT and order.created_by_id == user.pk and can_enter(user)


def _owner_or_manager(user: User, order: SalesOrder) -> bool:
    if not visible(user).filter(pk=order.pk).exists():
        return False
    return order.created_by_id == user.pk or effective_access(user).has("sales", "approve")


def can_approve(user: User, order: SalesOrder) -> bool:
    state = approvals.state_of(DOC, order.pk)
    return (
        order.status == St.AWAITING_APPROVAL
        and state is not None
        and approvals.why_not(user, state) is None
    )


def can_complete(user: User, order: SalesOrder) -> bool:
    return order.status in (St.OPEN, St.PARTLY_DELIVERED) and _owner_or_manager(user, order)


def can_cancel(user: User, order: SalesOrder) -> bool:
    return order.status in (St.DRAFT, St.OPEN) and _owner_or_manager(user, order)


# --- Making an order --------------------------------------------------------------------


def _new(user: User, *, source, customer, division, currency, **values) -> SalesOrder:
    today = timezone.localdate()
    try:
        lookup = currencies.rate_on(currency, today)
    except MastersError as error:
        raise SalesError(str(error)) from None
    try:
        number = allocate("sales_order", division=division, on_date=today)
    except NumberSeriesError as error:
        raise SalesError(str(error)) from None
    order = SalesOrder.objects.create(
        number=number,
        source=source,
        customer=customer,
        division=division,
        order_date=today,
        currency=currency,
        exchange_rate=lookup.rate,
        rate_date=lookup.rate_date,
        delivery_address=customer.delivery_address,
        created_by=user,
        **values,
    )
    currencies.mark_rate_used(lookup)
    customers.mark_used(customer)
    return order


def _default_schedule(quantity: Decimal) -> list[Delivery]:
    return [Delivery(timezone.localdate(), quantity)]


def from_quotation(user: User, quotation: Quotation) -> SalesOrder:
    if not can_enter(user):
        raise SalesError("You cannot make sales orders.")
    if not visible_quotations(user).filter(pk=quotation.pk).exists():
        raise SalesError("You cannot see this quotation.")
    if quotation.status != Quotation.Status.ACCEPTED:
        raise SalesError("A sales order is made from an accepted quotation: mark it won first.")
    with audit_context("sales_order_created"), transaction.atomic():
        contact = quotation.contact if quotation.contact and quotation.contact.is_active else None
        order = _new(
            user,
            source=SalesOrder.Source.QUOTATION,
            customer=quotation.customer,
            division=quotation.division,
            currency=quotation.currency,
            quotation=quotation,
            contact=contact,
            payment_terms=quotation.payment_terms,
            incoterm=quotation.incoterm,
            notes=quotation.notes,
            discount_pct=quotation.discount_pct,
        )
        lines = [
            LineInput(
                quantity=line.quantity,
                quotation_line=line,
                schedule=_default_schedule(line.quantity),
            )
            for line in quotation.lines.prefetch_related("breaks")
        ]
        _fill(order, [_check_line(n, line, order) for n, line in enumerate(lines, start=1)])
        return order


def from_proforma(user: User, proforma: ProformaInvoice) -> SalesOrder:
    """One click from an issued proforma: its lines, quantities, prices and terms."""
    if not can_enter(user):
        raise SalesError("You cannot make sales orders.")
    if not visible_proformas(user).filter(pk=proforma.pk).exists():
        raise SalesError("You cannot see this proforma.")
    if proforma.status != ProformaInvoice.Status.ISSUED:
        raise SalesError("A sales order is made from an issued proforma.")
    with audit_context("sales_order_created"), transaction.atomic():
        order = _new(
            user,
            source=SalesOrder.Source.PROFORMA,
            customer=proforma.customer,
            division=proforma.division,
            currency=proforma.currency,
            quotation=proforma.quotation,
            proforma=proforma,
            contact=proforma.contact,
            customer_po=proforma.customer_po,
            payment_terms=proforma.payment_terms,
            incoterm=proforma.incoterm,
            notes=proforma.notes,
            discount_pct=proforma.discount_pct,
        )
        lines = [
            LineInput(
                quantity=line.quantity,
                quotation_line=line.quotation_line,
                schedule=_default_schedule(line.quantity),
            )
            for line in proforma.lines.select_related("quotation_line")
        ]
        _fill(order, [_check_line(n, line, order) for n, line in enumerate(lines, start=1)])
        return order


def direct(
    user: User, *, customer: Customer, division: Division, lines: list[LineInput], **values
) -> SalesOrder:
    """A repeat order typed in directly; the Director approves it before it is confirmed."""
    if not can_enter(user):
        raise SalesError("You cannot make sales orders.")
    if not isinstance(customer, Customer) or not customer.is_active:
        raise SalesError("Choose an active customer.")
    if not isinstance(division, Division) or division.division_type != Division.Type.PRODUCTION:
        raise SalesError("A sales order is for a production division (Workshop or Moulding).")
    if not division_scope(user).filter(pk=division.pk).exists():
        raise SalesError(f"You do not work in division {division.code}.")
    if not lines:
        raise SalesError("A sales order needs at least one line.")
    with audit_context("sales_order_created"), transaction.atomic():
        order = _new(
            user,
            source=SalesOrder.Source.DIRECT,
            customer=customer,
            division=division,
            currency=customer.currency,
            payment_terms=(
                f"{customer.payment_terms_days} days" if customer.payment_terms_days else ""
            ),
            incoterm=customer.incoterm,
            contact=customer.contacts.filter(is_main=True, is_active=True).first(),
        )
        for key, value in _header(values, order).items():
            setattr(order, key, value)
        _fill(order, [_check_line(n, line, order) for n, line in enumerate(lines, start=1)])
        return order


# --- Checking and working out -----------------------------------------------------------


def _check_schedule(where: str, rows: list[Delivery], quantity: Decimal) -> list[tuple]:
    if not rows:
        raise SalesError(where + "give the delivery date (or dates).")
    if len(rows) > MAX_DELIVERIES:
        raise SalesError(where + f"at most {MAX_DELIVERIES} deliveries.")
    checked = []
    for row in rows:
        if not isinstance(row.due_date, date):
            raise SalesError(where + "each delivery needs a date.")
        try:
            amount = _decimal(row.quantity, "delivery quantity", QTY, positive=True)
        except SalesError as error:
            raise SalesError(where + str(error)) from None
        checked.append((row.due_date, amount))
    total = sum((q for _, q in checked), Decimal("0"))
    if total != quantity:
        raise SalesError(
            where + f"the deliveries add up to {total.normalize():f}, not the line's "
            f"{quantity.normalize():f}."
        )
    return sorted(checked)


def _check_line(n: int, line: LineInput, order: SalesOrder) -> dict:
    where = f"Line {n}: "
    try:
        quantity = _decimal(line.quantity, "quantity", QTY, positive=True)
    except SalesError as error:
        raise SalesError(where + str(error)) from None
    if order.source == SalesOrder.Source.DIRECT:
        description = (line.description or "").strip()
        if not description:
            raise SalesError(where + "the description is required.")
        try:
            price = _decimal(line.unit_price, "unit price", CENT, positive=False)
        except SalesError as error:
            raise SalesError(where + str(error)) from None
        tax_code = line.tax_code
        if tax_code is not None and (
            not tax_code.is_active or tax_code.use == TaxCode.Use.PURCHASES
        ):
            raise SalesError(where + f"tax code {tax_code.code} cannot be used on sales.")
        values = {
            "quotation_line": None,
            "description": description,
            "drawing_no": (line.drawing_no or "").strip()[:50],
            "unit": (line.unit or "pcs").strip()[:20] or "pcs",
            "unit_price": price,
            "is_tooling": False,
            "tax_code": tax_code,
        }
    else:
        source = line.quotation_line
        if not isinstance(source, QuotationLine) or source.quotation_id != order.quotation_id:
            raise SalesError(where + "choose a line of the quotation.")
        values = {
            "quotation_line": source,
            "description": source.description,
            "drawing_no": source.drawing_no,
            "unit": source.unit,
            "unit_price": price_for(source, quantity),
            "is_tooling": source.is_tooling,
            "tax_code": source.tax_code,
        }
    values["quantity"] = quantity
    values["schedule"] = _check_schedule(where, line.schedule, quantity)
    return values


def _header(values: dict, order: SalesOrder) -> dict:
    def text(name, limit):
        value = values.get(name, getattr(order, name))
        return (value or "").strip()[:limit]

    incoterm = text("incoterm", 3).upper()
    if incoterm and incoterm not in Customer.Incoterm.values:
        raise SalesError("The delivery term must be an Incoterm, for example EXW or FOB.")
    po_date = values.get("po_date", order.po_date)
    if po_date is not None and not isinstance(po_date, date):
        raise SalesError("The PO date is not a date.")
    contact = values.get("contact", order.contact)
    if contact is not None and (
        not isinstance(contact, CustomerContact) or contact.customer_id != order.customer_id
    ):
        raise SalesError("Choose one of the customer's contacts.")
    result = {
        "customer_po": text("customer_po", 50),
        "po_date": po_date,
        "payment_terms": text("payment_terms", 200),
        "incoterm": incoterm,
        "delivery_address": text("delivery_address", 1000),
        "notes": text("notes", 5000),
        "contact": contact,
    }
    # Prices and discount come from the quotation, except on a repeat order typed in.
    if order.source == SalesOrder.Source.DIRECT and "discount_pct" in values:
        discount = values["discount_pct"]
        discount = (
            Decimal("0")
            if discount in (None, "")
            else _decimal(discount, "discount %", CENT, positive=False)
        )
        if discount >= 100:
            raise SalesError("The discount must be below 100%.")
        result["discount_pct"] = discount
    return result


def _fill(order: SalesOrder, checked: list[dict]) -> None:
    if len(checked) > MAX_LINES:
        raise SalesError(f"A sales order can have at most {MAX_LINES} lines.")
    order.lines.all().delete()
    subtotal = tax_total = discount_total = Decimal("0")
    for n, line in enumerate(checked, start=1):
        schedule = line.pop("schedule")
        amount = (line["quantity"] * line["unit_price"]).quantize(CENT, ROUND_HALF_UP)
        discount = (amount * order.discount_pct / 100).quantize(CENT, ROUND_HALF_UP)
        net = amount - discount
        tax = Decimal("0")
        if line["tax_code"] is not None:
            tax = taxes.calculate(line["tax_code"], net, order.order_date).tax
        row = SalesOrderLine.objects.create(
            order=order,
            line_no=n,
            amount=amount,
            discount=discount,
            tax_amount=tax,
            total=net + tax,
            **line,
        )
        DeliverySchedule.objects.bulk_create(
            DeliverySchedule(line=row, seq=i, due_date=due, quantity=qty)
            for i, (due, qty) in enumerate(schedule, start=1)
        )
        subtotal += net
        discount_total += discount
        tax_total += tax
        if line["tax_code"] is not None:
            taxes.mark_used(line["tax_code"])
    order.discount_total = discount_total
    order.subtotal = subtotal
    order.tax_total = tax_total
    order.total_amount = subtotal + tax_total
    lookup = currencies.RateLookup(
        order.currency.code, order.order_date, order.exchange_rate, order.rate_date, None
    )
    order.total_lkr = currencies.to_lkr(order.total_amount, lookup)
    order.save()


# --- Changing, confirming, approving, completing, cancelling ---------------------------


def save(user: User, order: SalesOrder, *, lines: list[LineInput], **values) -> SalesOrder:
    with audit_context("sales_order_changed"), transaction.atomic():
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)
        if not can_edit(user, order):
            raise SalesError("Only the person who made a draft sales order changes it.")
        if not lines:
            raise SalesError("A sales order needs at least one line.")
        for key, value in _header(values, order).items():
            setattr(order, key, value)
        checked = [_check_line(n, line, order) for n, line in enumerate(lines, start=1)]
        used = [line["quotation_line"].pk for line in checked if line["quotation_line"]]
        if len(set(used)) != len(used):
            raise SalesError("Each line of the quotation can appear once.")
        _fill(order, checked)
        return order


def confirm(user: User, order: SalesOrder, comment: str = "") -> SalesOrder:
    """Open the order; a repeat order typed in goes to the Director first."""
    with audit_context("sales_order_confirmed", comment), transaction.atomic():
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)
        if not can_edit(user, order):
            raise SalesError("Only the person who made a draft sales order confirms it.")
        if not order.customer_po:
            raise SalesError("Enter the customer's PO number first.")
        if not order.lines.exists():
            raise SalesError("A sales order needs at least one line.")
        if order.source == SalesOrder.Source.DIRECT:
            try:
                approvals.submit(
                    user,
                    DOC,
                    order.pk,
                    created_by=order.created_by,
                    amount=order.total_lkr,
                    division=order.division,
                    comment=comment,
                    title=f"Sales order {order.number} for {order.customer.name}",
                    link=f"/sales-orders/{order.pk}",
                )
            except ApprovalError as error:
                raise SalesError(str(error)) from None
            order.status = St.AWAITING_APPROVAL
        else:
            order.status = St.OPEN
            order.confirmed_at = timezone.now()
        order.save(update_fields=["status", "confirmed_at"])
        return order


def approve(user: User, order: SalesOrder, comment: str = "") -> SalesOrder:
    with transaction.atomic():
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)
        if order.status != St.AWAITING_APPROVAL:
            raise SalesError("The sales order is not waiting for approval.")
        try:
            state = approvals.approve(user, DOC, order.pk, comment)
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("sales_order_approved", comment):
                order.status = St.OPEN
                order.confirmed_at = timezone.now()
                order.save(update_fields=["status", "confirmed_at"])
        return order


def send_back(user: User, order: SalesOrder, reason: str) -> SalesOrder:
    with transaction.atomic():
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)
        if order.status != St.AWAITING_APPROVAL:
            raise SalesError("The sales order is not waiting for approval.")
        try:
            approvals.send_back(user, DOC, order.pk, reason)
        except ApprovalError as error:
            raise SalesError(str(error)) from None
        with audit_context("sales_order_returned", reason):
            order.status = St.DRAFT
            order.save(update_fields=["status"])
        return order


def complete(user: User, order: SalesOrder) -> SalesOrder:
    """Close an open order by hand (from Phase 2, deliveries do it)."""
    with audit_context("sales_order_completed"), transaction.atomic():
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)
        if not can_complete(user, order):
            raise SalesError(
                "Only an open order is completed, by its creator or the Sales Manager."
            )
        order.status = St.COMPLETED
        order.save(update_fields=["status"])
        return order


def cancel(user: User, order: SalesOrder, reason: str) -> SalesOrder:
    reason = (reason or "").strip()
    if not reason:
        raise SalesError("Give a reason for cancelling the sales order.")
    with audit_context("sales_order_cancelled", reason), transaction.atomic():
        order = SalesOrder.objects.select_for_update().get(pk=order.pk)
        if not can_cancel(user, order):
            raise SalesError(
                "A draft or open sales order is cancelled, by its creator or the Sales Manager."
            )
        if order.advances.filter(status=CustomerAdvance.Status.APPROVED).exists():
            raise SalesError("An advance has been received against this order; it stays open.")
        order.status = St.CANCELLED
        order.cancel_reason = reason[:1000]
        order.save(update_fields=["status", "cancel_reason"])
        return order
