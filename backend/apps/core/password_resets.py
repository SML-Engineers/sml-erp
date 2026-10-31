"""Resetting someone's password (owner's decision, 31 Oct 2026).

1. The Admin requests it, with a reason (and, for a lost phone, the authenticator too).
2. The Director approves or refuses it. Nobody approves a reset they asked for or a reset of
   their own password.
3. Within 24 hours of approval, the Admin who asked makes the new temporary password. It is
   shown to them once and never stored. The person is signed out everywhere and must choose
   their own password at the next sign-in (and set up the authenticator again, if reset).

Every step is in the audit log.
"""

import secrets

from django.db import transaction
from django.utils import timezone

from . import access, notifications
from .access import AccessError
from .access_admin import end_sessions
from .audit import audit_context
from .models import PasswordReset, RecoveryCode, User

APPROVER_ACTION = "confirm_sensitive_grants"


def can_request(user: User) -> bool:
    return access.effective_access(user).has("users", "manage")


def can_decide(user: User, reset: PasswordReset) -> bool:
    return (
        reset.status == "waiting"
        and access.effective_access(user).can(APPROVER_ACTION)
        and user.pk not in (reset.requested_by_id, reset.user_id)
    )


def can_issue(user: User, reset: PasswordReset) -> bool:
    return reset.status == "approved" and reset.requested_by_id == user.pk and can_request(user)


def approvers(reset: PasswordReset) -> list[User]:
    return [
        u
        for u in User.objects.filter(is_active=True).exclude(
            pk__in=(reset.requested_by_id, reset.user_id)
        )
        if access.effective_access(u).can(APPROVER_ACTION)
    ]


def _link(reset: PasswordReset) -> str:
    return f"/admin/users/{reset.user_id}"


@transaction.atomic
def request(actor: User, target: User, reason: str, with_authenticator=False) -> PasswordReset:
    if not can_request(actor):
        raise AccessError("Only the Admin can ask for a password reset.")
    if actor.pk == target.pk:
        raise AccessError("Change your own password from your account menu.")
    reason = (reason or "").strip()
    if not reason:
        raise AccessError("Give a reason for the reset.")
    open_ones = [r for r in target.password_resets.all() if r.status in ("waiting", "approved")]
    if open_ones:
        raise AccessError(f"A password reset for {target.full_name} is already open.")
    with audit_context("password_reset_requested", reason):
        reset = PasswordReset.objects.create(
            user=target,
            with_authenticator=bool(with_authenticator),
            reason=reason,
            requested_by=actor,
        )
    who = approvers(reset)
    if not who:
        raise AccessError(
            "Nobody else can approve this reset (it needs a Director other than the person "
            "being reset)."
        )
    what = "password and authenticator" if reset.with_authenticator else "password"
    notifications.notify(
        who,
        "admin_request_waiting",
        title=f"Reset of {target.full_name}'s {what} is waiting for your approval",
        body=f"Asked by {actor.full_name}: {reason}",
        link=_link(reset),
    )
    return reset


@transaction.atomic
def decide(actor: User, reset: PasswordReset, *, approve: bool, reason: str = "") -> PasswordReset:
    reset = PasswordReset.objects.select_for_update().get(pk=reset.pk)
    if not access.effective_access(actor).can(APPROVER_ACTION):
        raise AccessError("Only the Director approves password resets.")
    if reset.status != "waiting":
        raise AccessError("This password reset is not waiting for approval.")
    if actor.pk in (reset.requested_by_id, reset.user_id):
        raise AccessError(
            "Someone other than the person who asked and the person being reset must decide."
        )
    reason = (reason or "").strip()
    if not approve and not reason:
        raise AccessError("Give a reason for refusing.")
    event = "password_reset_approved" if approve else "password_reset_refused"
    with audit_context(event, reason):
        reset.approved = approve
        reset.decided_by = actor
        reset.decided_at = timezone.now()
        reset.decision_reason = reason
        reset.save(update_fields=["approved", "decided_by", "decided_at", "decision_reason"])
    outcome = (
        f"approved: make the new temporary password within {PasswordReset.APPROVAL_HOURS} hours"
        if approve
        else f"refused: {reason}"
    )
    notifications.notify(
        [reset.requested_by],
        "admin_request_decided",
        title=f"Password reset for {reset.user.full_name} {outcome}",
        link=_link(reset),
    )
    return reset


@transaction.atomic
def issue(actor: User, reset: PasswordReset) -> str:
    """Make the temporary password and return it (to show once). Signs the person out."""
    reset = PasswordReset.objects.select_for_update().get(pk=reset.pk)
    if reset.status == "lapsed":
        raise AccessError("The approval has lapsed after 24 hours; ask again.")
    if not can_issue(actor, reset):
        raise AccessError("Only the Admin who asked can use an approved reset.")
    password = secrets.token_urlsafe(12)
    target = reset.user
    with audit_context("password_reset_done", reset.reason):
        target.set_password(password)
        target.must_change_password = True
        fields = ["password", "must_change_password"]
        if reset.with_authenticator:
            target.totp_secret_encrypted = ""
            target.totp_confirmed_at = None
            target.totp_last_timestep = None
            fields += ["totp_secret_encrypted", "totp_confirmed_at", "totp_last_timestep"]
            RecoveryCode.objects.filter(user=target).delete()
        target.save(update_fields=fields)
        reset.issued_at = timezone.now()
        reset.save(update_fields=["issued_at"])
    end_sessions(target)
    return password


def history(target: User) -> list[PasswordReset]:
    return list(target.password_resets.select_related("requested_by", "decided_by")[:20])
