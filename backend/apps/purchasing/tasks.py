from celery import shared_task


@shared_task
def check_reorder_levels() -> int:
    from .requests import check

    return check()


@shared_task
def remind_rejected_stock() -> int:
    from apps.inventory.rejected import remind

    return remind()
