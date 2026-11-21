"""The notice in the top bar (owner, 21 Nov 2026).

The Admin asks to switch it on or off, or to change its words, with a reason. Nothing changes
until a Director other than the Admin approves. English is shown with Sinhala below it, whatever
language the person uses. Every request and decision is in the audit log.
"""

from django.db import transaction
from django.utils import timezone

from .access import effective_access, has_access
from .audit import audited
from .models import NoticeChange, User

DEFAULT_EN = "Entering false information into the system is a punishable offence."
DEFAULT_SI = "පද්ධතියට අසත්‍ය තොරතුරු ඇතුළත් කිරීම දඬුවම් ලැබිය හැකි වරදකි."
MAX_LENGTH = 200


class NoticeError(Exception):
    pass


def in_force() -> NoticeChange | None:
    return (
        NoticeChange.objects.filter(status=NoticeChange.Status.APPROVED)
        .order_by("-decided_at", "-id")
        .first()
    )


def current() -> dict:
    """What every signed-in person sees: nothing while the notice is off."""
    change = in_force()
    if change is None or not change.show:
        return {"show": False, "text_en": "", "text_si": ""}
    return {"show": True, "text_en": change.text_en, "text_si": change.text_si}


def waiting() -> NoticeChange | None:
    return NoticeChange.objects.filter(status=NoticeChange.Status.WAITING).first()


def can_decide(user: User, change: NoticeChange) -> bool:
    return (
        change.status == NoticeChange.Status.WAITING
        and change.requested_by_id != user.pk
        and effective_access(user).can("confirm_sensitive_grants")
    )


def deciders(actor: User) -> list[User]:
    """Directors who may approve: anyone who confirms sensitive grants, not the person asking."""
    return [
        u
        for u in User.objects.filter(is_active=True).exclude(pk=actor.pk)
        if effective_access(u).can("confirm_sensitive_grants")
    ]


@audited("notice_change_requested", reason_arg="reason")
@transaction.atomic
def request_change(
    actor: User, show: bool, text_en: str, text_si: str, reason: str
) -> NoticeChange:
    if not has_access(actor, "users", "manage"):
        raise NoticeError("Only the Admin can ask to change the notice.")
    reason = (reason or "").strip()
    if not reason:
        raise NoticeError("Give the reason for the change.")
    text_en, text_si = (text_en or "").strip(), (text_si or "").strip()
    if show and (not text_en or not text_si):
        raise NoticeError("Write the notice in both English and Sinhala.")
    if len(text_en) > MAX_LENGTH or len(text_si) > MAX_LENGTH:
        raise NoticeError(f"Keep each line of the notice to {MAX_LENGTH} characters.")
    if not show:
        # Switching off keeps the words in force, so switching on again starts from them.
        kept = in_force()
        text_en = text_en or (kept.text_en if kept else "")
        text_si = text_si or (kept.text_si if kept else "")
    if NoticeChange.objects.select_for_update().filter(status=NoticeChange.Status.WAITING):
        raise NoticeError(
            "A change to the notice is already waiting for the Director. Withdraw it first."
        )
    now = current()
    if now == {"show": show, "text_en": text_en, "text_si": text_si} or (
        not show and not now["show"]
    ):
        raise NoticeError("That is the notice already in force.")
    change = NoticeChange.objects.create(
        show=show, text_en=text_en, text_si=text_si, reason=reason, requested_by=actor
    )
    from . import notifications

    notifications.notify(
        deciders(actor),
        "admin_request_waiting",
        title=(
            "Top-bar notice: switch on, waiting for your approval"
            if show
            else "Top-bar notice: switch off, waiting for your approval"
        ),
        body=f"Asked by {actor.full_name}: {reason}",
        link="/admin/access-to-confirm",
    )
    return change


def _locked_waiting(change: NoticeChange) -> NoticeChange:
    change = NoticeChange.objects.select_for_update().get(pk=change.pk)
    if change.status != NoticeChange.Status.WAITING:
        raise NoticeError("This change to the notice is not waiting any more.")
    return change


def _check_decider(actor: User, change: NoticeChange) -> None:
    if not effective_access(actor).can("confirm_sensitive_grants"):
        raise NoticeError("Only the Director can decide on the notice.")
    if change.requested_by_id == actor.pk:
        raise NoticeError("Someone other than the person who asked must decide.")


@audited("notice_change_approved")
@transaction.atomic
def approve(actor: User, change: NoticeChange) -> NoticeChange:
    change = _locked_waiting(change)
    _check_decider(actor, change)
    change.status = NoticeChange.Status.APPROVED
    change.decided_by = actor
    change.decided_at = timezone.now()
    change.save(update_fields=["status", "decided_by", "decided_at"])
    _tell_requester(change, "approved")
    return change


@audited("notice_change_refused", reason_arg="reason")
@transaction.atomic
def refuse(actor: User, change: NoticeChange, reason: str) -> NoticeChange:
    change = _locked_waiting(change)
    _check_decider(actor, change)
    reason = (reason or "").strip()
    if not reason:
        raise NoticeError("Give a reason for refusing.")
    change.status = NoticeChange.Status.REFUSED
    change.decided_by = actor
    change.decided_at = timezone.now()
    change.decision_reason = reason
    change.save(update_fields=["status", "decided_by", "decided_at", "decision_reason"])
    _tell_requester(change, "refused")
    return change


@audited("notice_change_withdrawn")
@transaction.atomic
def withdraw(actor: User, change: NoticeChange) -> NoticeChange:
    change = _locked_waiting(change)
    if not has_access(actor, "users", "manage"):
        raise NoticeError("Only the Admin can withdraw a change to the notice.")
    change.status = NoticeChange.Status.WITHDRAWN
    change.decided_at = timezone.now()
    change.save(update_fields=["status", "decided_at"])
    return change


def _tell_requester(change: NoticeChange, what: str) -> None:
    from . import notifications

    notifications.notify(
        [change.requested_by],
        "admin_request_decided",
        title=f"The change to the top-bar notice was {what} by {change.decided_by.full_name}",
        body=change.decision_reason,
        link="/admin/sign-in-security",
    )


def row(change: NoticeChange, viewer: User) -> dict:
    return {
        "id": change.pk,
        "show": change.show,
        "text_en": change.text_en,
        "text_si": change.text_si,
        "reason": change.reason,
        "requested_by": change.requested_by.full_name,
        "requested_at": change.requested_at,
        "status": change.status,
        "status_label": change.get_status_display(),
        "decided_by": change.decided_by.full_name if change.decided_by else None,
        "decided_at": change.decided_at,
        "decision_reason": change.decision_reason,
        "can_decide": can_decide(viewer, change),
    }
