"""Voucher lists and reports (spec 4.4 "Lists and reports", backlog P1-08): the Voucher
List, the Approved List, the Amendments List, vouchers pending by approver and age, and the
approval history of any voucher. Each gives rows for the screen and for Excel and PDF."""

from datetime import date

from django.db.models import OuterRef, Subquery
from django.utils import timezone

from apps.core import approvals
from apps.core.exports import Column
from apps.core.models import ApprovalLog, ApprovalState, User

from . import services
from .models import Voucher

DOC = services.DOC
APPROVED = (Voucher.Status.DIRECTOR_APPROVED, Voucher.Status.PARTLY_PAID, Voucher.Status.PAID)
AGE_BANDS = ((2, "0–2 days"), (7, "3–7 days"), (14, "8–14 days"), (None, "15 days or more"))


def _payee(v: Voucher) -> str:
    if v.payee_id:
        return v.payee.name
    return f"→ {v.transfer_to.code}" if v.transfer_to_id else ""


# --- Voucher List ---------------------------------------------------------------------------

LIST_COLUMNS = [
    Column("number", "Number", width=1.3),
    Column("voucher_date", "Date", "date"),
    Column("type", "Type", width=1.2),
    Column("division", "Division", width=0.6),
    Column("payee", "Payee", width=2),
    Column("status", "Status", width=1.2),
    Column("created_by", "Created by", width=1.2),
    Column("total_amount", "Total (LKR)", "money"),
]


def list_rows(vouchers) -> list[dict]:
    return [
        {
            "number": v.number,
            "voucher_date": v.voucher_date,
            "type": v.voucher_type.name,
            "division": v.division.code,
            "payee": _payee(v),
            "status": v.get_status_display(),
            "created_by": v.created_by.full_name,
            "total_amount": f"{v.total_amount:.2f}",
        }
        for v in vouchers
    ]


# --- Approved List --------------------------------------------------------------------------

APPROVED_COLUMNS = [
    Column("number", "Number", width=1.3),
    Column("voucher_date", "Date", "date"),
    Column("type", "Type", width=1.2),
    Column("division", "Division", width=0.6),
    Column("payee", "Payee", width=2),
    Column("approved_at", "Approved", "datetime", width=1.2),
    Column("approved_by", "Approved by", width=1.2),
    Column("status", "Status", width=1),
    Column("total_amount", "Approved (LKR)", "money"),
    Column("paid", "Paid (LKR)", "money"),
]


def approved(user: User, *, start: date | None, end: date | None, division: str = "") -> list:
    """Vouchers approved by the Director, by the date of that approval."""
    last = ApprovalLog.objects.filter(
        document_type=DOC, document_id=OuterRef("pk"), action=ApprovalLog.Action.APPROVE
    ).order_by("-acted_at", "-id")
    rows = (
        services.visible(user)
        .filter(status__in=APPROVED)
        .annotate(
            approved_at=Subquery(last.values("acted_at")[:1]),
            approved_by=Subquery(last.values("user__full_name")[:1]),
        )
        .select_related("voucher_type", "division", "payee", "transfer_to")
        .order_by("-approved_at", "-id")
    )
    if division:
        rows = rows.filter(division__code=division.upper())
    from apps.payments.services import paid_on

    result = []
    for v in rows:
        day = timezone.localtime(v.approved_at).date() if v.approved_at else None
        if (start and (day is None or day < start)) or (end and (day is None or day > end)):
            continue
        result.append(
            {
                "id": v.pk,
                "number": v.number,
                "voucher_date": v.voucher_date,
                "type": v.voucher_type.name,
                "division": v.division.code,
                "payee": _payee(v),
                "approved_at": v.approved_at,
                "approved_by": v.approved_by or "",
                "status": v.get_status_display(),
                "status_code": v.status,
                "total_amount": f"{v.total_amount:.2f}",
                "paid": f"{paid_on(v):.2f}",
            }
        )
    return result


# --- Pending by approver and age -------------------------------------------------------------

