"""Access administration (backlog P0-04b, spec 1.3): overrides, joiners / movers / leavers,
expiry, inactivity and the periodic access review."""

from datetime import date, timedelta

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from . import access
from .access import AccessError
from .access_defaults import (
    ACTIONS,
    AREAS,
    LEVELS,
    SENSITIVE_ACTIONS,
    SENSITIVE_AREA_LEVELS,
    SENSITIVE_AREAS,
)
from .models import AccessOverride, AccessReview, Role, User

# --- Overrides --------------------------------------------------------------------------


def is_sensitive(area: str = "", level: str = "", action: str = "") -> bool:
    if action:
        return action in SENSITIVE_ACTIONS
    return (area, level) in SENSITIVE_AREA_LEVELS or area in SENSITIVE_AREAS


def _not_self(actor: User, target: User, what: str = "access") -> None:
    if actor.pk == target.pk:
        raise AccessError(f"You cannot change your own {what}; another administrator must do it.")


@transaction.atomic
def create_override(
    actor: User,
    target: User,
    *,
    effect: str,
    reason: str,
    area: str = "",
    level: str = "",
    action: str = "",
    ends_on: date | None = None,
) -> AccessOverride:
    _not_self(actor, target)
    reason = (reason or "").strip()
    if not reason:
        raise AccessError("A reason is required.")
    if effect not in AccessOverride.Effect.values:
        raise AccessError("Choose grant or remove.")
    if action:
        if action not in ACTIONS or area or level:
            raise AccessError("Unknown special action.")
    elif area not in AREAS or level not in LEVELS:
        raise AccessError("Choose a valid area and access level.")
    if ends_on and ends_on < timezone.localdate():
        raise AccessError("The end date cannot be in the past.")

    override = AccessOverride.objects.create(
        user=target,
        area=area,
        level=level,
        action=action,
        effect=effect,
        reason=reason,
        ends_on=ends_on,
        is_sensitive=effect == AccessOverride.Effect.GRANT and is_sensitive(area, level, action),
        created_by=actor,
    )
    target.__dict__.pop("_effective_access", None)
    return override


@transaction.atomic
def confirm_override(actor: User, override: AccessOverride) -> AccessOverride:
    """The Director confirms a sensitive grant; only then does it take effect."""
    if not access.effective_access(actor).can("confirm_sensitive_grants"):
        raise AccessError("Only the Director can confirm sensitive access.")
    if override.status != "pending":
        raise AccessError("This override is not waiting for confirmation.")
    if actor.pk in (override.created_by_id, override.user_id):
        raise AccessError("Someone other than the requester and the recipient must confirm it.")
    override.confirmed_by = actor
    override.confirmed_at = timezone.now()
    override.save(update_fields=["confirmed_by", "confirmed_at"])
    return override


@transaction.atomic
def revoke_override(actor: User, override: AccessOverride, reason: str) -> AccessOverride:
    _not_self(actor, override.user)
    if override.revoked_at:
        raise AccessError("This override has already been ended.")
    override.revoked_by = actor
    override.revoked_at = timezone.now()
    override.revoke_reason = (reason or "").strip() or "Ended by administrator"
    override.save(update_fields=["revoked_by", "revoked_at", "revoke_reason"])
    return override


@transaction.atomic
def reset_to_role_defaults(actor: User, target: User, reason: str) -> int:
    """End every override, so the user has exactly their roles' access."""
    _not_self(actor, target)
    open_overrides = target.access_overrides.filter(revoked_at__isnull=True)
    count = open_overrides.count()
    open_overrides.update(
        revoked_by=actor,
        revoked_at=timezone.now(),
        revoke_reason=(reason or "").strip() or "Reset to role defaults",
    )
    return count


@transaction.atomic
def copy_access(actor: User, target: User, source: User, reason: str) -> list[str]:
    """Give `target` the same roles, divisions and current overrides as `source`.

    Sensitive grants are copied as new requests that the Director must confirm again.
    """
    _not_self(actor, target)
    roles = list(Role.objects.filter(assignments__user=source))
    warnings = access.set_user_roles(actor, target, roles, reason)
    access.set_user_scope(actor, target, source.all_divisions, list(source.divisions.all()))
    reset_to_role_defaults(actor, target, f"Replaced by access copied from {source.email}")
    for o in source.access_overrides.filter(revoked_at__isnull=True).exclude(
        ends_on__lt=timezone.localdate()
    ):
        create_override(
            actor,
            target,
            effect=o.effect,
            reason=f"Copied from {source.email}: {o.reason}",
            area=o.area,
            level=o.level,
            action=o.action,
            ends_on=o.ends_on,
        )
    return warnings


# --- Leavers and inactivity -------------------------------------------------------------


def end_sessions(user: User) -> int:
    """Sign the user out everywhere at once."""
    ended = 0
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator():
        if session.get_decoded().get("_auth_user_id") == str(user.pk):
            session.delete()
            ended += 1
    return ended


@transaction.atomic
def deactivate_user(actor: User | None, target: User, reason: str) -> None:
    """A leaver: account off, signed out everywhere, overrides ended. Records stay."""
    if actor is not None:
        _not_self(actor, target, "account")
    target.is_active = False
    target.save(update_fields=["is_active"])
    target.access_overrides.filter(revoked_at__isnull=True).update(
        revoked_by=actor,
        revoked_at=timezone.now(),
        revoke_reason=f"Account deactivated: {reason}".strip(),
    )
    end_sessions(target)


def _is_last_active_admin(user: User) -> bool:
    admins = User.objects.filter(
        is_active=True,
        role_assignments__role__code="system_admin",
        role_assignments__role__is_active=True,
    ).distinct()
    return admins.count() <= 1 and admins.filter(pk=user.pk).exists()


