"""Fixed asset API (P2-19). Rules live in services.py; Accounting access is needed."""

from datetime import date

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.masters.models import CompanyAccount, Machine

from . import services
from .models import AssetClass, DepreciationRun
from .services import AssetError


class _Assets(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _m(value) -> str:
    return f"{value:.2f}"


def _class(c: AssetClass) -> dict:
    today = date.today()
    current = services.rate_on(c, today)
    return {
        "id": c.pk,
        "code": c.code,
        "name": c.name,
        "cost_account": c.cost_account.number,
        "accumulated_account": c.accumulated_account.number,
        "expense_account": c.expense_account.number,
        "is_active": c.is_active,
        "current": None
        if current is None
        else {
            "method": current.method,
            "rate": f"{current.rate.normalize():f}",
            "from": current.effective_from,
        },
        "rates": [
            {
                "id": r.pk,
                "effective_from": r.effective_from,
                "method": r.method,
                "rate": f"{r.rate.normalize():f}",
                "reason": r.reason,
            }
            for r in c.rates.all()
        ],
    }


class ClassListView(_Assets):
    def get(self, request):
        rows = AssetClass.objects.select_related(
            "cost_account", "accumulated_account", "expense_account"
        ).prefetch_related("rates")
        return Response([_class(c) for c in rows])


class ClassRateView(_Assets):
    def post(self, request, pk):
        found = get_object_or_404(AssetClass, pk=pk)
        try:
            services.add_rate(
                request.user,
                found,
                effective_from=_day(request.data.get("effective_from")) or date.today(),
                method=str(request.data.get("method") or ""),
                rate=request.data.get("rate", ""),
                reason=str(request.data.get("reason") or ""),
            )
        except AssetError as error:
            return _error(error)
        return Response(_class(AssetClass.objects.get(pk=pk)), status=status.HTTP_201_CREATED)


def _asset(a) -> dict:
    charged = services.accumulated(a)
    return {
        "id": a.pk,
        "code": a.code,
        "name": a.name,
        "asset_class": {
            "id": a.asset_class_id,
            "code": a.asset_class.code,
            "name": a.asset_class.name,
        },
        "division": a.division.code,
        "machine": None if a.machine_id is None else {"id": a.machine_id, "code": a.machine.code},
        "serial_no": a.serial_no,
        "supplier": a.supplier,
        "acquisition_date": a.acquisition_date,
        "depreciation_from": a.depreciation_from,
        "cost": _m(a.cost),
        "residual_value": _m(a.residual_value),
        "accumulated": _m(charged),
        "book_value": _m(a.cost - charged),
        "status": a.status,
        "disposed_on": a.disposed_on,
        "proceeds": _m(a.proceeds),
        "disposal_reason": a.disposal_reason,
        "shot_count": a.shot_count,
        "notes": a.notes,
    }


class AssetListView(_Assets):
    def get(self, request):
        rows = services.visible(request.user).select_related("asset_class", "division", "machine")
        if request.query_params.get("status"):
            rows = rows.filter(status=request.query_params["status"])
        return Response([_asset(a) for a in rows[:3000]])

    def post(self, request):
        data = request.data
        try:
            made = services.register(
                request.user,
                asset_class=AssetClass.objects.filter(pk=data.get("asset_class") or 0).first(),
                division=Division.objects.filter(
                    code=str(data.get("division") or "").upper()
                ).first(),
                name=str(data.get("name") or ""),
                acquisition_date=_day(data.get("acquisition_date")),
                cost=data.get("cost", ""),
                depreciation_from=_day(data.get("depreciation_from")),
                residual_value=data.get("residual_value") or "0",
                opening_accumulated=data.get("opening_accumulated") or "0",
                machine=Machine.objects.filter(pk=data.get("machine") or 0)
                .select_related("section")
                .first(),
                serial_no=str(data.get("serial_no") or ""),
                supplier=str(data.get("supplier") or ""),
                notes=str(data.get("notes") or ""),
            )
        except AssetError as error:
            return _error(error)
        return Response(_asset(made), status=status.HTTP_201_CREATED)


class AssetDetailView(_Assets):
    def get(self, request, pk):
        found = get_object_or_404(services.visible(request.user), pk=pk)
        body = _asset(found)
        body["depreciation"] = [
            {
                "month_end": line.run.month_end,
                "rate": f"{line.rate.normalize():f}",
                "method": line.method,
                "amount": _m(line.amount),
                "posted": line.run.status == DepreciationRun.Status.POSTED,
            }
            for line in found.depreciation.select_related("run").order_by("run__month_end")
        ]
        return Response(body)

    def patch(self, request, pk):
        found = get_object_or_404(services.visible(request.user), pk=pk)
        try:
            saved = services.update(request.user, found, dict(request.data))
        except AssetError as error:
            return _error(error)
        return Response(_asset(saved))


class DisposeView(_Assets):
    def post(self, request, pk):
        found = get_object_or_404(services.visible(request.user), pk=pk)
        account = CompanyAccount.objects.filter(pk=request.data.get("account") or 0).first()
        try:
            saved = services.dispose(
                request.user,
                found,
                disposed_on=_day(request.data.get("disposed_on")),
                proceeds=request.data.get("proceeds") or "0",
                account=account,
                reason=str(request.data.get("reason") or ""),
            )
        except AssetError as error:
            return _error(error)
        return Response(_asset(saved))


def _run(r: DepreciationRun) -> dict:
    return {
        "id": r.pk,
        "month_end": r.month_end,
        "status": r.status,
        "total": _m(r.total),
        "journal_entry": r.journal_entry.number if r.journal_entry_id else None,
        "prepared_by": r.prepared_by.full_name,
        "posted_by": r.posted_by.full_name if r.posted_by_id else None,
        "lines": [
            {
                "asset": {"id": x.asset_id, "code": x.asset.code, "name": x.asset.name},
                "division": x.asset.division.code,
                "method": x.method,
                "rate": f"{x.rate.normalize():f}",
                "book_value_before": _m(x.book_value_before),
                "amount": _m(x.amount),
            }
            for x in r.lines.select_related("asset__division")
        ],
    }


class RunListView(_Assets):
    def get(self, request):
        rows = DepreciationRun.objects.select_related("journal_entry", "prepared_by", "posted_by")
        upcoming = services.next_month()
        return Response({"next_month": upcoming, "runs": [_run(r) for r in rows[:120]]})

    def post(self, request):
        try:
            made = services.prepare(
                request.user, _day(request.data.get("month_end")) or date.today()
            )
        except AssetError as error:
            return _error(error)
        return Response(_run(made), status=status.HTTP_201_CREATED)


class RunActionView(_Assets):
    action = "post"

    def post(self, request, pk):
        run = get_object_or_404(DepreciationRun, pk=pk)
        try:
            if self.action == "post":
                run = services.post(request.user, run)
            else:
                services.discard(request.user, run)
                return Response(status=status.HTTP_204_NO_CONTENT)
        except AssetError as error:
            return _error(error)
        return Response(_run(run))
