"""Notifications: the bell and email (backlog P0-18, spec 3 Notifications).

`notify()` writes one notification per person, as part of the transaction that caused it,
so nothing is announced that did not happen. Emails go out after that transaction commits,
through the background worker; a periodic job sends any that are still waiting (for example
if the worker was down), and each email is sent once only.

Each person chooses, per kind of event, whether it appears under the bell, arrives by email,
both or neither. Approval events come from the approval engine (approvals.py).
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import Notification, NotificationPreference, User

EVENTS = {
    "approval_waiting": "A document is waiting for my approval",
    "approval_reminder": "Reminder: a document has been waiting a long time for my approval",
    "document_returned": "A document I created was returned to me",
    "document_approved": "A document I created was approved",
    "document_rejected": "A document I created was rejected",
    "admin_request_waiting": "An Admin request (such as a password reset) waits for my approval",
    "admin_request_decided": "An Admin request I made was approved or refused",
}

log = logging.getLogger(__name__)

KEEP_DAYS = 180  # read notifications are tidied away after this many days


class NotificationError(Exception):
    pass


def preferences(user: User) -> list[dict]:
    stored = {p.event: p for p in NotificationPreference.objects.filter(user=user)}
    return [
        {
            "event": event,
            "label": label,
            "in_app": stored[event].in_app if event in stored else True,
            "email": stored[event].email if event in stored else True,
        }
        for event, label in EVENTS.items()
    ]


def set_preference(user: User, event: str, *, in_app=None, email=None) -> list[dict]:
    if event not in EVENTS:
        raise NotificationError("Unknown kind of notification.")
    preference, _ = NotificationPreference.objects.get_or_create(user=user, event=event)
    if in_app is not None:
        preference.in_app = bool(in_app)
    if email is not None:
        preference.email = bool(email)
    preference.save()
    return preferences(user)


def notify(
    users,
    event: str,
    *,
    title: str,
    body: str = "",
    link: str = "",
    document_type: str = "",
    document_id: int | None = None,
) -> list[Notification]:
    """Tell each user (inactive users and duplicates are skipped), as each has chosen."""
    if event not in EVENTS:
        raise NotificationError(f"Unknown kind of notification {event!r}.")
    people = {u.pk: u for u in users if u is not None and u.is_active}
    if not people:
        return []
    chosen = {
        p.user_id: p for p in NotificationPreference.objects.filter(user_id__in=people, event=event)
    }
    created = []
    for pk, user in people.items():
        choice = chosen.get(pk)
        in_app = choice.in_app if choice else True
        email = (choice.email if choice else True) and bool(user.email)
        if not (in_app or email):
            continue
        created.append(
            Notification.objects.create(
                user=user,
                event=event,
                title=title[:200],
                body=body,
                link=link[:200],
                document_type=document_type,
                document_id=document_id,
                in_app=in_app,
                email=email,
            )
        )
    emails = [n.pk for n in created if n.email]
    if emails:
        transaction.on_commit(lambda: _queue(emails))
    return created


def _queue(ids: list[int]) -> None:
    from .tasks import send_notification_email

    for pk in ids:
        try:
            send_notification_email.delay(pk)
        except Exception:  # noqa: BLE001 - the worker is down; the periodic job sends it later
            log.warning("Could not queue notification email %s; it will be retried", pk)


def _absolute(link: str) -> str:
    base = getattr(settings, "APP_URL", "").rstrip("/")
    return f"{base}{link}" if link.startswith("/") and base else link


def send_email(notification_id: int) -> bool:
    """Send one notification's email, once. Returns True if it was sent now."""
    with transaction.atomic():
        notification = (
            Notification.objects.select_for_update()
            .select_related("user")
            .filter(pk=notification_id, email=True, emailed_at__isnull=True)
            .first()
        )
        if notification is None or not notification.user.is_active:
            return False
        lines = [f"Hello {notification.user.full_name},", "", notification.title]
        if notification.body:
            lines += ["", notification.body]
        if notification.link:
            lines += ["", f"Open it: {_absolute(notification.link)}"]
        lines += [
            "",
            "You can choose which notifications you receive by email under My notifications.",
        ]
        send_mail(
            subject=f"SML ERP: {notification.title}",
            message="\n".join(lines),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.user.email],
        )
        notification.emailed_at = timezone.now()
        notification.save(update_fields=["emailed_at"])
        return True


def send_waiting_emails(limit: int = 200) -> int:
    """Send emails still waiting (run every few minutes by the background scheduler)."""
    ids = Notification.objects.filter(email=True, emailed_at__isnull=True).values_list(
        "pk", flat=True
    )[:limit]
    sent = 0
    for pk in list(ids):
        try:
            sent += send_email(pk)
        except Exception:  # noqa: BLE001 - mail server trouble: left for the next run
            log.exception("Could not send notification email %s; it will be retried", pk)
    return sent


def tidy_old(days: int = KEEP_DAYS) -> int:
    cutoff = timezone.now() - timedelta(days=days)
    deleted, _ = Notification.objects.filter(read_at__lt=cutoff).delete()
    return deleted


# --- The bell ---------------------------------------------------------------------------


def for_bell(user: User):
    return Notification.objects.filter(user=user, in_app=True)


def unread_count(user: User) -> int:
    return for_bell(user).filter(read_at__isnull=True).count()


def mark_read(user: User, ids: list[int] | None = None) -> int:
    """Mark the given notifications (or all) as read. Only the user's own."""
    rows = for_bell(user).filter(read_at__isnull=True)
    if ids is not None:
        rows = rows.filter(pk__in=ids)
    return rows.update(read_at=timezone.now())
