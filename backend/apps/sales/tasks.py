from celery import shared_task


@shared_task
def expire_quotations() -> int:
    """Daily (P15-06): approved and sent quotations past their validity date become Expired."""
    from .workflow import expire_due

    return expire_due()


@shared_task
def post_due_cheques() -> int:
    """Daily (P2-07): approved post-dated cheques from customers are posted on their date."""
    from .receipts import post_due

    return post_due()