def deactivate_inactive_accounts(days: int | None = None) -> list[str]:
    """Deactivate accounts unused for `days` (default 90). Never the last administrator."""
    days = days or settings.INACTIVE_ACCOUNT_DAYS
    cutoff = timezone.now() - timedelta(days=days)
    stale = User.objects.filter(is_active=True).filter(last_login__lt=cutoff) | User.objects.filter(
        is_active=True, last_login__isnull=True, date_joined__lt=cutoff
    )
    deactivated = []
    for user in stale.distinct():
        if _is_last_active_admin(user):
            continue
        deactivate_user(None, user, f"not used for {days} days")
        deactivated.append(user.email)
    return deactivated


def notify_expired_overrides() -> int:
    """Tell users when temporary access has ended (it already stopped working on its date)."""
    today = timezone.localdate()
    due = AccessOverride.objects.filter(
        revoked_at__isnull=True, ends_on__lt=today, expiry_notified_at__isnull=True
    ).select_related("user")
    sent = 0
    for override in due:
        what = ACTIONS.get(override.action) or (
            f"{AREAS.get(override.area, override.area)} ({override.level})"
        )
        verb = "extra access to" if override.effect == "grant" else "restriction on"
        send_mail(
            subject="SML ERP: temporary access ended",
            message=(
                f"Hello {override.user.full_name},\n\nYour temporary {verb} {what} ended on "
                f"{override.ends_on:%d %B %Y}.\n\nIf you still need it, ask the administrator."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[override.user.email],
        )
        override.expiry_notified_at = timezone.now()
        override.save(update_fields=["expiry_notified_at"])
        sent += 1
    return sent


# --- Effective access grid --------------------------------------------------------------


def access_grid(target: User) -> dict:
    """For every area and level: from roles, any override, and the result (spec 1.3)."""
    raw_roles, role_actions = access.role_access(target)
    from_roles = access._expand(raw_roles)
    effective = access.effective_access(target)
    overrides = list(
        target.access_overrides.filter(revoked_at__isnull=True).exclude(
            ends_on__lt=timezone.localdate()
        )
    )

    def override_for(area="", level="", action=""):
        for o in overrides:
            if (o.area, o.level, o.action) == (area, level, action):
                return {"id": o.id, "effect": o.effect, "status": o.status, "ends_on": o.ends_on}
        return None

    return {
        "areas": [
            {
                "area": area,
                "label": label,
                "levels": [
                    {
                        "level": level,
                        "from_roles": level in from_roles.get(area, set()),
                        "override": override_for(area=area, level=level),
                        "effective": effective.has(area, level),
                    }
                    for level in LEVELS
                ],
            }
            for area, label in AREAS.items()
        ],
        "actions": [
            {
                "action": action,
                "label": label,
                "from_roles": action in role_actions,
                "override": override_for(action=action),
                "effective": effective.can(action),
            }
            for action, label in ACTIONS.items()
        ],
    }


# --- Access review ----------------------------------------------------------------------


def current_period(today: date | None = None) -> str:
    today = today or timezone.localdate()
    return f"{today.year}-Q{(today.month - 1) // 3 + 1}"


def sensitive_access(user: User) -> list[str]:
    rights = access.effective_access(user)
    found = [ACTIONS[a] for a in sorted(rights.actions & SENSITIVE_ACTIONS)]
    for area, level in sorted(SENSITIVE_AREA_LEVELS):
        if rights.has(area, level):
            found.append(f"{AREAS[area]} ({level})")
    for area in sorted(SENSITIVE_AREAS):
        if rights.has(area, "view"):
            found.append(AREAS[area])
    return found


def review_rows(period: str) -> list[dict]:
    reviewed = {r.user_id: r for r in AccessReview.objects.filter(period=period)}
    rows = []
    for user in User.objects.filter(is_active=True).order_by("full_name"):
        roles = list(user.role_assignments.select_related("role"))
        overrides = [
            o
            for o in user.access_overrides.filter(revoked_at__isnull=True)
            if o.status in ("active", "pending")
        ]
        review = reviewed.get(user.pk)
        rows.append(
            {
                "user_id": user.pk,
                "email": user.email,
                "full_name": user.full_name,
                "roles": [a.role.name for a in roles],
                "conflicts": [a.conflict_warning for a in roles if a.conflict_warning],
                "overrides": [
                    {
                        "id": o.id,
                        "effect": o.effect,
                        "target": o.action or f"{o.area} {o.level}",
                        "status": o.status,
                        "ends_on": o.ends_on,
                        "reason": o.reason,
                    }
                    for o in overrides
                ],
                "pending_sensitive": sum(o.status == "pending" for o in overrides),
                "sensitive_access": sensitive_access(user),
                "last_login": user.last_login,
                "review": None
                if review is None
                else {
                    "outcome": review.outcome,
                    "reviewed_at": review.reviewed_at,
                    "reviewed_by": review.reviewed_by.email,
                    "note": review.note,
                },
            }
        )
    return rows


@transaction.atomic
def record_review(actor: User, target: User, period: str, outcome: str, note: str = ""):
    if not access.effective_access(actor).can("confirm_sensitive_grants"):
        raise AccessError("Only the Director can record the access review.")
    _not_self(actor, target, "access review")
    if outcome not in AccessReview.Outcome.values:
        raise AccessError("Choose confirmed or changed.")
    review, _ = AccessReview.objects.update_or_create(
        user=target,
        period=period,
        defaults={
            "reviewed_by": actor,
            "outcome": outcome,
            "note": note,
            "reviewed_at": timezone.now(),
        },
    )
    return review
