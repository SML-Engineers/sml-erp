"""Costing rates for quotations (backlog P15-02, spec 5.1, rule 11).

Maintained by the Accountant (Accounting: Manage); seen by sales staff for costing.

- Materials priced per kg from a date (steel, resins, masterbatches).
- Per division from a date: overhead % on direct cost, default margin %, setup rate per hour.
  Machine hourly rates are kept with each machine (P0-09).
- A rate starts today or later, never in the past, so a quotation keeps the rates of its
  date. Once in force a rate cannot be changed or removed (database guard); a rate that has
  not started yet can be removed, with a reason.
"""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User

from .models import CostingRate, Material, MaterialRate
from .services import MastersError, normalise_code

MATERIAL_TEXT = ("name", "grade", "notes")


def can_manage(user: User) -> bool:
    return effective_access(user).has("accounting", "manage")


def can_view(user: User) -> bool:
    access = effective_access(user)
    return access.has("accounting", "view") or access.has("sales", "view")


def _require_manage(user: User) -> None:
    if not can_manage(user):
        raise MastersError("Only the Accountant maintains costing rates.")


def _decimal(value, what: str, *, places: int, maximum: Decimal) -> Decimal:
    """An exact amount or percentage (rule 1): never a float, at most `places` decimals."""
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise MastersError(f"The {what} must be a number.") from None
    step = Decimal(1).scaleb(-places)
    if not amount.is_finite() or amount < 0:
        raise MastersError(f"The {what} cannot be negative.")
    if amount != amount.quantize(step):
        raise MastersError(f"The {what} can have at most {places} decimal places.")
    if amount > maximum:
        raise MastersError(f"The {what} is too large.")
    return amount.quantize(step)


def _start_date(effective_from: date) -> None:
    if effective_from < timezone.localdate():
        raise MastersError(
            "A new rate cannot start in the past: quotations already made keep the rate they "
            "had. Choose today or a later date."
        )


def _require_reason(reason: str, doing: str) -> None:
    if not (reason or "").strip():
        raise MastersError(f"Give a reason for {doing}.")


# --- Materials --------------------------------------------------------------------------


def _check_material(values: dict) -> dict:
    cleaned = {}
    for field in MATERIAL_TEXT:
        if field in values:
            cleaned[field] = (values[field] or "").strip()
    if "name" in cleaned and not cleaned["name"]:
        raise MastersError("The material name is required.")
    if "kind" in values:
        if values["kind"] not in Material.Kind.values:
            raise MastersError("Choose the kind of material.")
        cleaned["kind"] = values["kind"]
    if "form" in values:
        if values["form"] not in Material.Form.values:
            raise MastersError("Choose the form of the material.")
        cleaned["form"] = values["form"]
    if "density" in values:
        density = values["density"]
        if density in (None, ""):
            cleaned["density"] = None
        else:
            cleaned["density"] = _decimal(density, "density", places=3, maximum=Decimal("999.999"))
            if cleaned["density"] == 0:
                raise MastersError("The density must be more than 0, for example 7.850 for steel.")
    return cleaned


def create_material(user: User, values: dict) -> Material:
    _require_manage(user)
    code = normalise_code(values.get("code", ""), "material")
    cleaned = _check_material(values)
    if not cleaned.get("name") or not cleaned.get("kind"):
        raise MastersError("Give the material's code, name and kind.")
    if Material.objects.filter(code=code).exists():
        raise MastersError(f"There is already a material {code}.")
    with audit_context("material_created"), transaction.atomic():
        return Material.objects.create(code=code, created_by=user, **cleaned)


def update_material(user: User, material: Material, values: dict, reason: str = "") -> Material:
    """Change a material's details or deactivate it. The code never changes."""
    _require_manage(user)
    with transaction.atomic():
        material = Material.objects.select_for_update().get(pk=material.pk)
        cleaned = _check_material(values)
        event = "material_changed"
        if "is_active" in values and bool(values["is_active"]) != material.is_active:
            if not values["is_active"]:
                _require_reason(reason, "deactivating the material")
            material.is_active = bool(values["is_active"])
            event = "material_deactivated" if not material.is_active else "material_reactivated"
        for key, value in cleaned.items():
            setattr(material, key, value)
        with audit_context(event, reason):
            material.save()
        return material


def add_material_rate(
    user: User, material: Material, *, effective_from: date, rate, reason: str = ""
) -> MaterialRate:
    _require_manage(user)
    amount = _decimal(rate, "price per kg", places=2, maximum=Decimal("9999999999999999.99"))
    _start_date(effective_from)
    if not material.is_active:
        raise MastersError(f"Material {material.code} is inactive.")
    with audit_context("material_rate_added", reason), transaction.atomic():
        if MaterialRate.objects.filter(material=material, effective_from=effective_from).exists():
            raise MastersError(
                f"Material {material.code} already has a price from {effective_from}. "
                "Remove that one first if it has not started yet."
            )
        return MaterialRate.objects.create(
            material=material,
            effective_from=effective_from,
            rate=amount,
            reason=reason or "",
            created_by=user,
        )


def remove_material_rate(user: User, rate: MaterialRate, reason: str) -> None:
    _require_manage(user)
    _require_reason(reason, "removing the price")
    if rate.effective_from <= timezone.localdate():
        raise MastersError("This price is already in force and cannot be removed. Add a new one.")
    with audit_context("material_rate_removed", reason), transaction.atomic():
        rate.delete()


def material_rate_on(material: Material, on_date: date) -> Decimal | None:
    """The price per kg in force on a date, or None if none had started."""
    return (
        material.rates.filter(effective_from__lte=on_date)
        .order_by("-effective_from")
        .values_list("rate", flat=True)
        .first()
    )


# --- Division costing rates -------------------------------------------------------------


def add_costing_rate(
    user: User,
    division: Division,
    *,
    effective_from: date,
    overhead_pct,
    margin_pct,
    setup_rate,
    reason: str = "",
) -> CostingRate:
    _require_manage(user)
    values = {
        "overhead_pct": _decimal(overhead_pct, "overhead %", places=2, maximum=Decimal("999.99")),
        "margin_pct": _decimal(margin_pct, "margin %", places=2, maximum=Decimal("999.99")),
        "setup_rate": _decimal(
            setup_rate, "setup rate", places=2, maximum=Decimal("9999999999999999.99")
        ),
    }
    _start_date(effective_from)
    with audit_context("costing_rate_added", reason), transaction.atomic():
        if CostingRate.objects.filter(division=division, effective_from=effective_from).exists():
            raise MastersError(
                f"{division.code} already has costing rates from {effective_from}. "
                "Remove those first if they have not started yet."
            )
        return CostingRate.objects.create(
            division=division,
            effective_from=effective_from,
            reason=reason or "",
            created_by=user,
            **values,
        )


def remove_costing_rate(user: User, rate: CostingRate, reason: str) -> None:
    _require_manage(user)
    _require_reason(reason, "removing the costing rates")
    if rate.effective_from <= timezone.localdate():
        raise MastersError(
            "These rates are already in force and cannot be removed. Add new ones instead."
        )
    with audit_context("costing_rate_removed", reason), transaction.atomic():
        rate.delete()


def costing_rate_on(division: Division, on_date: date) -> CostingRate | None:
    """The division's costing rates in force on a date, or None if none had started."""
    return (
        division.costing_rates.filter(effective_from__lte=on_date)
        .order_by("-effective_from")
        .first()
    )
