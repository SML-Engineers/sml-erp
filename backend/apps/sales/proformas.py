"""Proforma invoices and their packing list (backlog P15-08, spec 5.2, 5.5).

- Made from an accepted quotation (won, P15-06) by a Sales Executive who sees it, with its
  customer, terms, discount and prices carried over: each line's price is the quotation's
  price for that quantity (its quantity breaks apply), so prices are never typed again.
- Numbered PI{YY}{MM}{DD}-{XX} (owner, 31 Oct 2026) on creation, in the saving transaction
  (rule 10); dated the day it is made, with the exchange rate of that day.
- Changed by its creator while a draft; then issued, and from then on never changed
  (database guard). An issued proforma can be cancelled with a reason, unless an approved
  customer advance stands against it.
- It records no sale and no receivable: nothing is posted to the journal (spec 5.2).
- Export fields: Incoterm, ports of loading and destination, and the bank account for the
  advance, printed with its bank details. An advance % prints the advance and the balance.
- Packing list (owner, 31 Oct 2026): per line the cartons, quantity per carton, net and gross
  weight and the carton's size, with totals and the volume; printed as its own page.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.accounting import taxes
from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters import currencies, customers
from apps.masters.models import CompanyAccount, Customer
from apps.masters.services import MastersError, mark_used

from .models import CustomerAdvance, ProformaInvoice, ProformaLine, Quotation, QuotationLine
from .services import SalesError, _decimal, can_enter, sales_tax_code, sees_all
from .services import visible as visible_quotations

CENT = Decimal("0.01")
QTY = Decimal("0.001")
P = ProformaInvoice.Status
BANK_KINDS = (CompanyAccount.Kind.CURRENT, CompanyAccount.Kind.SAVINGS)


@dataclass
class LineInput:
    quotation_line: QuotationLine | None
    quantity: object
    cartons: object = None
    qty_per_carton: object = None
    net_weight_kg: object = None
    gross_weight_kg: object = None
    carton_length_cm: object = None
    carton_width_cm: object = None
    carton_height_cm: object = None


# --- Who may do what --------------------------------------------------------------------


def visible(user: User) -> QuerySet[ProformaInvoice]:
    access = effective_access(user)
    if not access.has("sales", "view"):
        return ProformaInvoice.objects.none()
    rows = ProformaInvoice.objects.filter(division__in=division_scope(user))
    return rows if sees_all(user) else rows.filter(created_by=user)


def can_edit(user: User, proforma: ProformaInvoice) -> bool:
    return proforma.status == P.DRAFT and proforma.created_by_id == user.pk and can_enter(user)


def _owner_or_manager(user: User, proforma: ProformaInvoice) -> bool:
    if not visible(user).filter(pk=proforma.pk).exists():
        return False
    return proforma.created_by_id == user.pk or effective_access(user).has("sales", "approve")


def can_cancel(user: User, proforma: ProformaInvoice) -> bool:
    return proforma.status == P.ISSUED and _owner_or_manager(user, proforma)


def can_email(user: User, proforma: ProformaInvoice) -> bool:
    return proforma.status == P.ISSUED and _owner_or_manager(user, proforma)


# --- Prices and figures -----------------------------------------------------------------


def price_for(line: QuotationLine, quantity: Decimal) -> Decimal:
    """The quotation's unit price for this quantity: the price quoted for the largest of the
    line's quantity and its quantity breaks that is not more than it; below them all, the
    price of the smallest."""
    options = sorted(
        [(line.quantity, line.unit_price)] + [(b.quantity, b.unit_price) for b in line.breaks.all()]
    )
    price = options[0][1]
    for quoted, unit_price in options:
        if quoted <= quantity:
            price = unit_price
    return price


def _optional(value, what: str, step: Decimal) -> Decimal | None:
    if value in (None, ""):
        return None
    return _decimal(value, what, step, positive=False)


def _check_line(n: int, line: LineInput, quotation: Quotation) -> dict:
    where = f"Line {n}: "
    source = line.quotation_line
    if not isinstance(source, QuotationLine) or source.quotation_id != quotation.pk:
        raise SalesError(where + "choose a line of the quotation.")
    try:
        quantity = _decimal(line.quantity, "quantity", QTY, positive=True)
        cartons = _optional(line.cartons, "number of cartons", Decimal("1"))
        packing = {
            "cartons": None if cartons is None else int(cartons),
            "qty_per_carton": _optional(line.qty_per_carton, "quantity per carton", QTY),
            "net_weight_kg": _optional(line.net_weight_kg, "net weight", QTY),
            "gross_weight_kg": _optional(line.gross_weight_kg, "gross weight", QTY),
            "carton_length_cm": _optional(line.carton_length_cm, "carton length", Decimal("0.1")),
            "carton_width_cm": _optional(line.carton_width_cm, "carton width", Decimal("0.1")),
            "carton_height_cm": _optional(line.carton_height_cm, "carton height", Decimal("0.1")),
        }
    except SalesError as error:
        raise SalesError(where + str(error)) from None
    if cartons is not None and cartons != int(cartons):
        raise SalesError(where + "the number of cartons is a whole number.")
    net, gross = packing["net_weight_kg"], packing["gross_weight_kg"]
    if net is not None and gross is not None and gross < net:
        raise SalesError(where + "the gross weight cannot be less than the net weight.")
    return {
        "quotation_line": source,
        "description": source.description,
        "drawing_no": source.drawing_no,
        "quantity": quantity,
        "unit": source.unit,
        "unit_price": price_for(source, quantity),
        "is_tooling": source.is_tooling,
        "tax_code": sales_tax_code(source.quotation.customer, source.tax_code),
        **packing,
    }


def _header(values: dict, proforma: ProformaInvoice) -> dict:
    def text(name, limit):
        value = values.get(name, getattr(proforma, name))
        return (value or "").strip()[:limit]

    incoterm = text("incoterm", 3).upper()
    if incoterm and incoterm not in Customer.Incoterm.values:
        raise SalesError("The delivery term must be an Incoterm, for example EXW or FOB.")
    advance = values.get("advance_pct", proforma.advance_pct)
    advance = (
        Decimal("0")
        if advance in (None, "")
        else _decimal(advance, "advance %", CENT, positive=False)
    )
    if advance > 100:
        raise SalesError("The advance cannot be more than 100%.")
    discount = values.get("discount_pct", proforma.discount_pct)
    discount = (
        Decimal("0")
        if discount in (None, "")
        else _decimal(discount, "discount %", CENT, positive=False)
    )
    if discount >= 100:
        raise SalesError("The discount must be below 100%.")
    bank = values.get("bank_account", proforma.bank_account)
    if bank is not None and (
        not isinstance(bank, CompanyAccount) or not bank.is_active or bank.kind not in BANK_KINDS
    ):
        raise SalesError("Choose one of the company's active bank accounts for the payment.")
    return {
        "customer_po": text("customer_po", 50),
        "payment_terms": text("payment_terms", 200),
        "delivery_lead_time": text("delivery_lead_time", 100),
        "incoterm": incoterm,
        "port_of_loading": text("port_of_loading", 100),
        "port_of_destination": text("port_of_destination", 100),
        "notes": text("notes", 5000),
        "advance_pct": advance,
        "discount_pct": discount,
        "bank_account": bank,
    }


def _fill(proforma: ProformaInvoice, checked: list[dict]) -> None:
    """Replace the draft's lines and work out its figures: discount, then taxes at the rates
    of its date, as on quotations."""
    proforma.lines.all().delete()
    subtotal = tax_total = discount_total = Decimal("0")
    for n, line in enumerate(checked, start=1):
        amount = (line["quantity"] * line["unit_price"]).quantize(CENT, ROUND_HALF_UP)
        discount = (amount * proforma.discount_pct / 100).quantize(CENT, ROUND_HALF_UP)
        net = amount - discount
        tax = Decimal("0")
        if line["tax_code"] is not None:
            tax = taxes.calculate(line["tax_code"], net, proforma.issue_date).tax
        ProformaLine.objects.create(
            proforma=proforma,
            line_no=n,
            amount=amount,
            discount=discount,
            tax_amount=tax,
            total=net + tax,
            **line,
        )
        subtotal += net
        discount_total += discount
        tax_total += tax
    proforma.discount_total = discount_total
    proforma.subtotal = subtotal
    proforma.tax_total = tax_total
    proforma.total_amount = subtotal + tax_total
    lookup = currencies.RateLookup(
        proforma.currency.code,
        proforma.issue_date,
        proforma.exchange_rate,
        proforma.rate_date,
        None,
    )
    proforma.total_lkr = currencies.to_lkr(proforma.total_amount, lookup)
    proforma.save()


# --- Making, changing, issuing, cancelling ----------------------------------------------


def create(user: User, quotation: Quotation) -> ProformaInvoice:
    """A draft proforma from an accepted quotation, with all its lines at their quantities."""
    if not can_enter(user):
        raise SalesError("You cannot make proformas.")
    if not visible_quotations(user).filter(pk=quotation.pk).exists():
        raise SalesError("You cannot see this quotation.")
    if quotation.status != Quotation.Status.ACCEPTED:
        raise SalesError(
            "A proforma is made from an accepted quotation: mark the quotation won first."
        )
    today = timezone.localdate()
    try:
        lookup = currencies.rate_on(quotation.currency, today)
    except MastersError as error:
        raise SalesError(str(error)) from None
    with audit_context("proforma_created"), transaction.atomic():
        try:
            number = allocate("proforma", division=quotation.division, on_date=today)
        except NumberSeriesError as error:
            raise SalesError(str(error)) from None
        contact = quotation.contact if quotation.contact and quotation.contact.is_active else None
        customer = quotation.customer
        proforma = ProformaInvoice.objects.create(
            number=number,
            quotation=quotation,
            customer=customer,
            contact=contact,
            division=quotation.division,
            issue_date=today,
            currency=quotation.currency,
            exchange_rate=lookup.rate,
            rate_date=lookup.rate_date,
            payment_terms=quotation.payment_terms,
            delivery_lead_time=quotation.delivery_lead_time,
            incoterm=quotation.incoterm,
            port_of_destination=customer.port_of_destination if customer.is_export else "",
            notes=quotation.notes,
            discount_pct=quotation.discount_pct,
            created_by=user,
        )
        checked = [
            _check_line(n, LineInput(line, line.quantity), quotation)
            for n, line in enumerate(
                quotation.lines.prefetch_related("breaks").select_related("tax_code"), start=1
            )
        ]
        _fill(proforma, checked)
        currencies.mark_rate_used(lookup)
        customers.mark_used(customer)
        return proforma


def save(user: User, proforma: ProformaInvoice, *, lines: list[LineInput], **values):
    """Change a draft: its terms, export details, bank account, advance %, discount, and its
    lines (quantities from the quotation's lines, with their packing)."""
    with audit_context("proforma_changed"), transaction.atomic():
        proforma = ProformaInvoice.objects.select_for_update().get(pk=proforma.pk)
        if not can_edit(user, proforma):
            raise SalesError("Only the person who made a draft proforma changes it.")
        if not lines:
            raise SalesError("A proforma needs at least one line.")
        quotation = proforma.quotation
        checked = [_check_line(n, line, quotation) for n, line in enumerate(lines, start=1)]
        used = [line["quotation_line"].pk for line in checked]
        if len(set(used)) != len(used):
            raise SalesError("Each line of the quotation can appear once.")
        for key, value in _header(values, proforma).items():
            setattr(proforma, key, value)
        _fill(proforma, checked)
        return proforma


def issue(user: User, proforma: ProformaInvoice) -> ProformaInvoice:
    with audit_context("proforma_issued"), transaction.atomic():
        proforma = ProformaInvoice.objects.select_for_update().get(pk=proforma.pk)
        if not can_edit(user, proforma):
            raise SalesError("Only the person who made a draft proforma issues it.")
        if not proforma.lines.exists():
            raise SalesError("A proforma needs at least one line.")
        proforma.status = P.ISSUED
        proforma.issued_at = timezone.now()
        proforma.save(update_fields=["status", "issued_at"])
        if proforma.bank_account_id:
            mark_used(proforma.bank_account)
        return proforma


def cancel(user: User, proforma: ProformaInvoice, reason: str) -> ProformaInvoice:
    reason = (reason or "").strip()
    if not reason:
        raise SalesError("Give a reason for cancelling the proforma.")
    with audit_context("proforma_cancelled", reason), transaction.atomic():
        proforma = ProformaInvoice.objects.select_for_update().get(pk=proforma.pk)
        if not can_cancel(user, proforma):
            raise SalesError(
                "Only an issued proforma is cancelled, by its creator or the Sales Manager."
            )
        if proforma.advances.filter(status=CustomerAdvance.Status.APPROVED).exists():
            raise SalesError(
                "An advance has been received against this proforma; it cannot be cancelled."
            )
        proforma.status = P.CANCELLED
        proforma.cancel_reason = reason[:1000]
        proforma.save(update_fields=["status", "cancel_reason"])
        return proforma


# --- Packing list -----------------------------------------------------------------------


def volume_m3(line: ProformaLine) -> Decimal | None:
    sizes = (line.carton_length_cm, line.carton_width_cm, line.carton_height_cm)
    if line.cartons is None or None in sizes:
        return None
    cm3 = line.cartons * sizes[0] * sizes[1] * sizes[2]
    return (cm3 / Decimal(1_000_000)).quantize(QTY, ROUND_HALF_UP)


def packing_totals(proforma: ProformaInvoice) -> dict:
    lines = list(proforma.lines.all())

    def total(values):
        known = [v for v in values if v is not None]
        return sum(known, Decimal("0")) if known else None

    return {
        "cartons": sum((line.cartons or 0) for line in lines) or None,
        "net_weight_kg": total(line.net_weight_kg for line in lines),
        "gross_weight_kg": total(line.gross_weight_kg for line in lines),
        "volume_m3": total(volume_m3(line) for line in lines),
    }


def has_packing(proforma: ProformaInvoice) -> bool:
    return proforma.lines.exclude(cartons__isnull=True).exists()
