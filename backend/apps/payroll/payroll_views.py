"""Payroll run API (P2B-06). HR prepares; the Director approves; the Accountant sees the
totals only (no one's personal figures). The APIT tables and EPF/ETF rates are kept by the
Accountant (accounting area)."""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.access import AreaAccess, division_scope
from apps.core.audit import audit_context

from . import employees, payroll, periods
from .models import PayComponent, PayrollRun, StatutoryRate, TaxBand, TaxTable
from .payroll import PayrollError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _name(user):
    return (user.get_full_name() or user.email) if user else None


class _Payroll(APIView):
    permission_classes = [AreaAccess]
    access_area = "hr_payroll"
    access_write_level = "view"  # the service decides who prepares and who approves


def _runs(user):
    return PayrollRun.objects.filter(division__in=division_scope(user)).select_related(
        "division", "created_by"
    )


def _t(values: dict) -> dict:
    return {k: (f"{v:.2f}" if isinstance(v, Decimal) else v) for k, v in values.items()}


def _run(run: PayrollRun, user, detail=False) -> dict:
    out = {
        "id": run.pk,
        "division": run.division.code,
        "month": run.month.isoformat()[:7],
        "period": periods.label(run.month),
        "status": run.status,
        "status_label": run.get_status_display(),
        "created_by": _name(run.created_by),
        "worked_out_at": run.worked_out_at,
        "approved_at": run.approved_at,
        "totals": _t(payroll.totals(run)),
    }
    if not detail:
        return out
    state = approvals.state_of(payroll.DOC, run.pk)
    hr = payroll.can_prepare(user)
    sees_people = employees.can_view(user)
    s = run.statutory
    out |= {
        "statutory": {
            "epf_employee": f"{s.epf_employee}",
            "epf_employer": f"{s.epf_employer}",
            "etf": f"{s.etf}",
        },
        "returned": bool(state and state.status == state.Status.RETURNED),
        "history": [
            {
                "action": h.get_action_display(),
                "user": _name(h.user),
                "reason": h.reason,
                "at": h.acted_at,
            }
            for h in (approvals.history(payroll.DOC, run.pk) if state else [])
        ],
        "can_work_out": hr and run.status == run.Status.DRAFT,
        "can_submit": hr and run.status == run.Status.DRAFT,
        "can_approve": payroll.can_approve(user, run),
        "sees_people": sees_people,
        "lines": [],
        "entries": [],
        "components": [],
    }
    if sees_people:
        out["lines"] = [
            {
                "employee": {
                    "id": x.employee_id,
                    "number": x.employee.number,
                    "name": x.employee.full_name,
                    "category": x.employee.category,
                },
                "days_employed": x.days_employed,
                "days_in_period": x.days_in_period,
                "day_rate": f"{x.day_rate:.2f}",
                "hourly_rate": f"{x.hourly_rate:.2f}",
                "gross": f"{x.gross:.2f}",
                "epf_earnings": f"{x.epf_earnings:.2f}",
                "apit_earnings": f"{x.apit_earnings:.2f}",
                "epf_employee": f"{x.epf_employee:.2f}",
                "epf_employer": f"{x.epf_employer:.2f}",
                "etf": f"{x.etf:.2f}",
                "apit": f"{x.apit:.2f}",
                "deductions": f"{x.deductions:.2f}",
                "net": f"{x.net:.2f}",
                "items": [
                    {
                        "code": i.code,
                        "name": i.name,
                        "kind": i.kind,
                        "amount": f"{i.amount:.2f}",
                        "basis": i.basis,
                    }
                    for i in x.items.all()
                ],
            }
            for x in run.lines.select_related("employee").prefetch_related("items")
        ]
        out["entries"] = [
            {
                "employee": x.employee_id,
                "component": x.component.code,
                "amount": f"{x.amount:.2f}",
                "note": x.note,
            }
            for x in run.entries.select_related("component")
        ]
        out["components"] = [
            {"code": c.code, "name": c.name, "kind": c.kind}
            for c in PayComponent.objects.filter(is_active=True)
        ]
    return out


class PayrollListView(_Payroll):
    def get(self, request):
        return Response(
            {
                "results": [_run(r, request.user) for r in _runs(request.user)],
                "divisions": [d.code for d in division_scope(request.user)],
                "last_month": periods.last_pay_month().isoformat()[:7],
                "can_prepare": payroll.can_prepare(request.user),
            }
        )

    def post(self, request):
        try:
            data = request.data
            run = payroll.prepare(request.user, data.get("division"), data.get("month"))
        except PayrollError as error:
            return _error(error)
        return Response(_run(run, request.user, True), status=status.HTTP_201_CREATED)


