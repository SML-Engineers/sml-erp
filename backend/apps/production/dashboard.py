"""The Production Manager's dashboard (owner, 11 Nov 2026): what waits for their decision, and
what was made today. Each figure comes from the same queue or report its tile opens, so a tile
and its page always agree."""

from __future__ import annotations

from django.utils import timezone

from apps.core import approvals
from apps.core.models import User

from . import boms, job_inspections, jobs, reports, routings, shift_approval


def _waiting(user: User, document_type: str) -> int:
    return len(approvals.waiting_for(user, document_type))


def dashboard(user: User) -> dict:
    today = timezone.localdate()
    made = reports.daily(user, today, today)["total"]
    return {
        "today": today,
        "waiting": {
            "shift_reports": _waiting(user, shift_approval.DOC),
            "corrections": _waiting(user, shift_approval.FIX),
            "issue_more": _waiting(user, jobs.EXCESS),
            "deviations": _waiting(user, job_inspections.DOC),
            "boms": _waiting(user, boms.DOC),
            "routings": _waiting(user, routings.DOC),
        },
        "made_today": made,
        "moulds_due": len(reports.moulds_due(user)),
    }


def supervisor(user: User) -> dict:
    """The shop-floor supervisor's home page (owner, 12 Nov 2026), for their own sections only:
    the shifts open for entry and how far each report has got, reports still to finish (draft
    or returned), today's and tomorrow's plan on their machines, what was made yesterday and
    today (approved reports), and the moulds due for maintenance."""
    from datetime import timedelta

    from . import plan, shift_reports
    from .models import ShiftReport

    today = timezone.localdate()
    to_finish = (
        shift_reports.visible(user)
        .filter(
            status__in=[ShiftReport.Status.DRAFT, ShiftReport.Status.RETURNED],
            day__gte=today - timedelta(days=7),
        )
        .select_related("section", "shift")
        .order_by("-day", "section__code")
    )
    return {
        "today": today,
        "shifts": shift_reports.open_shifts(user),
        "to_finish": [
            {
                "id": r.pk,
                "section": r.section.code,
                "day": r.day,
                "shift": r.shift.code,
                "status": r.status,
            }
            for r in to_finish
        ],
        "plan": plan.mine(user)["entries"],
        "made_yesterday": reports.daily(user, today - timedelta(days=1), today - timedelta(days=1))[
            "total"
        ],
        "made_today": reports.daily(user, today, today)["total"],
        "moulds_due": reports.moulds_due(user),
    }
