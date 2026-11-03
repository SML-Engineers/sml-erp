"""Customers and their contacts (backlog P15-01, spec 5.4, 5.5).

- Sales Executives (Sales: Enter) add customers and keep their details and contacts; the
  Sales Manager and Director (Sales: Approve) also deactivate and reactivate them.
- Only the Accountant and the Director ("set_credit_terms") change a customer's credit limit
  and payment terms (owner, 3 Nov 2026), so nobody lifts a credit hold (P2-08) by changing
  them; a new customer starts with 30 days and no limit.
- A customer with documents keeps its code and is never deleted (rule 9, database guard).
- A name or VAT number already used by another customer is a warning the user confirms.
- Export and import in one Excel layout; an import is checked first and is all or nothing.
"""

import io
import re
import zipfile
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.core.numbering import allocate

from . import excel
from .models import Currency, Customer, CustomerContact
from .services import MastersError

TEXT_FIELDS = (
    "name",
    "billing_address",
    "delivery_address",
    "phone",
    "email",
    "vat_no",
    "tin",
    "country",
    "port_of_destination",
    "notes",
)
CONTACT_FIELDS = ("name", "position", "phone", "email")
TIN = re.compile(r"^\d{9}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NeedsConfirmation(MastersError):
    """Saving would create a likely duplicate; the user must confirm."""

    def __init__(self, warnings: list[str]):
        super().__init__(" ".join(warnings))
        self.warnings = warnings


def can_enter(user: User) -> bool:
    return effective_access(user).has("sales", "enter")


TERMS = ("credit_limit", "payment_terms_days")
DEFAULT_TERMS = {"credit_limit": None, "payment_terms_days": 30}
TERMS_REFUSED = (
    "Only the Accountant or the Director changes a customer's credit limit and payment terms."
)


def can_set_terms(user: User) -> bool:
    return effective_access(user).can("set_credit_terms")


def can_deactivate(user: User) -> bool:
    return effective_access(user).has("sales", "approve")


# --- Checks -----------------------------------------------------------------------------


def _check_details(values: dict) -> dict:
    cleaned = {}
    for field in TEXT_FIELDS:
        if field in values:
            cleaned[field] = (values[field] or "").strip()
    if "name" in cleaned and not cleaned["name"]:
        raise MastersError("The customer name is required.")
    if cleaned.get("tin") and not TIN.match(cleaned["tin"]):
        raise MastersError("The TIN must be nine digits.")
    if cleaned.get("email") and not EMAIL.match(cleaned["email"]):
        raise MastersError("The email address is not valid.")
    if "payment_terms_days" in values:
        days = values["payment_terms_days"]
        if not isinstance(days, int) or isinstance(days, bool) or not 0 <= days <= 365:
            raise MastersError("Payment terms must be 0 to 365 days (0 = due on receipt).")
        cleaned["payment_terms_days"] = days
    if "currency" in values:
        currency = Currency.objects.filter(code=(values["currency"] or "").upper()).first()
        if currency is None or not currency.is_active:
            raise MastersError("Choose an active currency.")
        cleaned["currency"] = currency
    if "credit_limit" in values:
        cleaned["credit_limit"] = _money(values["credit_limit"])
    if "is_export" in values:
        cleaned["is_export"] = bool(values["is_export"])
    if "incoterm" in values:
        term = (values["incoterm"] or "").strip().upper()
        if term and term not in Customer.Incoterm.values:
            raise MastersError(
                "The delivery term must be an Incoterm: " + ", ".join(Customer.Incoterm.values)
            )
        cleaned["incoterm"] = term
    return cleaned


def _money(value) -> Decimal | None:
    """A credit limit in the customer's currency: blank for none, otherwise 0 or more with
    at most two decimals (rule 1: never a float)."""
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise MastersError("The credit limit must be an amount, for example 500000.00.") from None
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal("0.01")):
        raise MastersError("The credit limit must be 0 or more, with at most two decimals.")
    if amount >= Decimal("1e16"):
        raise MastersError("The credit limit is too large.")
    return amount.quantize(Decimal("0.01"))


