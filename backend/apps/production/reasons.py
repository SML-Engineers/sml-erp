"""Reject and downtime reasons, and the production settings (backlog P3-02).

- **Reasons** per division and kind (reject or downtime); a downtime reason is planned (not
  lost time in OEE: planned maintenance, nothing planned) or unplanned. Starting lists are
  loaded for IM and WS (spec 7.4); the Admin renames, adds, orders and deactivates them. A
  reason's code is fixed once a shift report uses it, and a used reason is deactivated,
  never deleted (rule 9, database).
- **Settings** (owner, 7 Nov 2026: changeable later in a control panel by an authorised
  person): the entry grace period after a shift (4 hours), the reject % alert (5%), the cost
  overrun % alert (10%) and the minimum margin (blank: the order's quotation). Dated (rule
  11): a change takes effect from a date, today or later, and the values in force earlier
  stay for earlier shifts and orders; a setting in force never changes (database). Kept
  by those who manage Settings (the Admin), with a reason; every change is in the audit
  log.
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.masters.models import CODE_REGEX

from .models import ProductionSetting, ReasonCode


class ReasonError(Exception):
    pass


def can_manage(user: User) -> bool:
    return effective_access(user).has("settings", "manage")


def _check(user: User) -> None:
    if not can_manage(user):
        raise ReasonError("Only the Admin keeps the production reasons and settings.")


# --- Reasons -------------------------------------------------------------------------------------


def active(division: Division, kind: str):
    return ReasonCode.objects.filter(division=division, kind=kind, is_active=True)


def _name(values: dict) -> str:
    name = " ".join(str(values.get("name") or "").split())[:100]
    if not name:
        raise ReasonError("Give the reason a name.")
    return name


def _flags(values: dict, reason: ReasonCode | None, kind: str) -> dict:
    out = {}
    if "planned" in values or reason is None:
        planned = str(values.get("planned", False)).lower() in ("true", "1", "yes")
        if planned and kind != ReasonCode.Kind.DOWNTIME:
            raise ReasonError("Only a downtime reason can be planned.")
        out["planned"] = planned
    if "is_active" in values:
        out["is_active"] = str(values["is_active"]).lower() in ("true", "1", "yes")
    if "sort_order" in values:
        try:
            out["sort_order"] = max(0, min(int(values["sort_order"]), 9999))
        except (TypeError, ValueError):
            raise ReasonError("The order is a whole number.") from None
    return out


def _code(values: dict) -> str:
    code = re.sub(r"\s+", "-", str(values.get("code") or "").strip().upper())
    if not re.match(CODE_REGEX, code):
        raise ReasonError("The code is up to 20 capital letters, digits and dashes, e.g. FLASH.")
    return code


def add(user: User, values: dict) -> ReasonCode:
    _check(user)
    division = Division.objects.filter(code=str(values.get("division") or "").upper()).first()
    if division is None:
        raise ReasonError("Choose the division.")
    kind = str(values.get("kind") or "")
    if kind not in ReasonCode.Kind.values:
        raise ReasonError("The kind is reject or downtime.")
    code = _code(values)
    if ReasonCode.objects.filter(division=division, kind=kind, code=code).exists():
        raise ReasonError(f"{division.code} already has a {kind} reason {code}.")
    last = ReasonCode.objects.filter(division=division, kind=kind).order_by("-sort_order").first()
    fields = {"sort_order": (last.sort_order + 10) if last else 10} | _flags(values, None, kind)
    with audit_context("production_reason_added", code), transaction.atomic():
        return ReasonCode.objects.create(
            division=division, kind=kind, code=code, name=_name(values), **fields
        )


def change(user: User, reason: ReasonCode, values: dict) -> ReasonCode:
    _check(user)
    fields = _flags(values, reason, reason.kind)
    if "name" in values:
        fields["name"] = _name(values)
    if "code" in values:
        code = _code(values)
        if code != reason.code:
            if reason.first_used_at:
                raise ReasonError(f"{reason.code} has been used: its code cannot change.")
            clash = ReasonCode.objects.filter(
                division=reason.division, kind=reason.kind, code=code
            ).exclude(pk=reason.pk)
            if clash.exists():
                raise ReasonError(f"There is already a {reason.kind} reason {code}.")
            fields["code"] = code
    with audit_context("production_reason_changed", reason.code), transaction.atomic():
        for key, value in fields.items():
            setattr(reason, key, value)
        reason.save()
        return reason


def remove(user: User, reason: ReasonCode) -> None:
    _check(user)
    if reason.first_used_at:
        raise ReasonError(f"{reason.code} has been used: deactivate it instead.")
    with audit_context("production_reason_deleted", reason.code), transaction.atomic():
        reason.delete()


def row(r: ReasonCode) -> dict:
    return {
        "id": r.pk,
        "division": r.division.code,
        "kind": r.kind,
        "code": r.code,
        "name": r.name,
        "planned": r.planned,
        "is_active": r.is_active,
        "sort_order": r.sort_order,
        "in_use": r.first_used_at is not None,
    }


# --- Settings ------------------------------------------------------------------------------------


def setting_on(day: date | None = None) -> ProductionSetting:
    """The settings in force on a date (today by default)."""
    day = day or timezone.localdate()
    found = (
        ProductionSetting.objects.filter(effective_from__lte=day)
        .order_by("-effective_from")
        .first()
    )
    if found is None:
        raise ReasonError("There are no production settings in force; ask the Admin.")
    return found


def _pct(value, label: str, *, blank=False) -> Decimal | None:
    text = str(value if value is not None else "").strip().rstrip("%").strip()
    if not text:
        if blank:
            return None
        raise ReasonError(f"Give the {label}.")
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise ReasonError(f"The {label} is a number.") from None
    if not number.is_finite() or not Decimal("0") < number <= Decimal("100"):
        raise ReasonError(f"The {label} is more than 0 and at most 100.")
    if number != number.quantize(Decimal("0.01")):
        raise ReasonError(f"The {label} has at most two decimal places.")
    return number


def add_setting(user: User, values: dict) -> ProductionSetting:
    _check(user)
    today = timezone.localdate()
    try:
        day = date.fromisoformat(str(values.get("effective_from") or today.isoformat()))
    except ValueError:
        raise ReasonError("Give the date it applies from, e.g. 2026-12-01.") from None
    if day < today:
        raise ReasonError("A change applies from today or later; earlier shifts keep theirs.")
    try:
        grace = Decimal(str(values.get("grace_hours", "")).strip())
    except InvalidOperation:
        raise ReasonError("The grace period is a number of hours, e.g. 4.") from None
    if not grace.is_finite() or not 0 <= grace <= 48 or grace != grace.quantize(Decimal("0.1")):
        raise ReasonError("The grace period is 0 to 48 hours (one decimal place).")
    reason = " ".join(str(values.get("reason") or "").split())[:200]
    if not reason:
        raise ReasonError("Give the reason for the change.")
    fields = {
        "grace_hours": grace,
        "reject_alert_pct": _pct(values.get("reject_alert_pct"), "reject % alert"),
        "overrun_alert_pct": _pct(values.get("overrun_alert_pct"), "cost overrun % alert"),
        "min_margin_pct": _pct(values.get("min_margin_pct"), "minimum margin %", blank=True),
        "reason": reason,
        "created_by": user,
        "created_at": timezone.now(),
    }
    with audit_context("production_settings_changed", reason), transaction.atomic():
        # A change already entered for the same future date is replaced (not yet in force).
        setting, _ = ProductionSetting.objects.update_or_create(effective_from=day, defaults=fields)
        return setting


def setting_row(s: ProductionSetting) -> dict:
    return {
        "id": s.pk,
        "effective_from": s.effective_from,
        "grace_hours": f"{s.grace_hours}",
        "reject_alert_pct": f"{s.reject_alert_pct}",
        "overrun_alert_pct": f"{s.overrun_alert_pct}",
        "min_margin_pct": f"{s.min_margin_pct}" if s.min_margin_pct is not None else "",
        "reason": s.reason,
        "created_by": s.created_by.full_name if s.created_by_id else "",
        "in_force": s.effective_from <= timezone.localdate(),
    }
