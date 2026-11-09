from celery import shared_task


@shared_task
def snapshot_order_profits() -> int:
    """P3-17: each evening, every open order's profitability is kept and its alerts sent."""
    from .profit import snapshot_open

    return snapshot_open()
