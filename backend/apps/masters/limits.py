"""Quotation approval limits (backlog P0-12, spec 3A.3).

The Admin proposes a division's limits from a date; they take effect only once the Director
confirms them (rule 5: not the same person). Old quotations keep the limits in force on
their date (rule 11). Used by quotations in Phase 1.5.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User

from . import currencies
from .models import QuotationLimit
from .services import MastersError


class LimitError(MastersError):
    pass


def _decimal(value, label: str, places: str) -> Decimal:
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise LimitError(f"{label} must be a number.") from None
    if not number.is_finite():
        raise LimitError(f"{label} must be a number.")
    if number != number.quantize(Decimal(places)):
        raise LimitError(f"{label} can have at most {len(places) - 2} decimal places.")
    return number


def propose(
    *,
    user: User,
    division: Division,
    effective_from: date,
    min_margin_pct,
    director_above_lkr,
    reason,
) -> QuotationLimit:
    if not (reason or "").strip():
        raise LimitError("Give a reason for the change.")
    if effective_from < timezone.localdate():
        raise LimitError("New limits cannot start in the past; choose today or a later date.")
    margin = _decimal(min_margin_pct, "The minimum margin", "0.01")
    if not 0 <= margin < 100:
        raise LimitError("The minimum margin must be from 0% to below 100%.")
    value = _decimal(director_above_lkr, "The value limit", "0.01")
    if value <= 0:
        raise LimitError("The value limit must be more than zero.")
    with audit_context("quotation_limit_proposed", reason), transaction.atomic():
        if not division.is_active:
            raise LimitError(f"Division {division.code} is deactivated.")
        if QuotationLimit.objects.filter(division=division, status="pending").exists():
            raise LimitError(
                f"{division.code} already has a change waiting for the Director. Withdraw it "
                "first, or wait for the decision."
            )
        return QuotationLimit.objects.create(
            division=division,
            effective_from=effective_from,
            min_margin_pct=margin,
            director_above_lkr=value,
            reason=reason.strip(),
            created_by=user,
        )


def _pending(limit: QuotationLimit) -> QuotationLimit:
    limit = QuotationLimit.objects.select_for_update().get(pk=limit.pk)
    if limit.status != QuotationLimit.Status.PENDING:
        raise LimitError(f"This change is already {limit.get_status_display().lower()}.")
    return limit


def _check_director(user: User, limit: QuotationLimit) -> None:
    if not effective_access(user).can("confirm_limits"):
        raise LimitError("Only the Director can confirm or reject quotation limits.")
    if limit.created_by_id == user.pk:
        raise LimitError("You cannot confirm a change you entered yourself.")


def confirm(user: User, limit: QuotationLimit) -> QuotationLimit:
    """The limits take effect from their date, or from today if confirmed later."""
    with audit_context("quotation_limit_confirmed"), transaction.atomic():
        limit = _pending(limit)
        _check_director(user, limit)
        today = timezone.localdate()
        if limit.effective_from < today:
            limit.effective_from = today
        clash = QuotationLimit.objects.filter(
            division=limit.division, effective_from=limit.effective_from, status="confirmed"
        )
        if clash.exists():
            raise LimitError(
                f"{limit.division.code} already has confirmed limits from "
                f"{limit.effective_from}; ask the Admin to enter the change from a later date."
            )
        limit.status = QuotationLimit.Status.CONFIRMED
        limit.decided_by = user
        limit.decided_at = timezone.now()
        limit.save()
        return limit


def reject(user: User, limit: QuotationLimit, note: str) -> QuotationLimit:
    if not (note or "").strip():
        raise LimitError("Give a reason for rejecting the change.")
    with audit_context("quotation_limit_rejected", note), transaction.atomic():
        limit = _pending(limit)
        _check_director(user, limit)
        limit.status = QuotationLimit.Status.REJECTED
        limit.decided_by = user
        limit.decided_at = timezone.now()
        limit.decision_note = note.strip()
        limit.save()
        return limit


def withdraw(user: User, limit: QuotationLimit) -> QuotationLimit:
    with audit_context("quotation_limit_withdrawn"), transaction.atomic():
        limit = _pending(limit)
        if limit.created_by_id != user.pk:
            raise LimitError("Only the person who entered the change can withdraw it.")
        limit.status = QuotationLimit.Status.WITHDRAWN
        limit.decided_by = user
        limit.decided_at = timezone.now()
        limit.save()
        return limit


def in_force(division: Division, on_date: date) -> QuotationLimit | None:
    """The confirmed limits a quotation dated `on_date` must meet."""
    return (
        QuotationLimit.objects.filter(
            division=division, status="confirmed", effective_from__lte=on_date
        )
        .order_by("-effective_from")
        .first()
    )


@dataclass
class ApprovalCheck:
    needs_director: bool
    reasons: list[str]
    value_lkr: Decimal
    limit: QuotationLimit | None


def check_quotation(
    *, division: Division, on_date: date, margin_pct, value, currency: str = "LKR"
) -> ApprovalCheck:
    """Does a quotation need the Director? A foreign-currency value is converted at the
    rate of the quotation's date. With no limits set, every quotation goes to the Director."""
    lookup = currencies.rate_on(currency, on_date)
    value_lkr = currencies.to_lkr(Decimal(str(value)), lookup)
    limit = in_force(division, on_date)
    if limit is None:
        return ApprovalCheck(
            True, [f"No confirmed quotation limits for {division.code} yet."], value_lkr, None
        )
    reasons = []
    margin = Decimal(str(margin_pct))
    if margin < limit.min_margin_pct:
        reasons.append(f"Margin {margin}% is below the minimum of {limit.min_margin_pct}%.")
    if value_lkr > limit.director_above_lkr:
        reasons.append(f"Value LKR {value_lkr:,} is above LKR {limit.director_above_lkr:,}.")
    return ApprovalCheck(bool(reasons), reasons, value_lkr, limit)
