from celery import shared_task


@shared_task
def make_recurring_journals() -> int:
    """Every morning (P2-02): the draft journals of recurring journals that have come due."""
    from .recurring import make_due

    return make_due()


@shared_task
def reverse_accruals() -> int:
    """Every morning (P2-02): accruals reversed on the first day of the next month."""
    from .manual import reverse_due

    return reverse_due()
