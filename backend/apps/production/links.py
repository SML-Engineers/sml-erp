"""The job or production order a cost belongs to (backlog P3-13; spec 7.7): resolved from the
number the Accountant types on a voucher line or a supplier invoice line."""

from .models import JobOrder, ProductionOrder

OPEN_FOR_COSTS = ("released", "completed")


class OrderNotFound(Exception):
    pass


def order_for(text) -> tuple[JobOrder | None, ProductionOrder | None, str]:
    """(job, production order, number) for a number; nothing for a blank. Only a released or
    completed order takes costs."""
    number = " ".join(str(text or "").split()).upper()
    if not number:
        return None, None, ""
    job = JobOrder.objects.filter(number=number).first()
    order = None if job else ProductionOrder.objects.filter(number=number).first()
    found = job or order
    if found is None:
        raise OrderNotFound(f"There is no job order or production order {number}.")
    if found.status not in OPEN_FOR_COSTS:
        raise OrderNotFound(
            f"{number} is {found.get_status_display().lower()}: costs go to a released or "
            "completed order."
        )
    return job, order, number
