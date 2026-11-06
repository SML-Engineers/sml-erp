"""Payroll run API (P2B-06). HR prepares; the Director approves; the Accountant sees the
totals only (no one's personal figures). The APIT tables and EPF/ETF rates are kept by the
Accountant (accounting area)."""

from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.permissions import AreaAccess

from . import credits, employees, payroll, payslips, periods, returns
from .models import PayComponent, PayrollRun, StaffCredit, StatutoryRate, TaxBand, TaxTable
from .payroll import PayrollError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _name(user):
    return (user.full_name or user.email) if user else None


class _Payroll(APIView):
    permission_classes = [AreaAccess]
    access_area = "hr_payroll"
    access_write_level = "view"  # the service decides who prepares and who approves

    def check_permissions(self, request):
        super().check_permissions(request)
        user = request.user
        # HR and the Director; the Accountant sees the totals only. Not section supervisors.
        if not (employees.can_view(user) or effective_access(user).has("accounting", "view")):
            self.permission_denied(request, message="Only HR, the Director and the Accountant.")


def _runs(user):
    return PayrollRun.objects.filter(division__in=division_scope(user)).select_related(
        "division", "created_by", "journal_entry"
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
        "number": run.number,
        "journal": run.journal_entry.number if run.journal_entry_id else "",
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
        "can_email_payslips": run.status == run.Status.APPROVED and employees.can_edit(user),
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


# --- Payslips (P2B-08) ---------------------------------------------------------------------------


class PayslipPdfView(_Payroll):
    """All payslips of an approved payroll in one PDF to print, or one (?employee=<id>)."""

    def get(self, request, pk):
        run = get_object_or_404(_runs(request.user), pk=pk)
        try:
            lines = payslips.lines_of(request.user, run)
        except payslips.PayslipError as error:
            return _error(error)
        one = request.query_params.get("employee")
        if one:
            lines = lines.filter(employee_id=one)
        lines = list(lines)
        if not lines:
            return _error("There is no payslip to print.")
        name = (
            payslips.filename(lines[0])
            if one
            else f"payslips-{run.division.code}-{run.month:%Y-%m}.pdf"
        )
        with audit_context("payslips_printed", name):
            content = payslips.render(lines)
        response = HttpResponse(content, content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{name}"'
        return response


class PayslipEmailView(_Payroll):
    def post(self, request, pk):
        run = get_object_or_404(_runs(request.user), pk=pk)
        try:
            result = payslips.email(request.user, run, request.data.get("employees") or None)
        except payslips.PayslipError as error:
            return _error(error)
        return Response(result)


# --- Statutory returns (P2B-09) ------------------------------------------------------------------


class ReturnView(_Payroll):
    """GET /payroll-returns/<kind>/ with ?month= (epf, etf, apit), ?year=&half= (etf-half) or
    ?year= (apit-year, apit-certificates); &download=xlsx or pdf."""

    def get(self, request, kind):
        q = request.query_params
        try:
            if kind == "apit-certificates":
                content = returns.certificates(request.user, q.get("year"), q.get("employee"))
                with audit_context("apit_certificates_printed", f"{q.get('year')}"):
                    response = HttpResponse(content, content_type="application/pdf")
                response["Content-Disposition"] = (
                    f'inline; filename="apit-certificates-{q.get("year")}.pdf"'
                )
                return response
            if kind in returns.KINDS:
                report = getattr(returns, kind)(request.user, q.get("month"))
                stem = f"{kind}-{q.get('month')}"
            elif kind == "etf-half":
                report = returns.etf_half_year(request.user, q.get("year"), q.get("half"))
                stem = f"etf-{q.get('year')}-h{q.get('half')}"
            elif kind == "apit-year":
                report = returns.apit_year(request.user, q.get("year"))
                stem = f"apit-{q.get('year')}"
            else:
                return _error("Unknown return.")
        except returns.ReturnError as error:
            return _error(error)
        wanted = q.get("download")
        if wanted == "xlsx":
            response = HttpResponse(
                returns.xlsx(report),
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            response["Content-Disposition"] = f'attachment; filename="{stem}.xlsx"'
            return response
        if wanted == "pdf":
            response = HttpResponse(returns.pdf(report), content_type="application/pdf")
            response["Content-Disposition"] = f'inline; filename="{stem}.pdf"'
            return response
        return Response(report.as_dict())


# --- Advances and loans (P2B-10) -----------------------------------------------------------------


def _who(e) -> dict:
    return {"id": e.pk, "number": e.number, "name": e.full_name}


def _credit(c: StaffCredit, user) -> dict:
    state = approvals.state_of(credits.DOC, c.pk)
    got = credits.recovered(c)
    mine = c.created_by_id == user.pk
    hr = employees.can_edit(user)
    return {
        "id": c.pk,
        "number": c.number,
        "employee": _who(c.employee),
        "kind": c.kind,
        "kind_label": c.get_kind_display(),
        "amount": f"{c.amount:.2f}",
        "interest": f"{c.interest:.2f}",
        "months": c.months,
        "instalment": f"{c.instalment:.2f}",
        "first_month": c.first_month.isoformat()[:7],
        "reason": c.reason,
        "status": c.status,
        "status_label": c.get_status_display(),
        "returned": bool(state and state.status == state.Status.RETURNED),
        "recovered": f"{got:.2f}",
        "balance": f"{(c.total - got) if c.status == c.Status.APPROVED else 0:.2f}",
        "created_by": _name(c.created_by),
        "can_edit": c.status == c.Status.DRAFT and mine,
        "can_submit": c.status == c.Status.DRAFT and mine,
        "can_withdraw": c.status in (c.Status.DRAFT, c.Status.AWAITING) and hr,
        "can_approve": credits.can_approve(user, c),
    }


class _Credits(_Payroll):
    def check_permissions(self, request):
        super().check_permissions(request)
        if not employees.can_view(request.user):
            self.permission_denied(request, message="Only HR and the Director.")


def _credits_for(user):
    return StaffCredit.objects.filter(employee__in=employees.visible(user)).select_related(
        "employee", "created_by"
    )


class StaffCreditListView(_Credits):
    def get(self, request):
        user = request.user
        people = employees.visible(user).filter(is_active=True).order_by("number")
        return Response(
            {
                "results": [_credit(c, user) for c in _credits_for(user)],
                "employees": [_who(e) for e in people],
                "first_month": periods.pay_month_of(timezone.localdate()).isoformat()[:7],
                "can_record": employees.can_edit(user),
            }
        )

    def post(self, request):
        e = get_object_or_404(employees.visible(request.user), pk=request.data.get("employee"))
        try:
            c = credits.record(request.user, e, request.data)
        except credits.CreditError as error:
            return _error(error)
        return Response(_credit(c, request.user), status=status.HTTP_201_CREATED)


CREDIT_ACTIONS = {
    "submit": credits.submit,
    "approve": credits.approve,
    "return": credits.send_back,
    "reject": credits.reject,
    "withdraw": credits.withdraw,
}


class StaffCreditDetailView(_Credits):
    def put(self, request, pk):
        c = get_object_or_404(_credits_for(request.user), pk=pk)
        try:
            c = credits.edit(request.user, c, request.data)
        except credits.CreditError as error:
            return _error(error)
        return Response(_credit(c, request.user))


class StaffCreditActionView(_Credits):
    def post(self, request, pk, action):
        c = get_object_or_404(_credits_for(request.user), pk=pk)
        act = CREDIT_ACTIONS.get(action)
        if act is None:
            return _error("Unknown action.")
        try:
            act(request.user, c, request.data.get("reason", ""))
        except credits.CreditError as error:
            return _error(error)
        c = _credits_for(request.user).get(pk=pk)
        return Response(_credit(c, request.user))
