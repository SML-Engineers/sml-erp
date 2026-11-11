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
