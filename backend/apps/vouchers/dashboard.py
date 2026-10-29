"""The vouchers dashboard on the home page (spec 7A, backlog P1-08b).

Every figure is worked out from the same rules as the list it opens, so a tile and its list
always agree: vouchers waiting for me (my approval queue), my drafts and returned vouchers,
vouchers waiting by level and age (the pending report), approved and unpaid (the Cashier's
list), and payments this month (payments made). A user only sees their divisions' vouchers.
"""

from decimal import Decimal

from django.db.models import Count, Sum
from django.utils import timezone

from apps.core.access import division_scope, effective_access
from apps.core.models import User

from . import reports, services
from .models import Voucher

PAYABLE = (Voucher.Status.DIRECTOR_APPROVED, Voucher.Status.PARTLY_PAID)
ZERO = Decimal("0.00")


def _money(value) -> str:
    return f"{(value or ZERO):.2f}"


def _unpaid(rows) -> dict:
    """Approved and not fully paid: how many, their approved total and what is left."""
    from apps.payments.models import SupplierPayment

    vouchers = rows.filter(status__in=PAYABLE)
    approved = vouchers.aggregate(n=Count("id"), total=Sum("total_amount"))
    paid = (
        SupplierPayment.objects.filter(voucher__in=vouchers, cancelled=False).aggregate(
            total=Sum("amount")
        )["total"]
        or ZERO
    )
    total = approved["total"] or ZERO
    return {"count": approved["n"], "total": _money(total), "remaining": _money(total - paid)}


def _paid_this_month(user: User, division: str) -> dict | None:
    if not effective_access(user).has("payments", "view"):
        return None
    from apps.payments.services import visible as visible_payments

    today = timezone.localdate()
    start = today.replace(day=1)
    payments = visible_payments(user).filter(payment_date__gte=start, payment_date__lte=today)
    if division:
        payments = payments.filter(voucher__division__code=division)
    figures = payments.aggregate(n=Count("id"), total=Sum("amount"))
    return {
        "count": figures["n"],
        "total": _money(figures["total"]),
        "from": start.isoformat(),
        "to": today.isoformat(),
    }


def figures(user: User, division: str = "") -> dict:
    division = (division or "").upper()
    rows = services.visible(user)
    if division:
        rows = rows.filter(division__code=division)

    queue = services.waiting(user)
    if division:
        queue = queue.filter(division__code=division)
    queue_sum = queue.aggregate(n=Count("id"), total=Sum("total_amount"))

    mine = rows.filter(created_by=user, status__in=services.EDITABLE)
    drafts = {}
    for status in services.EDITABLE:
        mine_now = mine.filter(status=status).aggregate(n=Count("id"), total=Sum("total_amount"))
        drafts[status] = {"count": mine_now["n"], "total": _money(mine_now["total"])}

    pending = reports.pending(user, division=division)
    levels: dict[int, dict] = {}
    for row in pending:
        entry = levels.setdefault(
            row["level"],
            {
                "level": row["level"],
                "waiting_for": row["waiting_for"],
                "count": 0,
                "total": ZERO,
                "bands": {name: 0 for _, name in reports.AGE_BANDS},
            },
        )
        entry["count"] += 1
        entry["total"] += Decimal(row["total_amount"])
        entry["bands"][row["band"]] += 1
    by_level = [{**entry, "total": _money(entry["total"])} for _, entry in sorted(levels.items())]

    by_division = []
    for d in division_scope(user).order_by("code"):
        if division and d.code != division:
            continue
        in_division = services.visible(user).filter(division=d)
        waiting = [r for r in pending if r["division"] == d.code]
        paid = _paid_this_month(user, d.code)
        by_division.append(
            {
                "code": d.code,
                "name": d.name,
                "pending": len(waiting),
                "pending_total": _money(sum((Decimal(r["total_amount"]) for r in waiting), ZERO)),
                "unpaid": _unpaid(in_division),
                "paid_this_month": paid["total"] if paid else None,
            }
        )

    return {
        "division": division,
        "can_approve": effective_access(user).has("vouchers", "approve"),
        "can_enter": effective_access(user).has("vouchers", "enter"),
        # A Cashier sees approved vouchers only, so counts of vouchers waiting for approval
        # would always be 0 for them: the dashboard leaves those out.
        "sees_approvals": not services.approved_only(user),
        "waiting_for_me": {"count": queue_sum["n"], "total": _money(queue_sum["total"])},
        "my_vouchers": drafts,
        "by_level": by_level,
        "pending_count": len(pending),
        "unpaid": _unpaid(rows),
        "paid_this_month": _paid_this_month(user, division),
        "by_division": by_division,
        "oldest": pending[:5],
    }
