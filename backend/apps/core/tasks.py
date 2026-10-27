from celery import shared_task


@shared_task
def ping() -> str:
    """Trivial task used to check that the background worker is running."""
    return "pong"
