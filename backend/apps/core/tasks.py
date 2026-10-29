from celery import shared_task


@shared_task
def ping() -> str:
    """Trivial task used to check that the background worker is running."""
    return "pong"


@shared_task
def notify_expired_access() -> int:
    from .access_admin import notify_expired_overrides

    return notify_expired_overrides()


@shared_task
def deactivate_inactive_accounts() -> list[str]:
    from .access_admin import deactivate_inactive_accounts as run

    return run()


@shared_task
def send_notification_email(notification_id: int) -> bool:
    from .notifications import send_email

    return send_email(notification_id)


@shared_task
def send_waiting_notification_emails() -> int:
    from .notifications import send_waiting_emails

    return send_waiting_emails()


@shared_task
def tidy_old_notifications() -> int:
    from .notifications import tidy_old

    return tidy_old()


@shared_task
def send_approval_reminders() -> int:
    from .approvals import send_reminders

    return send_reminders()
