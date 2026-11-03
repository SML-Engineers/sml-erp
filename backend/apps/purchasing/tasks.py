from celery import shared_task


@shared_task
def check_reorder_levels() -> int:
    from .requests import check

    return check()
