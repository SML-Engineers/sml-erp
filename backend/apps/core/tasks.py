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