class PayrollDetailView(_Payroll):
    def get(self, request, pk):
        run = get_object_or_404(_runs(request.user), pk=pk)
        return Response(_run(run, request.user, True))


ACTIONS = {
    "submit": payroll.submit,
    "approve": payroll.approve,
    "return": payroll.send_back,
    "reject": payroll.reject,
}


class PayrollActionView(_Payroll):
    def post(self, request, pk, action):
        run = get_object_or_404(_runs(request.user), pk=pk)
        try:
            if action == "work-out":
                run = payroll.recompute(request.user, run)
            elif action == "entries":
                run = payroll.set_entry(
                    request.user,
                    run,
                    request.data.get("employee"),
                    request.data.get("component"),
                    request.data.get("amount"),
                    request.data.get("note", ""),
                )
            elif action in ACTIONS:
                run = ACTIONS[action](request.user, run, request.data.get("reason", ""))
            else:
                return _error("Unknown action.")
        except PayrollError as error:
            return _error(error)
        run.refresh_from_db()
        return Response(_run(run, request.user, True))


# --- APIT tables and EPF/ETF rates (the Accountant) ----------------------------------------------


class _Rates(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "manage"


def _table(t: TaxTable) -> dict:
    return {
        "id": t.pk,
        "kind": t.kind,
        "kind_label": t.get_kind_display(),
        "effective_from": t.effective_from,
        "reason": t.reason,
        "bands": [
            {
                "up_to": None if b.up_to is None else f"{b.up_to:.2f}",
                "rate": f"{b.rate}",
                "constant": f"{b.constant:.2f}",
            }
            for b in t.bands.all()
        ],
    }


def _number(value, label) -> Decimal:
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise PayrollError(f"The {label} is a number.") from None
    if not number.is_finite() or number < 0:
        raise PayrollError(f"The {label} is 0 or more.")
    return number


def _day(value) -> date:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        raise PayrollError("Give the date it applies from.") from None


def _paid_after(day: date) -> bool:
    """Would a rate from `day` change a payroll already sent or approved?"""
    return PayrollRun.objects.filter(
        period_end__gte=day, status__in=[PayrollRun.Status.AWAITING, PayrollRun.Status.APPROVED]
    ).exists()


class TaxTableView(_Rates):
    def get(self, request):
        return Response(
            {
                "tables": [_table(t) for t in TaxTable.objects.prefetch_related("bands")],
                "statutory": [
                    {
                        "effective_from": s.effective_from,
                        "epf_employee": f"{s.epf_employee}",
                        "epf_employer": f"{s.epf_employer}",
                        "etf": f"{s.etf}",
                        "reason": s.reason,
                    }
                    for s in StatutoryRate.objects.all()
                ],
            }
        )

    def post(self, request):
        """A new APIT table from a date: bands in order, the last one open (no upper limit)."""
        data = request.data
        try:
            kind = data.get("kind")
            if kind not in TaxTable.Kind.values:
                raise PayrollError("Choose Table 01 (primary) or Table 07 (secondary).")
            starts = _day(data.get("effective_from"))
            reason = " ".join(str(data.get("reason") or "").split())
            if not reason:
                raise PayrollError("Give the source (e.g. the IRD table and year).")
            bands = data.get("bands") or []
            if not isinstance(bands, list) or not bands:
                raise PayrollError("Give the bands.")
            rows, last = [], Decimal(-1)
            for i, b in enumerate(bands):
                up_to = b.get("up_to")
                top = i == len(bands) - 1
                if top and up_to not in (None, ""):
                    raise PayrollError("The last band has no upper limit.")
                if not top:
                    up_to = _number(up_to, "upper limit")
                    if up_to <= last:
                        raise PayrollError("Each band's upper limit is above the one before.")
                    last = up_to
                else:
                    up_to = None
                rate = _number(b.get("rate"), "rate")
                if rate > 100:
                    raise PayrollError("A rate is at most 100%.")
                rows.append((up_to, rate, _number(b.get("constant") or 0, "amount deducted")))
            if _paid_after(starts):
                raise PayrollError("A payroll from that date is already sent or approved.")
            with audit_context("apit_table_added", reason), transaction.atomic():
                if TaxTable.objects.filter(kind=kind, effective_from=starts).exists():
                    raise PayrollError("There is already a table of that kind from that date.")
                table = TaxTable.objects.create(
                    kind=kind, effective_from=starts, reason=reason[:200], created_at=timezone.now()
                )
                TaxBand.objects.bulk_create(
                    TaxBand(table=table, up_to=u, rate=r, constant=c) for u, r, c in rows
                )
        except PayrollError as error:
            return _error(error)
        return Response(_table(table), status=status.HTTP_201_CREATED)
