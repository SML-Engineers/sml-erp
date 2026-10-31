"""Quotations: entry (backlog P15-03, spec 5.1, 5.5).

- Sales Executives (Sales: Enter) make quotations for the production divisions they work in.
  A draft is changed only by the person who made it.
- Who sees which quotations: a Sales Executive sees their own; roles that approve or only
  look (Sales Manager, Director, Accountant) see every quotation of their divisions.
- The number QL{YY}{MM}{DD}{XX} is given on first save, inside the saving transaction
  (rule 10). The currency's exchange rate of the quotation date is kept on the quotation, so
  later rate changes never alter it (rule 11).
- Money is Decimal throughout (rule 1): each line's amount is quantity × unit price, rounded
  half-up to the cent; its taxes come from its tax code at the rates of the quotation date.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode
from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.core.numbering import allocate
from apps.masters import currencies, customers
from apps.masters.models import Currency, Customer, CustomerContact
from apps.masters.services import MastersError

from .models import Quotation, QuotationFile, QuotationLine, QuotationQtyBreak

CENT = Decimal("0.01")
QTY = Decimal("0.001")
MAX_LINES = 200
MAX_BREAKS = 10
DEFAULT_VALIDITY_DAYS = 7
MAX_FILES = 30
MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_TYPES = {  # what the file really is, read from its first bytes
    b"%PDF-": ("application/pdf", ".pdf"),
    b"\xff\xd8\xff": ("image/jpeg", ".jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", ".png"),
}


class SalesError(Exception):
    pass


@dataclass
class BreakInput:
    quantity: object
    unit_price: object


@dataclass
class LineInput:
    description: str
    quantity: object
    unit_price: object
    drawing_no: str = ""
    drawing_rev: str = ""
    unit: str = "pcs"
    min_order_qty: object = None
    tax_code: TaxCode | None = None
    breaks: list[BreakInput] = field(default_factory=list)
    is_tooling: bool = False
    # The saved line this one is (from the quotation as loaded); None for a new line. Kept
    # lines keep their costing (P15-04) and their drawings follow them when renumbered.
    id: int | None = None


# --- Who may do what --------------------------------------------------------------------


def can_enter(user: User) -> bool:
    return effective_access(user).has("sales", "enter")


def sees_all(user: User) -> bool:
    """Approvers and those who only look see everyone's quotations; a Sales Executive
    (Enter without Approve) sees their own."""
    access = effective_access(user)
    return access.has("sales", "approve") or not access.has("sales", "enter")


def visible(user: User) -> QuerySet[Quotation]:
    access = effective_access(user)
    if not access.has("sales", "view"):
        return Quotation.objects.none()
    rows = Quotation.objects.filter(division__in=division_scope(user))
    return rows if sees_all(user) else rows.filter(created_by=user)


def can_edit(user: User, quotation: Quotation) -> bool:
    return (
        quotation.status == Quotation.Status.DRAFT
        and quotation.created_by_id == user.pk
        and can_enter(user)
    )


# --- Checking what was entered ----------------------------------------------------------


def _decimal(value, what: str, step: Decimal, *, positive: bool) -> Decimal:
    if isinstance(value, float):
        raise SalesError(f"The {what} must be an exact number.")
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise SalesError(f"The {what} must be a number.") from None
    if not number.is_finite():
        raise SalesError(f"The {what} must be a number.")
    if number != number.quantize(step):
        places = -step.as_tuple().exponent
        raise SalesError(f"The {what} can have at most {places} decimal places.")
    if positive and number <= 0:
        raise SalesError(f"The {what} must be more than 0.")
    if not positive and number < 0:
        raise SalesError(f"The {what} cannot be negative.")
    if number >= Decimal("1e15"):
        raise SalesError(f"The {what} is too large.")
    return number.quantize(step)


def _check_line(n: int, line: LineInput) -> dict:
    where = f"Line {n}: "
    description = (line.description or "").strip()
    if not description:
        raise SalesError(where + "the description is required.")
    try:
        quantity = _decimal(line.quantity, "quantity", QTY, positive=True)
        unit_price = _decimal(line.unit_price, "unit price", CENT, positive=False)
        moq = (
            None
            if line.min_order_qty in (None, "")
            else _decimal(line.min_order_qty, "minimum order quantity", QTY, positive=True)
        )
        breaks = []
        for b in line.breaks:
            breaks.append(
                (
                    _decimal(b.quantity, "quantity break", QTY, positive=True),
                    _decimal(b.unit_price, "quantity break price", CENT, positive=False),
                )
            )
    except SalesError as error:
        raise SalesError(where + str(error)) from None
    if len(breaks) > MAX_BREAKS:
        raise SalesError(where + f"at most {MAX_BREAKS} quantity breaks.")
    if len({q for q, _ in breaks}) != len(breaks):
        raise SalesError(where + "each quantity break must be a different quantity.")
    if line.tax_code is not None and (
        not line.tax_code.is_active or line.tax_code.use == TaxCode.Use.PURCHASES
    ):
        raise SalesError(where + f"tax code {line.tax_code.code} cannot be used on sales.")
    return {
        "id": line.id,
        "description": description,
        "drawing_no": (line.drawing_no or "").strip()[:50],
        "drawing_rev": (line.drawing_rev or "").strip()[:20],
        "quantity": quantity,
        "unit": (line.unit or "pcs").strip()[:20] or "pcs",
        "min_order_qty": moq,
        "unit_price": unit_price,
        "tax_code": line.tax_code,
        "is_tooling": bool(line.is_tooling),
        "breaks": sorted(breaks),
    }


def _header(user: User, quotation: Quotation | None, values: dict) -> dict:
    customer = values.get("customer", quotation.customer if quotation else None)
    if not isinstance(customer, Customer):
        raise SalesError("Choose the customer.")
    if not customer.is_active:
        raise SalesError(f"Customer {customer.code} is inactive.")
    contact = values.get("contact", quotation.contact if quotation else None)
    if contact is not None and (
        not isinstance(contact, CustomerContact)
        or contact.customer_id != customer.pk
        or not contact.is_active
    ):
        raise SalesError("Choose one of the customer's current contacts.")
    if contact is None:
        contact = customer.contacts.filter(is_main=True, is_active=True).first()

    division = values.get("division", quotation.division if quotation else None)
    if quotation is None:
        if not isinstance(division, Division):
            raise SalesError("Choose the division.")
        if division.division_type != Division.Type.PRODUCTION or not division.is_active:
            raise SalesError("A quotation is for a production division (Workshop or Moulding).")
        if not division_scope(user).filter(pk=division.pk).exists():
            raise SalesError(f"You do not work in division {division.code}.")
    elif division is not None and division.pk != quotation.division_id:
        raise SalesError("The division of a quotation cannot change (its number shows it).")

    currency = values.get("currency") or (quotation.currency if quotation else customer.currency)
    if isinstance(currency, str):
        currency = Currency.objects.filter(code=currency.strip().upper()).first()
    if currency is None or not currency.is_active:
        raise SalesError("Choose an active currency.")

    quote_date = quotation.quote_date if quotation else timezone.localdate()
    valid_until = values.get("valid_until") or (
        quotation.valid_until if quotation else quote_date + timedelta(days=DEFAULT_VALIDITY_DAYS)
    )
    if not isinstance(valid_until, date) or valid_until < quote_date:
        raise SalesError("The quotation must be valid until its own date or later.")

    def text(name, default, limit):
        value = values.get(name, getattr(quotation, name) if quotation else default)
        return (value or "").strip()[:limit]

    incoterm = text("incoterm", customer.incoterm, 3).upper()
    if incoterm and incoterm not in Customer.Incoterm.values:
        raise SalesError("The delivery term must be an Incoterm, for example EXW or FOB.")
    terms = f"{customer.payment_terms_days} days" if customer.payment_terms_days else "On receipt"
    return {
        "customer": customer,
        "contact": contact,
        "division": division,
        "currency": currency,
        "quote_date": quote_date,
        "valid_until": valid_until,
        "enquiry_ref": text("enquiry_ref", "", 100),
        "payment_terms": text("payment_terms", terms, 200),
        "delivery_lead_time": text("delivery_lead_time", "", 100),
        "incoterm": incoterm,
        "notes": text("notes", "", 5000),
        "discount_pct": _discount(values, quotation),
    }


def _discount(values: dict, quotation: Quotation | None) -> Decimal:
    """The discount %: 0 or more, below 100, at most two decimals."""
    if "discount_pct" not in values:
        return quotation.discount_pct if quotation else Decimal("0")
    value = values["discount_pct"]
    if value in (None, ""):
        return Decimal("0")
    pct = _decimal(value, "discount %", CENT, positive=False)
    if pct >= 100:
        raise SalesError("The discount must be below 100%.")
    return pct


# --- Saving -----------------------------------------------------------------------------


def save(user: User, quotation: Quotation | None, *, lines: list[LineInput], **values) -> Quotation:
    """Create a draft quotation, or change one's header and lines. Lines sent with their id
    are kept (with their costing); lines left out are removed; lines without an id are new."""
    if not can_enter(user):
        raise SalesError("You cannot make quotations.")
    if quotation is not None and not can_edit(user, quotation):
        if quotation.created_by_id != user.pk:
            raise SalesError("Only the person who made a quotation can change it.")
        raise SalesError("Only a draft quotation can be changed.")
    if not lines:
        raise SalesError("A quotation needs at least one line.")
    if len(lines) > MAX_LINES:
        raise SalesError(f"A quotation can have at most {MAX_LINES} lines.")
    checked = [_check_line(n, line) for n, line in enumerate(lines, start=1)]
    header = _header(user, quotation, values)
    try:
        lookup = currencies.rate_on(header["currency"], header["quote_date"])
    except MastersError as error:
        raise SalesError(str(error)) from None

    event = "quotation_changed" if quotation else "quotation_created"
    with audit_context(event), transaction.atomic():
        if quotation is None:
            quotation = Quotation(created_by=user, **header)
            quotation.number = allocate("quotation", division=header["division"])
        else:
            quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
            for key, value in header.items():
                setattr(quotation, key, value)
        quotation.exchange_rate = lookup.rate
        quotation.rate_date = lookup.rate_date
        quotation.updated_at = timezone.now()
        quotation.save()

        kept, kept_no = _keep_lines(quotation, checked)

        subtotal = tax_total = discount_total = Decimal("0")
        pct = quotation.discount_pct
        for n, line in enumerate(checked, start=1):
            amount = (line["quantity"] * line["unit_price"]).quantize(CENT, ROUND_HALF_UP)
            # The discount comes off each line before its taxes (owner, 31 Oct 2026).
            discount = (amount * pct / 100).quantize(CENT, ROUND_HALF_UP)
            net = amount - discount
            tax = Decimal("0")
            if line["tax_code"] is not None:
                tax = taxes.calculate(line["tax_code"], net, quotation.quote_date).tax
            fields = {k: v for k, v in line.items() if k not in ("breaks", "id")}
            fields |= {
                "line_no": n,
                "amount": amount,
                "discount": discount,
                "tax_amount": tax,
                "total": net + tax,
            }
            row = kept.get(line["id"])
            if row is None:
                row = QuotationLine.objects.create(quotation=quotation, **fields)
            else:
                for key, value in fields.items():
                    setattr(row, key, value)
                row.save()
                row.breaks.all().delete()
            QuotationQtyBreak.objects.bulk_create(
                QuotationQtyBreak(line=row, quantity=q, unit_price=p) for q, p in line["breaks"]
            )
            subtotal += net
            discount_total += discount
            tax_total += tax
            if line["tax_code"] is not None:
                taxes.mark_used(line["tax_code"])
                for part in line["tax_code"].lines.select_related("component"):
                    taxes.mark_used(part.component)
        quotation.discount_total = discount_total
        quotation.subtotal = subtotal
        quotation.tax_total = tax_total
        quotation.total_amount = subtotal + tax_total
        quotation.total_lkr = currencies.to_lkr(quotation.total_amount, lookup)
        quotation.save(
            update_fields=["discount_total", "subtotal", "tax_total", "total_amount", "total_lkr"]
        )
        # Drawings follow their line when lines are renumbered, and the files of removed
        # lines stay, tied to the whole quotation. (Lines sent without their id are new
        # lines: files then keep their line number while that line exists.)
        moved = {kept_no[line["id"]]: n for n, line in enumerate(checked, start=1) if line["id"]}
        for record in quotation.files.filter(line_no__isnull=False):
            if kept_no:
                new_no = moved.get(record.line_no)
            else:
                new_no = record.line_no if record.line_no <= len(checked) else None
            if new_no != record.line_no:
                record.line_no = new_no
                record.save(update_fields=["line_no"])

        customers.mark_used(quotation.customer)
        currencies.mark_rate_used(lookup)
        return quotation


def _keep_lines(quotation: Quotation, checked: list[dict]) -> tuple[dict, dict]:
    """Remove the lines no longer on the quotation and keep the others, so their costing
    stays (P15-04). Returns the kept lines and their old numbers, both by id."""
    existing = {row.id: row for row in quotation.lines.all()}
    ids = [line["id"] for line in checked if line["id"] is not None]
    if len(set(ids)) != len(ids):
        raise SalesError("The same line was sent twice. Reload the page and try again.")
    for n, line in enumerate(checked, start=1):
        if line["id"] is not None and line["id"] not in existing:
            raise SalesError(f"Line {n} is not part of this quotation. Reload the page.")
    old_no = {i: existing[i].line_no for i in ids}
    quotation.lines.exclude(id__in=ids).delete()
    # Out of the way first, so lines can swap numbers without clashing.
    quotation.lines.filter(id__in=ids).update(line_no=F("line_no") + 1000)
    return {row.id: row for row in quotation.lines.filter(id__in=ids)}, old_no


# --- Files ------------------------------------------------------------------------------


def _kind(head: bytes):
    for magic, kind in FILE_TYPES.items():
        if head.startswith(magic):
            return kind
    return None


def add_file(user: User, quotation: Quotation, uploaded, line_no: int | None = None):
    """Attach a drawing or other file: PDF, JPG or PNG (checked from the file itself), at
    most 20 MB, to a line of the draft or to the whole quotation. Returns (file, warnings)."""
    with audit_context("quotation_file_added"), transaction.atomic():
        quotation = Quotation.objects.select_for_update().get(pk=quotation.pk)
        if not can_edit(user, quotation):
            raise SalesError("Files are added to a draft, by the person who made it.")
        if line_no is not None and not quotation.lines.filter(line_no=line_no).exists():
            raise SalesError(f"The quotation has no line {line_no}.")
        if quotation.files.count() >= MAX_FILES:
            raise SalesError(f"A quotation can have at most {MAX_FILES} files.")
        if uploaded.size > MAX_FILE_BYTES:
            raise SalesError("The file is larger than 20 MB.")
        content = uploaded.read()
        kind = _kind(content[:8])
        if kind is None:
            raise SalesError("Only PDF, JPG and PNG files can be attached.")
        content_type, extension = kind
        digest = hashlib.sha256(content).hexdigest()
        warnings = [
            f"This file is already attached to quotation {label}."
            for label in sorted(
                {
                    f.quotation.label
                    for f in QuotationFile.objects.filter(sha256=digest)
                    .exclude(quotation=quotation)
                    .select_related("quotation")
                }
            )
        ]
        name = (uploaded.name or f"drawing{extension}").replace("/", "_").replace("\\", "_")
        uploaded.seek(0)
        record = QuotationFile(
            quotation=quotation,
            line_no=line_no,
            file_name=name[-200:],
            content_type=content_type,
            size=len(content),
            sha256=digest,
            uploaded_by=user,
        )
        record.file.save(f"{quotation.number}-{digest[:12]}{extension}", uploaded, save=False)
        record.save()
        return record, warnings


def remove_file(user: User, record: QuotationFile) -> None:
    with audit_context("quotation_file_removed"), transaction.atomic():
        quotation = Quotation.objects.select_for_update().get(pk=record.quotation_id)
        if not can_edit(user, quotation):
            raise SalesError("Files are removed from a draft, by the person who made it.")
        record.delete()


def search(queryset: QuerySet[Quotation], text: str) -> QuerySet[Quotation]:
    text = (text or "").strip()
    if not text:
        return queryset
    return queryset.filter(
        Q(number__icontains=text)
        | Q(customer__name__icontains=text)
        | Q(customer__code__iexact=text)
        | Q(enquiry_ref__icontains=text)
        | Q(lines__description__icontains=text)
        | Q(lines__drawing_no__icontains=text)
    ).distinct()