def _check_export(customer: Customer) -> None:
    if customer.is_export and not customer.country:
        raise MastersError("Give the country of an export customer.")


def duplicate_warnings(values: dict, exclude_pk: int | None = None) -> list[str]:
    warnings = []
    others = Customer.objects.exclude(pk=exclude_pk) if exclude_pk else Customer.objects.all()
    vat = (values.get("vat_no") or "").strip()
    if vat:
        for other in others.filter(vat_no__iexact=vat)[:3]:
            warnings.append(f"VAT number {vat} is already used by {other.code} {other.name}.")
    name = (values.get("name") or "").strip()
    if name:
        for other in others.filter(name__iexact=name)[:3]:
            warnings.append(f"There is already a customer called {other.name} ({other.code}).")
    return warnings


# --- Customers --------------------------------------------------------------------------


def create_customer(user: User, values: dict, *, confirmed: bool = False) -> Customer:
    if not can_enter(user):
        raise MastersError("You cannot add customers.")
    cleaned = _check_details(values)
    if not cleaned.get("name"):
        raise MastersError("The customer name is required.")
    if not can_set_terms(user) and any(
        key in cleaned and cleaned[key] != DEFAULT_TERMS[key] for key in TERMS
    ):
        raise MastersError(TERMS_REFUSED)
    warnings = duplicate_warnings(cleaned)
    if warnings and not confirmed:
        raise NeedsConfirmation(warnings)
    with audit_context("customer_created", "; ".join(warnings)), transaction.atomic():
        cleaned.setdefault("currency", Currency.objects.get(is_base=True))
        customer = Customer(created_by=user, **cleaned)
        _check_export(customer)
        customer.code = allocate("customer")
        customer.save()
        return customer


def update_customer(
    user: User, customer: Customer, values: dict, *, reason: str = "", confirmed: bool = False
) -> Customer:
    """Change a customer's details (Sales: Enter). Deactivating is set_active()."""
    if not can_enter(user):
        raise MastersError("You cannot change customers.")
    with transaction.atomic():
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
        cleaned = _check_details(values)
        if not can_set_terms(user) and any(
            key in cleaned and cleaned[key] != getattr(customer, key) for key in TERMS
        ):
            raise MastersError(TERMS_REFUSED)
        check = {k: cleaned[k] for k in ("vat_no", "name") if k in cleaned}
        new_values = {
            k: v for k, v in check.items() if (getattr(customer, k) or "").lower() != v.lower()
        }
        warnings = duplicate_warnings(new_values, exclude_pk=customer.pk)
        if warnings and not confirmed:
            raise NeedsConfirmation(warnings)
        for key, value in cleaned.items():
            setattr(customer, key, value)
        _check_export(customer)
        note = "; ".join(filter(None, [reason, *warnings]))
        with audit_context("customer_changed", note):
            customer.save()
        return customer


def set_credit_terms(
    user: User, customer: Customer, *, credit_limit, payment_terms_days, reason: str
) -> Customer:
    """The Accountant or the Director changes the credit limit (empty: no limit) and the
    payment terms, with a reason (both kept in the audit log)."""
    if not can_set_terms(user):
        raise MastersError(TERMS_REFUSED)
    reason = (reason or "").strip()
    if not reason:
        raise MastersError("Give a reason for changing the credit terms.")
    cleaned = _check_details(
        {"credit_limit": credit_limit, "payment_terms_days": payment_terms_days}
    )
    with audit_context("customer_credit_terms_changed", reason), transaction.atomic():
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
        for key, value in cleaned.items():
            setattr(customer, key, value)
        customer.save(update_fields=list(cleaned))
        return customer


def set_active(user: User, customer: Customer, active: bool, *, reason: str = "") -> Customer:
    """Deactivate or reactivate a customer: the Sales Manager or Director (Sales: Approve),
    with a reason for deactivating. A deactivated customer keeps its history and code."""
    if not can_deactivate(user):
        raise MastersError(
            "Only the Sales Manager or the Director can deactivate or reactivate customers."
        )
    if not active and not (reason or "").strip():
        raise MastersError("Give a reason for deactivating the customer.")
    with transaction.atomic():
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
        if customer.is_active == active:
            return customer
        customer.is_active = active
        event = "customer_reactivated" if active else "customer_deactivated"
        with audit_context(event, reason):
            customer.save(update_fields=["is_active"])
        return customer


