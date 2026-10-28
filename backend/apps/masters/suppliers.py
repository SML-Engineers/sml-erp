"""Suppliers and payees (backlog P0-13, spec 4.1).

- Clerks (Payees: Enter) add payees and keep their contact details; the Accountant (Payees:
  Manage) also deactivates them.
- Bank details can be entered or changed only with the "change bank details" action. Every
  change is audited with its old and new values and flagged to the Accountant on the
  payee's next voucher.
- A VAT number already used by another payee is a warning the user must confirm.
"""

import re

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.core.numbering import allocate

from .models import Currency, Supplier, SupplierBankAccount
from .services import MastersError

TEXT_FIELDS = (
    "name",
    "address",
    "phone",
    "email",
    "contact_person",
    "contact_phone",
    "vat_no",
    "tin",
    "notes",
)
ACCOUNT_NUMBER = re.compile(r"^[A-Z0-9][A-Z0-9 -]{3,33}$")
SWIFT = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")
TIN = re.compile(r"^\d{9}$")


class NeedsConfirmation(MastersError):
    """Saving would create a likely duplicate; the user must confirm."""

    def __init__(self, warnings: list[str]):
        super().__init__(" ".join(warnings))
        self.warnings = warnings


def _can(user: User, area_level=None, action=None) -> bool:
    access = effective_access(user)
    if action:
        return access.can(action)
    return access.has(*area_level)


def _check_details(values: dict) -> dict:
    cleaned = {}
    for field in TEXT_FIELDS:
        if field in values:
            cleaned[field] = (values[field] or "").strip()
    if "name" in cleaned and not cleaned["name"]:
        raise MastersError("The payee name is required.")
    if cleaned.get("tin") and not TIN.match(cleaned["tin"]):
        raise MastersError("The TIN must be nine digits.")
    if "category" in values:
        if values["category"] not in Supplier.Category.values:
            raise MastersError("Choose the payee category.")
        cleaned["category"] = values["category"]
    if "payment_terms_days" in values:
        days = values["payment_terms_days"]
        if not isinstance(days, int) or not 0 <= days <= 365:
            raise MastersError("Payment terms must be 0 to 365 days (0 = due on receipt).")
        cleaned["payment_terms_days"] = days
    if "currency" in values:
        currency = Currency.objects.filter(code=(values["currency"] or "").upper()).first()
        if currency is None or not currency.is_active:
            raise MastersError("Choose an active currency.")
        cleaned["currency"] = currency
    return cleaned


def duplicate_warnings(values: dict, exclude_pk: int | None = None) -> list[str]:
    warnings = []
    others = Supplier.objects.exclude(pk=exclude_pk) if exclude_pk else Supplier.objects.all()
    vat = (values.get("vat_no") or "").strip()
    if vat:
        for other in others.filter(vat_no__iexact=vat)[:3]:
            warnings.append(f"VAT number {vat} is already used by {other.code} {other.name}.")
    name = (values.get("name") or "").strip()
    if name:
        for other in others.filter(name__iexact=name)[:3]:
            warnings.append(f"There is already a payee called {other.name} ({other.code}).")
    return warnings


def create_supplier(user: User, values: dict, *, confirmed: bool = False) -> Supplier:
    if not _can(user, ("payees", "enter")):
        raise MastersError("You cannot add payees.")
    cleaned = _check_details(values)
    if not cleaned.get("name"):
        raise MastersError("The payee name is required.")
    warnings = duplicate_warnings(cleaned)
    if warnings and not confirmed:
        raise NeedsConfirmation(warnings)
    with audit_context("payee_created", "; ".join(warnings)), transaction.atomic():
        cleaned.setdefault("currency", Currency.objects.get(is_base=True))
        return Supplier.objects.create(code=allocate("payee"), created_by=user, **cleaned)


def update_supplier(
    user: User, supplier: Supplier, values: dict, *, reason: str = "", confirmed: bool = False
) -> Supplier:
    if not _can(user, ("payees", "enter")):
        raise MastersError("You cannot change payees.")
    with transaction.atomic():
        supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
        cleaned = _check_details(values)
        event = "payee_changed"
        if "is_active" in values and bool(values["is_active"]) != supplier.is_active:
            if not _can(user, ("payees", "manage")):
                raise MastersError("Only the Accountant can deactivate or reactivate payees.")
            if not values["is_active"] and not (reason or "").strip():
                raise MastersError("Give a reason for deactivating the payee.")
            supplier.is_active = bool(values["is_active"])
            event = "payee_deactivated" if not supplier.is_active else "payee_reactivated"
        check = {k: cleaned[k] for k in ("vat_no", "name") if k in cleaned}
        new_values = {
            k: v for k, v in check.items() if (getattr(supplier, k) or "").lower() != v.lower()
        }
        warnings = duplicate_warnings(new_values, exclude_pk=supplier.pk)
        if warnings and not confirmed:
            raise NeedsConfirmation(warnings)
        for key, value in cleaned.items():
            setattr(supplier, key, value)
        note = "; ".join(filter(None, [reason, *warnings]))
        with audit_context(event, note):
            supplier.save()
        return supplier


