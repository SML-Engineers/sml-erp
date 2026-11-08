"""Actual labour cost per hour (backlog P2B-13), for job costing (Phase 3).

- A payroll's labour cost is what the company pays for the pay month: gross pay plus the
  company's EPF 12% and ETF 3%.
- Hours are the hours worked in the pay period, from attendance (P2B-04, sheet and phone
  punches; breaks already left out), of the employees in the payroll.
- Cost per hour = cost / hours, for the division and for each section (sections hold the
  machines that job costing will charge). Shown on the payroll page; per section only to HR
  and the Director, as a section of one person would show their pay.
- Sections carry their id as well as their name, so the production cost rates (P3-05) can
  be kept per section.
- `rate(division, month)` gives job costing the rate of a division's approved payroll for a
  pay month (None until it is approved).
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum

from .models import AttendanceDay, PayrollRun

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _per_hour(cost: Decimal, minutes: int) -> Decimal | None:
    if not minutes:
        return None
    return (cost * 60 / minutes).quantize(CENT, ROUND_HALF_UP)


def _hours(minutes: int) -> Decimal:
    return (Decimal(minutes) / 60).quantize(CENT, ROUND_HALF_UP)


def cost(run: PayrollRun) -> dict:
    lines = list(run.lines.select_related("employee", "employee__section"))
    minutes = dict(
        AttendanceDay.objects.filter(
            employee__in=[x.employee_id for x in lines],
            date__range=(run.period_start, run.period_end),
        )
        .values("employee")
        .annotate(total=Sum("worked_minutes"))
        .values_list("employee", "total")
    )
    by_section: dict[int | None, dict] = defaultdict(
        lambda: {"name": "", "employees": 0, "cost": ZERO, "minutes": 0}
    )
    total_cost, total_minutes = ZERO, 0
    for x in lines:
        paid = x.gross + x.epf_employer + x.etf
        worked = minutes.get(x.employee_id) or 0
        s = by_section[x.employee.section_id]
        s["name"] = x.employee.section.name if x.employee.section_id else "(no section)"
        s["employees"] += 1
        s["cost"] += paid
        s["minutes"] += worked
        total_cost += paid
        total_minutes += worked
    return {
        "cost": total_cost,
        "hours": _hours(total_minutes),
        "per_hour": _per_hour(total_cost, total_minutes),
        "sections": [
            {
                "section": s["name"],
                "section_id": section_id,
                "employees": s["employees"],
                "cost": s["cost"],
                "hours": _hours(s["minutes"]),
                "per_hour": _per_hour(s["cost"], s["minutes"]),
            }
            for section_id, s in sorted(by_section.items(), key=lambda pair: pair[1]["name"])
        ],
    }


def rate(division, month) -> Decimal | None:
    run = PayrollRun.objects.filter(
        division=division, month=month, status=PayrollRun.Status.APPROVED
    ).first()
    return cost(run)["per_hour"] if run else None