def mark_used(customer: Customer) -> None:
    """Called when a document first uses the customer: from then on its code is fixed and
    it can only be deactivated (quotations, P15-03)."""
    now = timezone.now()
    Customer.objects.filter(pk=customer.pk, first_used_at__isnull=True).update(first_used_at=now)


def search(queryset, text: str):
    text = (text or "").strip()
    if not text:
        return queryset
    return queryset.filter(
        Q(name__icontains=text)
        | Q(code__iexact=text)
        | Q(vat_no__icontains=text)
        | Q(contacts__name__icontains=text, contacts__is_active=True)
    ).distinct()


# --- Contacts ---------------------------------------------------------------------------


def _check_contact(values: dict) -> dict:
    cleaned = {}
    for field in CONTACT_FIELDS:
        if field in values:
            cleaned[field] = (values[field] or "").strip()
    if "name" in cleaned and not cleaned["name"]:
        raise MastersError("The contact's name is required.")
    if cleaned.get("email") and not EMAIL.match(cleaned["email"]):
        raise MastersError("The contact's email address is not valid.")
    return cleaned


def _make_main(contact: CustomerContact) -> None:
    CustomerContact.objects.filter(customer=contact.customer, is_main=True).exclude(
        pk=contact.pk
    ).update(is_main=False)


def add_contact(user: User, customer: Customer, values: dict) -> CustomerContact:
    if not can_enter(user):
        raise MastersError("You cannot change customers.")
    cleaned = _check_contact(values)
    if not cleaned.get("name"):
        raise MastersError("The contact's name is required.")
    with audit_context("customer_contact_added"), transaction.atomic():
        customer = Customer.objects.select_for_update().get(pk=customer.pk)
        main = bool(values.get("is_main")) or not customer.contacts.filter(is_active=True).exists()
        if main:
            CustomerContact.objects.filter(customer=customer, is_main=True).update(is_main=False)
        return CustomerContact.objects.create(
            customer=customer, created_by=user, is_main=main, **cleaned
        )


def update_contact(user: User, contact: CustomerContact, values: dict) -> CustomerContact:
    if not can_enter(user):
        raise MastersError("You cannot change customers.")
    cleaned = _check_contact(values)
    with transaction.atomic():
        contact = CustomerContact.objects.select_for_update().get(pk=contact.pk)
        for key, value in cleaned.items():
            setattr(contact, key, value)
        if "is_active" in values:
            contact.is_active = bool(values["is_active"])
            if not contact.is_active:
                contact.is_main = False
        if values.get("is_main"):
            if not contact.is_active:
                raise MastersError("A contact who has left cannot be the main contact.")
            contact.is_main = True
        with audit_context("customer_contact_changed"):
            if contact.is_main:
                _make_main(contact)
            contact.save()
        return contact


# --- Excel export and import ------------------------------------------------------------

COLUMNS = [
    "Code",
    "Name",
    "Billing address",
    "Delivery address",
    "Phone",
    "Email",
    "VAT no.",
    "TIN",
    "Currency",
    "Payment terms (days)",
    "Credit limit",
    "Export",
    "Country",
    "Delivery term",
    "Port of destination",
    "Notes",
    "Main contact",
    "Contact position",
    "Contact phone",
    "Contact email",
    "Active",
]
SHEET = "Customers"
TEXT_COLUMNS = {
    "Name": "name",
    "Billing address": "billing_address",
    "Delivery address": "delivery_address",
    "Phone": "phone",
    "Email": "email",
    "VAT no.": "vat_no",
    "TIN": "tin",
    "Country": "country",
    "Port of destination": "port_of_destination",
    "Notes": "notes",
}


