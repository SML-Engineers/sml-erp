"""Payment voucher rules (spec 4). P1-01: voucher types, kept by the Admin."""

import re

from django.db import transaction

from apps.core.access import has_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.masters.models import Supplier
from apps.masters.services import is_in_use

from .models import TYPE_CODE_REGEX, VoucherType

CODE = re.compile(TYPE_CODE_REGEX)


class VoucherError(Exception):
    pass


def _admin(user: User) -> None:
    if not has_access(user, "settings", "manage"):
        raise VoucherError("Only the Admin can change voucher types.")


def _code(value) -> str:
    code = (value or "").strip().upper()
    if not CODE.match(code):
        raise VoucherError(
            "The type code must be 2 to 10 letters or digits, starting with a letter, e.g. CHQ."
        )
    return code


def _apply(vt: VoucherType, values: dict) -> None:
    if "name" in values:
        name = " ".join((values["name"] or "").split())
        if not name:
            raise VoucherError("The type name is required.")
        if len(name) > 50:
            raise VoucherError("The type name can have at most 50 characters.")
        clash = VoucherType.objects.filter(name__iexact=name).exclude(pk=vt.pk)
        if clash.exists():
            raise VoucherError(f"There is already a voucher type called {name}.")
        vt.name = name
    if "payment_method" in values:
        if values["payment_method"] not in VoucherType.Method.values:
            raise VoucherError("Choose how this type is paid.")
        vt.payment_method = values["payment_method"]
    for flag in ("needs_payee", "is_advance"):
        if flag in values:
            setattr(vt, flag, bool(values[flag]))
    if "payee_category" in values:
        category = values["payee_category"] or ""
        if category and category not in Supplier.Category.values:
            raise VoucherError("Choose a payee category, or none for any payee.")
        vt.payee_category = category
    if "notes" in values:
        vt.notes = (values["notes"] or "").strip()[:300]
    if "sort_order" in values:
        try:
            vt.sort_order = max(0, min(int(values["sort_order"]), 32767))
        except (TypeError, ValueError):
            raise VoucherError("The order must be a whole number.") from None
    internal = vt.payment_method == VoucherType.Method.INTERNAL
    if internal and vt.needs_payee:
        vt.needs_payee = False  # money moves between the company's own accounts
    if not vt.needs_payee:
        if not internal:
            raise VoucherError("Only transfers between the company's own accounts have no payee.")
        if vt.payee_category or vt.is_advance:
            raise VoucherError("A type with no payee cannot limit payees or be an advance.")


def create_type(user: User, *, code, name, payment_method, reason="", **values) -> VoucherType:
    _admin(user)
    vt = VoucherType(code=_code(code), payment_method="")
    with audit_context("voucher_type_created", reason), transaction.atomic():
        if VoucherType.objects.filter(code=vt.code).exists():
            raise VoucherError(f"The type code {vt.code} is already used.")
        _apply(vt, {"name": name, "payment_method": payment_method, **values})
        vt.save()
        return vt


def update_type(user: User, vt: VoucherType, values: dict, reason: str = "") -> VoucherType:
    _admin(user)
    with transaction.atomic():
        vt = VoucherType.objects.select_for_update().get(pk=vt.pk)
        used = is_in_use(vt)
        event = "voucher_type_changed"
        if "code" in values:
            code = _code(values["code"])
            if code != vt.code:
                if used:
                    raise VoucherError(f"{vt.code} has been used on vouchers; its code is fixed.")
                if VoucherType.objects.filter(code=code).exclude(pk=vt.pk).exists():
                    raise VoucherError(f"The type code {code} is already used.")
                vt.code = code
        if used and any(
            key in values and values[key] != getattr(vt, key)
            for key in ("payment_method", "needs_payee", "is_advance")
        ):
            raise VoucherError(
                f"{vt.code} has been used on vouchers, so how it is paid cannot change. "
                "Add a new type and switch this one off."
            )
        _apply(vt, values)
        if "is_active" in values and bool(values["is_active"]) != vt.is_active:
            if not values["is_active"]:
                if not (reason or "").strip():
                    raise VoucherError("Give a reason for switching off the voucher type.")
                if not VoucherType.objects.filter(is_active=True).exclude(pk=vt.pk).exists():
                    raise VoucherError("At least one voucher type must stay in use.")
                event = "voucher_type_switched_off"
            else:
                event = "voucher_type_switched_on"
            vt.is_active = bool(values["is_active"])
        with audit_context(event, reason):
            vt.save()
        return vt


def delete_type(user: User, vt: VoucherType, reason: str) -> None:
    """Remove a type added by mistake; a type used on vouchers is switched off instead."""
    _admin(user)
    if not (reason or "").strip():
        raise VoucherError("Give a reason for deleting the voucher type.")
    with audit_context("voucher_type_deleted", reason), transaction.atomic():
        vt = VoucherType.objects.select_for_update().get(pk=vt.pk)
        if is_in_use(vt):
            raise VoucherError(f"{vt.code} has been used on vouchers; switch it off instead.")
        if not VoucherType.objects.filter(is_active=True).exclude(pk=vt.pk).exists():
            raise VoucherError("At least one voucher type must stay in use.")
        vt.delete()