PENDING_COLUMNS = [
    Column("number", "Number", width=1.3),
    Column("type", "Type", width=1.2),
    Column("division", "Division", width=0.6),
    Column("payee", "Payee", width=2),
    Column("waiting_for", "Waiting for", width=1.1),
    Column("approvers", "Who can approve", width=1.6),
    Column("since", "Waiting since", "datetime", width=1.2),
    Column("days", "Days", "number", width=0.5),
    Column("band", "Age", width=0.9),
    Column("total_amount", "Total (LKR)", "money"),
]


def _band(days: int) -> str:
    for limit, name in AGE_BANDS:
        if limit is None or days <= limit:
            return name
    return AGE_BANDS[-1][1]


def pending(user: User, *, division: str = "", level: int | None = None) -> list[dict]:
    """Vouchers waiting for approval: at which level, who can approve, since when (the last
    action on the voucher) and how long, oldest first. Optionally one division or level."""
    vouchers = services.visible(user).select_related(
        "voucher_type", "division", "payee", "transfer_to"
    )
    if division:
        vouchers = vouchers.filter(division__code=division.upper())
    visible = {v.pk: v for v in vouchers}
    states = ApprovalState.objects.filter(
        document_type=DOC, status=ApprovalState.Status.IN_PROGRESS, document_id__in=visible
    )
    if level is not None:
        states = states.filter(current_level=level)
    now = timezone.now()
    rows = []
    for state in states:
        v = visible[state.document_id]
        last = approvals.history(DOC, v.pk).order_by("-acted_at", "-id").first()
        since = last.acted_at if last else v.submitted_at or v.created_at
        days = (timezone.localtime(now).date() - timezone.localtime(since).date()).days
        step = next(s for s in state.route if s["level"] == state.current_level)
        rows.append(
            {
                "id": v.pk,
                "number": v.number,
                "type": v.voucher_type.name,
                "division": v.division.code,
                "payee": _payee(v),
                "level": state.current_level,
                "waiting_for": f"L{state.current_level} {step['role_name']}",
                "approvers": ", ".join(p.full_name for p in approvals.approvers(state)),
                "since": since,
                "days": days,
                "band": _band(days),
                "total_amount": f"{v.total_amount:.2f}",
            }
        )
    rows.sort(key=lambda r: (r["since"], r["number"]))
    return rows


def pending_summary(rows: list[dict]) -> list[dict]:
    """Counts and totals per approver level and age band, for the top of the report."""
    summary: dict[tuple, dict] = {}
    for row in rows:
        key = (row["level"], row["waiting_for"])
        entry = summary.setdefault(
            key,
            {"waiting_for": row["waiting_for"], "count": 0, "bands": {b: 0 for _, b in AGE_BANDS}},
        )
        entry["count"] += 1
        entry["bands"][row["band"]] += 1
    return [summary[k] for k in sorted(summary)]


# --- Approval history of one voucher -----------------------------------------------------------

HISTORY_COLUMNS = [
    Column("acted_at", "When", "datetime", width=1.2),
    Column("round", "Round", "number", width=0.5),
    Column("level", "Level", "number", width=0.5),
    Column("action", "Action", width=1.3),
    Column("user", "By", width=1.3),
    Column("reason", "Reason / comment", width=3),
]


def history(voucher: Voucher) -> list[dict]:
    rows = [
        {
            "acted_at": row.acted_at,
            "round": row.round,
            "level": row.level,
            "action": services.history_row(row)[1],
            "user": row.user.full_name,
            "reason": services.history_row(row)[2],
        }
        for row in approvals.history(DOC, voucher.pk)
    ]
    for cancel in voucher.cancellations.all():
        for row in approvals.history(services.CANCEL_DOC, cancel.pk):
            rows.append(
                {
                    "acted_at": row.acted_at,
                    "round": row.round,
                    "level": row.level,
                    "action": f"Cancellation: {row.get_action_display().lower()}",
                    "user": row.user.full_name,
                    "reason": row.reason,
                }
            )
    rows.sort(key=lambda r: r["acted_at"])
    return rows