# --- Bank details -----------------------------------------------------------------------


def _require_bank_action(user: User) -> None:
    if not _can(user, action="change_bank_details"):
        raise MastersError(
            'Only someone with the "change bank details" permission (normally the '
            "Accountant) can enter or change bank details."
        )


def _check_account(values: dict) -> dict:
    cleaned = {}
    for field in ("bank_name", "branch", "account_name"):
        if field in values:
            cleaned[field] = (values[field] or "").strip()
    if "account_number" in values:
        number = (values["account_number"] or "").strip().upper()
        if not ACCOUNT_NUMBER.match(number):
            raise MastersError(
                "The account number must be 4 to 34 letters, digits, spaces or dashes."
            )
        cleaned["account_number"] = number
    if "swift_code" in values:
        swift = (values["swift_code"] or "").strip().upper()
        if swift and not SWIFT.match(swift):
            raise MastersError("The SWIFT / BIC code must be 8 or 11 characters.")
        cleaned["swift_code"] = swift
    for field, label in (("bank_name", "bank name"), ("account_name", "account name")):
        if field in cleaned and not cleaned[field]:
            raise MastersError(f"The {label} is required.")
    return cleaned


def _flag_bank_change(supplier: Supplier, user: User) -> None:
    supplier.bank_changed_at = timezone.now()
    supplier.bank_changed_by = user
    supplier.save(update_fields=["bank_changed_at", "bank_changed_by"])


def _set_default(account: SupplierBankAccount) -> None:
    SupplierBankAccount.objects.filter(supplier=account.supplier, is_default=True).exclude(
        pk=account.pk
    ).update(is_default=False)


def add_bank_account(user: User, supplier: Supplier, values: dict, reason: str = ""):
    _require_bank_action(user)
    cleaned = _check_account(values)
    for field in ("bank_name", "account_name", "account_number"):
        if not cleaned.get(field):
            raise MastersError("Give the bank name, account name and account number.")
    with audit_context("payee_bank_added", reason), transaction.atomic():
        supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
        if SupplierBankAccount.objects.filter(
            supplier=supplier, account_number=cleaned["account_number"], is_active=True
        ).exists():
            raise MastersError("This payee already has that account number.")
        make_default = (
            bool(values.get("is_default"))
            or not supplier.bank_accounts.filter(is_active=True).exists()
        )
        if make_default:
            SupplierBankAccount.objects.filter(supplier=supplier, is_default=True).update(
                is_default=False
            )
        account = SupplierBankAccount.objects.create(
            supplier=supplier, created_by=user, is_default=make_default, **cleaned
        )
        _flag_bank_change(supplier, user)
        return account


def update_bank_account(user: User, account: SupplierBankAccount, values: dict, reason: str):
    """Change an account in place: one audit row with the old and new values."""
    _require_bank_action(user)
    if not (reason or "").strip():
        raise MastersError("Give a reason for changing bank details.")
    cleaned = _check_account(values)
    with transaction.atomic():
        account = SupplierBankAccount.objects.select_for_update().get(pk=account.pk)
        changed = {k: v for k, v in cleaned.items() if getattr(account, k) != v}
        event = "payee_bank_changed"
        if "is_active" in values and bool(values["is_active"]) != account.is_active:
            changed["is_active"] = bool(values["is_active"])
            if not values["is_active"]:
                changed["is_default"] = False
        if values.get("is_default") and not account.is_default:
            changed["is_default"] = True
        if not changed:
            return account
        for key, value in changed.items():
            setattr(account, key, value)
        if account.is_default and not account.is_active:
            raise MastersError("A closed account cannot be the default.")
        with audit_context(event, reason):
            if account.is_default:
                _set_default(account)
            account.save()
        _flag_bank_change(account.supplier, user)
        return account


def acknowledge_bank_change(user: User, supplier: Supplier) -> Supplier:
    """The Accountant has seen the new bank details (called from the voucher, P1-03)."""
    if not _can(user, ("payees", "manage")):
        raise MastersError("Only the Accountant can acknowledge changed bank details.")
    with audit_context("payee_bank_change_acknowledged"), transaction.atomic():
        supplier = Supplier.objects.select_for_update().get(pk=supplier.pk)
        if supplier.bank_change_pending:
            supplier.bank_change_acknowledged_at = timezone.now()
            supplier.save(update_fields=["bank_change_acknowledged_at"])
        return supplier


def search(queryset, text: str):
    text = (text or "").strip()
    if not text:
        return queryset
    return queryset.filter(
        Q(name__icontains=text)
        | Q(code__iexact=text)
        | Q(vat_no__icontains=text)
        | Q(contact_person__icontains=text)
    )