def export_workbook(rows) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    lines = []
    for c in rows:
        main = next((x for x in c.contacts.all() if x.is_main), None)
        lines.append(
            [
                c.code,
                c.name,
                c.billing_address,
                c.delivery_address,
                c.phone,
                c.email,
                c.vat_no,
                c.tin,
                c.currency.code,
                c.payment_terms_days,
                None if c.credit_limit is None else c.credit_limit,
                "Yes" if c.is_export else "No",
                c.country,
                c.incoterm,
                c.port_of_destination,
                c.notes,
                main.name if main else "",
                main.position if main else "",
                main.phone if main else "",
                main.email if main else "",
                "Yes" if c.is_active else "No",
            ]
        )
    excel._sheet(workbook, SHEET, COLUMNS, lines)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _terms(value) -> int:
    text = excel._text(value)
    if text == "":
        return 30
    if not text.isdigit():
        raise MastersError("Payment terms must be a whole number of days.")
    return int(text)


def _import_row(row: dict, *, user: User, reason: str) -> str:
    values = {field: excel._text(row.get(column)) for column, field in TEXT_COLUMNS.items()}
    values["currency"] = excel._text(row.get("Currency")) or Currency.objects.get(is_base=True).code
    values["payment_terms_days"] = _terms(row.get("Payment terms (days)"))
    values["credit_limit"] = excel._number(row.get("Credit limit"))
    values["is_export"] = excel._text(row.get("Export")).lower() in ("yes", "y", "true", "1")
    values["incoterm"] = excel._text(row.get("Delivery term")).split(" ")[0]
    active = excel._yes_no(row.get("Active"))
    code = excel._text(row.get("Code")).upper()

    if code:
        customer = Customer.objects.filter(code=code).first()
        if customer is None:
            raise MastersError(f"There is no customer {code} (leave Code empty for a new one).")
        customer = update_customer(user, customer, values, reason=reason, confirmed=False)
        if active != customer.is_active:
            customer = set_active(user, customer, active, reason=reason)
        outcome = "updated"
    else:
        if not active:
            raise MastersError("A new customer cannot be imported as inactive.")
        customer = create_customer(user, values, confirmed=False)
        outcome = "created"

    contact = {
        "name": excel._text(row.get("Main contact")),
        "position": excel._text(row.get("Contact position")),
        "phone": excel._text(row.get("Contact phone")),
        "email": excel._text(row.get("Contact email")),
    }
    if contact["name"]:
        main = customer.contacts.filter(is_main=True).first()
        if main is None:
            add_contact(user, customer, {**contact, "is_main": True})
        elif any(getattr(main, k) != v for k, v in contact.items()):
            update_contact(user, main, contact)
    return outcome


def import_workbook(content: bytes, *, user: User, reason: str, dry_run: bool) -> dict:
    """Apply a workbook of customers. Returns counts; raises excel.ImportRefused listing
    every refused row, in which case nothing is saved."""
    if not can_enter(user):
        raise excel.ImportRefused(["You cannot add or change customers."])
    if not (reason or "").strip():
        raise excel.ImportRefused(["Give a reason for the import."])
    if len(content) > excel.MAX_BYTES:
        raise excel.ImportRefused(["The file must be 5 MB or smaller."])
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise excel.ImportRefused(["The file is not an Excel workbook (.xlsx)."]) from None
    rows = excel._rows(workbook, SHEET, COLUMNS)
    if not rows:
        raise excel.ImportRefused([f"The workbook has no rows on a sheet called {SHEET}."])

    counts = {"created": 0, "updated": 0}
    errors = []
    with transaction.atomic():
        for number, row in rows:
            try:
                with transaction.atomic():
                    counts[_import_row(row, user=user, reason=reason)] += 1
            except NeedsConfirmation as warning:
                errors.append(
                    f"Row {number}: {warning} Put the existing code in the Code column to "
                    "update that customer instead."
                )
            except MastersError as error:
                errors.append(f"Row {number}: {error}")
        if errors or dry_run:
            transaction.set_rollback(True)
    if errors:
        raise excel.ImportRefused(errors)
    return counts
