from celery import shared_task


@shared_task
def expire_quotations() -> int:
    """Daily (P15-06): approved and sent quotations past their validity date become Expired."""
    from .workflow import expire_due

    return expire_due()
