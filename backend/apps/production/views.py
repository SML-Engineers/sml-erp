"""Production API (Phase 3). P3-01: moulds."""

from datetime import date

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import division_scope
from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.inventory.models import Item
from apps.masters.models import Machine

from . import (
    boms,
    closing,
    costs,
    job_cards,
    job_inspections,
    jobs,
    labels,
    maintenance,
    moulds,
    oee,
    orders,
    plan,
    profit,
    rates,
    reasons,
    reports,
    routings,
    shift_approval,
    shift_reports,
    subcontract,
    transfers,
    wip,
)
from .boms import BomError
from .job_inspections import JobInspectionError
from .jobs import JobError
from .maintenance import MaintenanceError
from .models import (
    Bom,
    BomLine,
    CostRate,
    JobExcess,
    JobInspection,
    JobOrder,
    Mould,
    ProductionOrder,
    ProductionSetting,
    ReasonCode,
    Routing,
    ShiftCorrection,
    SubcontractDispatch,
)
from .moulds import ImportRefused, MouldError
from .orders import OrderError
from .plan import PlanError
from .rates import RateError
from .reasons import ReasonError
from .routings import RoutingError
from .shift_reports import ShiftReportError
from .subcontract import SubcontractError
from .transfers import TransferError

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _error(error, code=status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"detail": str(error)}, status=code)


class _Planning(APIView):
    permission_classes = [AreaAccess]
    access_area = "production_planning"
    access_write_level = "enter"


class MouldListView(_Planning):
    def get(self, request):
        found = moulds.search(
            request.user,
            request.query_params.get("q", "").strip(),
            request.query_params.get("status", ""),
        )
        return Response(
            {
                "results": [moulds.payload(m) for m in found],
                "can_edit": moulds.can_edit(request.user),
                "statuses": [{"value": v, "label": label} for v, label in Mould.Status.choices],
                # The moulding machines a mould can be set against.
                "machines": [
                    {"code": m.code, "name": m.name}
                    for m in Machine.objects.filter(
                        section__section_type="moulding",
                        section__division__in=division_scope(request.user),
                    ).exclude(status=Machine.Status.RETIRED)
                ],
            }
        )

    def post(self, request):
        try:
            mould = moulds.create(request.user, request.data)
        except MouldError as error:
            return _error(error)
        return Response(moulds.payload(mould), status=status.HTTP_201_CREATED)


class MouldDetailView(_Planning):
    def _mould(self, request, pk) -> Mould:
        return get_object_or_404(moulds.visible(request.user), pk=pk)

    def get(self, request, pk):
        return Response(moulds.payload(self._mould(request, pk)))

    def patch(self, request, pk):
        try:
            mould = moulds.update(request.user, self._mould(request, pk), request.data)
        except MouldError as error:
            return _error(error)
        return Response(moulds.payload(mould))

    def delete(self, request, pk):
        try:
            moulds.delete(request.user, self._mould(request, pk))
        except MouldError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MouldFitView(_Planning):
    """Whether a mould fits a machine: ?machine=CODE."""

    def get(self, request, pk):
        mould = get_object_or_404(moulds.visible(request.user), pk=pk)
        machine = get_object_or_404(Machine, code=request.query_params.get("machine", "").upper())
        return Response({"machine": machine.code, "warnings": moulds.fit(mould, machine)})


class MouldExportView(_Planning):
    def get(self, request):
        response = HttpResponse(moulds.export_workbook(request.user), content_type=XLSX)
        today = timezone.localdate().isoformat()
        response["Content-Disposition"] = f'attachment; filename="moulds-{today}.xlsx"'
        return response


class MouldImportView(_Planning):
    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose an Excel file to import.")
        dry_run = str(request.data.get("dry_run", "true")).lower() not in ("false", "0", "no")
        try:
            result = moulds.import_workbook(request.user, uploaded.read(), dry_run=dry_run)
        except ImportRefused as refused:
            return Response(
                {"detail": "Nothing was imported.", "errors": refused.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(result)


class MouldLabelsView(_Planning):
    """QR labels: ?ids=1,2,3 (all shown moulds when empty)."""

    def get(self, request):
        found = moulds.visible(request.user).filter(status__in=["active", "maintenance"])
        ids = [int(x) for x in request.query_params.get("ids", "").split(",") if x.isdigit()]
        if ids:
            found = found.filter(pk__in=ids)
        response = HttpResponse(
            labels.render(found.select_related("customer").order_by("code")),
            content_type="application/pdf",
        )
        response["Content-Disposition"] = 'inline; filename="mould-labels.pdf"'
        return response


# --- Reasons and settings (P3-02) ----------------------------------------------------------------


class _Settings(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"


class ProductionSetupView(_Settings):
    """The reasons of every division and the settings: in force, future and past."""

    def get(self, request):
        found = ReasonCode.objects.select_related("division")
        today = timezone.localdate()
        current = reasons.setting_on(today)
        return Response(
            {
                "reasons": [reasons.row(r) for r in found],
                "divisions": list(
                    Division.objects.filter(code__in=["IM", "WS"]).values_list("code", flat=True)
                ),
                "settings": [reasons.setting_row(s) for s in ProductionSetting.objects.all()],
                "current": current.pk,
                "can_manage": reasons.can_manage(request.user),
            }
        )

    def post(self, request):
        try:
            reasons.add_setting(request.user, request.data)
        except ReasonError as error:
            return _error(error)
        return self.get(request)


class ReasonsView(_Settings):
    def post(self, request):
        try:
            reasons.add(request.user, request.data)
        except ReasonError as error:
            return _error(error)
        return ProductionSetupView().get(request)


class ReasonView(_Settings):
    def patch(self, request, pk):
        try:
            reasons.change(request.user, get_object_or_404(ReasonCode, pk=pk), request.data)
        except ReasonError as error:
            return _error(error)
        return ProductionSetupView().get(request)

    def delete(self, request, pk):
        try:
            reasons.remove(request.user, get_object_or_404(ReasonCode, pk=pk))
        except ReasonError as error:
            return _error(error)
        return ProductionSetupView().get(request)


# --- Routings (P3-03) ----------------------------------------------------------------------------


class RoutingListView(_Planning):
    access_write_level = "view"  # the service checks who prepares

    def get(self, request):
        query = request.query_params
        found = routings.search(query.get("q", "").strip(), query.get("status", ""))
        return Response(
            {
                "results": [routings.payload(r, request.user) for r in found],
                "can_prepare": routings.can_prepare(request.user),
                "statuses": [{"value": v, "label": label} for v, label in Routing.Status.choices],
            }
        )

    def post(self, request):
        try:
            routing = routings.create(request.user, request.data)
        except RoutingError as error:
            return _error(error)
        return Response(routings.payload(routing, request.user), status=status.HTTP_201_CREATED)


class RoutingDetailView(_Planning):
    access_write_level = "view"

    def get(self, request, pk):
        return Response(routings.payload(get_object_or_404(Routing, pk=pk), request.user))

    def patch(self, request, pk):
        try:
            routing = routings.update(request.user, get_object_or_404(Routing, pk=pk), request.data)
        except RoutingError as error:
            return _error(error)
        return Response(routings.payload(routing, request.user))

    def delete(self, request, pk):
        try:
            routings.delete(request.user, get_object_or_404(Routing, pk=pk))
        except RoutingError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RoutingActionView(_Planning):
    """submit, approve, send_back ({reason}) or copy ({item}: another part; blank: same)."""

    access_write_level = "view"

    def post(self, request, pk, action):
        routing = get_object_or_404(Routing, pk=pk)
        try:
            if action == "submit":
                routing = routings.submit(request.user, routing)
            elif action == "copy":
                routing = routings.copy(request.user, routing, request.data.get("item") or None)
            else:
                routing = routings.decide(
                    request.user, routing, action, request.data.get("reason", "")
                )
        except RoutingError as error:
            return _error(error)
        return Response(routings.payload(routing, request.user))


class RoutingExportView(_Planning):
    def get(self, request):
        response = HttpResponse(routings.export_workbook(), content_type=XLSX)
        today = timezone.localdate().isoformat()
        response["Content-Disposition"] = f'attachment; filename="routings-{today}.xlsx"'
        return response


class RoutingImportView(_Planning):
    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose an Excel file to import.")
        dry_run = str(request.data.get("dry_run", "true")).lower() not in ("false", "0", "no")
        try:
            result = routings.import_workbook(request.user, uploaded.read(), dry_run=dry_run)
        except routings.ImportRefused as refused:
            return Response(
                {"detail": "Nothing was imported.", "errors": refused.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(result)


# --- Bills of materials (P3-04) ------------------------------------------------------------------


class BomListView(_Planning):
    access_write_level = "view"  # the service checks who prepares

    def get(self, request):
        query = request.query_params
        found = boms.search(query.get("q", "").strip(), query.get("status", ""))
        return Response(
            {
                "results": [boms.payload(b, request.user) for b in found],
                "can_prepare": boms.can_prepare(request.user),
                "statuses": [{"value": v, "label": label} for v, label in Bom.Status.choices],
                "line_types": [{"value": v, "label": label} for v, label in BomLine.Type.choices],
            }
        )

    def post(self, request):
        try:
            bom = boms.create(request.user, request.data)
        except BomError as error:
            return _error(error)
        return Response(boms.payload(bom, request.user), status=status.HTTP_201_CREATED)


class BomDetailView(_Planning):
    access_write_level = "view"

    def get(self, request, pk):
        return Response(boms.payload(get_object_or_404(Bom, pk=pk), request.user))

    def patch(self, request, pk):
        try:
            bom = boms.update(request.user, get_object_or_404(Bom, pk=pk), request.data)
        except BomError as error:
            return _error(error)
        return Response(boms.payload(bom, request.user))

    def delete(self, request, pk):
        try:
            boms.delete(request.user, get_object_or_404(Bom, pk=pk))
        except BomError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class BomActionView(_Planning):
    """submit, approve, send_back ({reason}) or copy ({item}: another item; blank: same)."""

    access_write_level = "view"

    def post(self, request, pk, action):
        bom = get_object_or_404(Bom, pk=pk)
        try:
            if action == "submit":
                bom = boms.submit(request.user, bom)
            elif action == "copy":
                bom = boms.copy(request.user, bom, request.data.get("item") or None)
            else:
                bom = boms.decide(request.user, bom, action, request.data.get("reason", ""))
        except BomError as error:
            return _error(error)
        return Response(boms.payload(bom, request.user))


class BomCompareView(_Planning):
    """?a=<id>&b=<id>"""

    def get(self, request):
        a = get_object_or_404(Bom, pk=request.query_params.get("a") or 0)
        b = get_object_or_404(Bom, pk=request.query_params.get("b") or 0)
        return Response(
            {
                "a": f"{a.item.code} rev {a.revision}",
                "b": f"{b.item.code} rev {b.revision}",
                "lines": boms.compare(a, b),
            }
        )


class BomWhereUsedView(_Planning):
    """?item=CODE"""

    def get(self, request):
        item = get_object_or_404(Item, code=request.query_params.get("item", "").strip().upper())
        return Response(boms.where_used(item))


class BomMachiningCalcView(_Planning):
    """The machining calculator: ?component=CODE&bar_length_mm=&cut_length_mm=&facing_mm=&saw_mm="""

    def get(self, request):
        query = request.query_params
        try:
            component = boms._item(query.get("component"))
            values = {
                f: boms._decimal(query.get(f), f.replace("_", " "), 1)
                for f in ("bar_length_mm", "cut_length_mm", "facing_mm", "saw_mm")
            }
            result = boms.machining(component, **values)
        except BomError as error:
            return _error(error)
        return Response(result | {"quantity": f"{result['quantity'].normalize():f}"})


class BomExportView(_Planning):
    def get(self, request):
        response = HttpResponse(boms.export_workbook(), content_type=XLSX)
        today = timezone.localdate().isoformat()
        response["Content-Disposition"] = f'attachment; filename="boms-{today}.xlsx"'
        return response


class BomImportView(_Planning):
    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose an Excel file to import.")
        dry_run = str(request.data.get("dry_run", "true")).lower() not in ("false", "0", "no")
        try:
            result = boms.import_workbook(request.user, uploaded.read(), dry_run=dry_run)
        except boms.ImportRefused as refused:
            return Response(
                {"detail": "Nothing was imported.", "errors": refused.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(result)


class _Rates(APIView):
    """P3-05: everyone in production planning reads the cost rates; the service lets only
    the Accountant (Accounting, enter) change them."""

    permission_classes = [AreaAccess]
    access_area = "production_planning"
    access_write_level = "view"


class CostRatesView(_Rates):
    def get(self, request):
        return Response(rates.overview(request.user))

    def post(self, request):
        try:
            rates.add(request.user, request.data)
        except RateError as error:
            return _error(error)
        return Response(rates.overview(request.user), status=status.HTTP_201_CREATED)


class CostRatesAcceptView(_Rates):
    def post(self, request):
        try:
            rates.accept(request.user, request.data)
        except RateError as error:
            return _error(error)
        return Response(rates.overview(request.user))


class CostRateView(_Rates):
    def delete(self, request, pk):
        try:
            rates.remove(request.user, get_object_or_404(CostRate, pk=pk))
        except RateError as error:
            return _error(error)
        return Response(rates.overview(request.user))


def _refresh(user, order) -> None:
    """P3-16: the Accountant brings an order's costs up to date."""
    if not costs.can_see(user) or not costs.summary(order, user)["can_refresh"]:
        raise JobError("The Accountant refreshes order costs.")
    try:
        costs.sync(order)
    except costs.CostError as error:
        raise JobError(str(error)) from None


class OrderProfitView(APIView):
    """P3-17: the order dashboard: every open order's estimate, actual and forecast with a
    red, amber or green status; filters by division, customer, section and due date."""

    permission_classes = [AreaAccess]
    access_area = "job_profitability"
    access_also_area = "accounting"

    def get(self, request):
        q = request.query_params
        filters = {k: q.get(k, "") for k in ("state", "division", "customer", "section", "due_by")}
        try:
            return Response(profit.dashboard(request.user, filters))
        except profit.ProfitError as error:
            return _error(error)


class MouldingProfitView(APIView):
    """P3-17: per machine and mould: cycle time, material per good piece, rejects and the
    margin per 1,000 pieces, from `start` to `end` (this month by default)."""

    permission_classes = [AreaAccess]
    access_area = "job_profitability"
    access_also_area = "accounting"

    def get(self, request):
        today = timezone.localdate()
        try:
            start = date.fromisoformat(request.query_params.get("start") or "")
        except ValueError:
            start = today.replace(day=1)
        try:
            end = date.fromisoformat(request.query_params.get("end") or "")
        except ValueError:
            end = today
        if end < start:
            return Response(
                {"detail": "The end date is before the start."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            rows = profit.moulding_view(request.user, start, end)
        except profit.ProfitError as error:
            return _error(error)
        return Response({"start": start, "end": end, "rows": rows})


class ClosedProfitView(APIView):
    """P3-20: closed orders' margin by order, customer, part, mould or division, and the
    estimate accuracy by element, for a date range (this year by default)."""

    permission_classes = [AreaAccess]
    access_area = "job_profitability"
    access_also_area = "accounting"

    def get(self, request, kind):
        today = timezone.localdate()
        q = request.query_params
        try:
            start = date.fromisoformat(q.get("start") or today.replace(month=1, day=1).isoformat())
            end = date.fromisoformat(q.get("end") or today.isoformat())
        except ValueError:
            return Response({"detail": "Give the dates as YYYY-MM-DD."}, status=400)
        if end < start:
            return Response({"detail": "The end date is before the start."}, status=400)
        if not costs.can_see(request.user):
            return Response({"detail": "You do not have access to order costs."}, status=403)
        try:
            if kind == "margins":
                body = closing.margins(request.user, start, end, q.get("by") or "customer")
            elif kind == "accuracy":
                body = closing.accuracy(request.user, start, end)
            else:
                return Response({"detail": "Unknown report."}, status=404)
        except profit.ProfitError as error:
            return _error(error)
        return Response({"start": start, "end": end, **body})


class PartActualsView(APIView):
    """P3-18: what closed orders of a part actually took (kg and machine hours per piece,
    setup hours, cycle time), for the next quotation."""

    permission_classes = [AreaAccess]
    access_area = "job_profitability"
    access_also_area = "accounting"

    def get(self, request):
        code = (request.query_params.get("item") or "").strip().upper()
        item = Item.objects.filter(code=code).first()
        if item is None:
            return Response(
                {"detail": f"There is no item {code}." if code else "Give the part's item code."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(closing.part_actuals(item))


class OeeView(APIView):
    """P3-19: OEE per moulding machine for a date range (this month by default): totals to
    compare machines, with each machine's months, days and shifts."""

    permission_classes = [AreaAccess]
    access_area = "production_approvals"

    def get(self, request):
        today = timezone.localdate()
        q = request.query_params
        try:
            start = date.fromisoformat(q.get("start") or today.replace(day=1).isoformat())
            end = date.fromisoformat(q.get("end") or today.isoformat())
        except ValueError:
            return Response({"detail": "Give the dates as YYYY-MM-DD."}, status=400)
        try:
            return Response(oee.report(request.user, start, end, q.get("section", "")))
        except oee.OeeError as error:
            return _error(error)


class ProductionReportView(APIView):
    """P3-20: the production reports (daily, rejects, downtime, jobs, material, moulds) for a
    date range (this month by default) in the user's sections."""

    permission_classes = [AreaAccess]
    access_area = "production_approvals"

    def get(self, request, kind):
        today = timezone.localdate()
        q = request.query_params
        try:
            start = date.fromisoformat(q.get("start") or today.replace(day=1).isoformat())
            end = date.fromisoformat(q.get("end") or today.isoformat())
        except ValueError:
            return Response({"detail": "Give the dates as YYYY-MM-DD."}, status=400)
        section = q.get("section", "")
        user = request.user
        try:
            if kind == "daily":
                body = reports.daily(user, start, end, section)
            elif kind == "rejects":
                body = reports.rejects(user, start, end, q.get("by") or "reason", section)
            elif kind == "downtime":
                body = reports.downtime(user, start, end, section)
            elif kind == "jobs":
                body = reports.jobs(user, start, end)
            elif kind == "material":
                body = reports.material(user, start, end, section)
            elif kind == "moulds":
                body = {"rows": reports.moulds_due(user)}
            elif kind == "sections":
                body = {"sections": reports.sections(user)}
            else:
                return Response({"detail": "Unknown report."}, status=404)
        except reports.ReportError as error:
            return _error(error)
        return Response({"start": start, "end": end, **body})


class WipReportView(APIView):
    """P3-16: the month-end WIP report: open jobs against the Work in progress account, and
    machine time charged to no order."""

    permission_classes = [AreaAccess]
    access_area = "accounting"

    def get(self, request):
        return Response(wip.report(request.query_params.get("month")))


class OrderCostsRefreshView(APIView):
    """P3-16: bring every open order's costs up to date (also run at month end)."""

    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "enter"

    def post(self, request):
        return Response({"entries": costs.sync_open(request.user)})


class _Orders(APIView):
    """P3-06: production planning works the orders; the stores person and purchasing read
    them to raise purchase requests for shortages. The services check who does what."""

    permission_classes = [AreaAccess]
    access_area = "production_planning"
    access_also_area = "stores"
    access_write_level = "view"


class ProductionOrderListView(_Orders):
    def get(self, request):
        p = request.query_params
        found = orders.search(
            request.user, p.get("q", "").strip(), p.get("status", ""), p.get("item", "").strip()
        )
        return Response(
            {
                "results": [orders.row(o) for o in found[:500]],
                "can_plan": orders.can_plan(request.user),
                "statuses": [
                    {"value": v, "label": label} for v, label in ProductionOrder.Status.choices
                ],
            }
        )

    def post(self, request):
        try:
            order = orders.create(request.user, request.data)
        except OrderError as error:
            return _error(error)
        return Response(orders.payload(order, request.user), status=status.HTTP_201_CREATED)


class ProductionOrderDetailView(_Orders):
    def _order(self, request, pk) -> ProductionOrder:
        return get_object_or_404(orders.visible(request.user), pk=pk)

    def get(self, request, pk):
        return Response(orders.payload(self._order(request, pk), request.user))

    def patch(self, request, pk):
        try:
            order = orders.update(request.user, self._order(request, pk), request.data)
        except OrderError as error:
            return _error(error)
        return Response(orders.payload(order, request.user))


class ProductionOrderActionView(_Orders):
    def post(self, request, pk, action):
        order = get_object_or_404(orders.visible(request.user), pk=pk)
        try:
            if action == "release":
                order = orders.release(request.user, order)
            elif action == "complete":
                order = orders.complete(request.user, order)
            elif action == "close":
                order = orders.close(request.user, order)
            elif action == "cancel":
                order = orders.cancel(request.user, order, request.data.get("reason", ""))
            elif action == "refresh-costs":
                try:
                    _refresh(request.user, order)
                except JobError as error:
                    raise OrderError(str(error)) from None
            elif action == "purchase-request":
                made = orders.raise_request(request.user, order)
                body = orders.payload(order, request.user)
                return Response(body | {"purchase_request": {"id": made.pk, "number": made.number}})
            else:
                return _error("Unknown action.", status.HTTP_404_NOT_FOUND)
        except OrderError as error:
            return _error(error)
        return Response(orders.payload(order, request.user))


class ProductionOrderSalesLinesView(_Orders):
    def get(self, request):
        return Response(
            {"results": orders.sales_lines(request.user, request.query_params.get("q", "").strip())}
        )


class ProductionOrderWhereUsedView(_Orders):
    def get(self, request):
        code = request.query_params.get("item", "").strip().upper()
        item = get_object_or_404(Item, code=code)
        return Response(orders.where_used(request.user, item))


class _Plan(APIView):
    """P3-07: production planning works the plan; supervisors (shop floor) read their own
    sections' plan. The service checks who may change it."""

    permission_classes = [AreaAccess]
    access_area = "production_planning"
    access_also_area = "shop_floor"
    access_write_level = "view"


class PlanView(_Plan):
    def get(self, request):
        p = request.query_params
        try:
            return Response(plan.board(request.user, p.get("start"), p.get("days")))
        except PlanError as error:
            return _error(error)

    def post(self, request):
        try:
            entry = plan.add(request.user, request.data)
        except PlanError as error:
            return _error(error)
        return Response(plan.entry_row(entry, []), status=status.HTTP_201_CREATED)


class PlanEntryView(_Plan):
    def _entry(self, request, pk):
        return get_object_or_404(plan.visible(request.user), pk=pk)

    def patch(self, request, pk):
        try:
            entry = plan.change(request.user, self._entry(request, pk), request.data)
        except PlanError as error:
            return _error(error)
        return Response(plan.entry_row(entry, []))

    def delete(self, request, pk):
        try:
            plan.remove(request.user, self._entry(request, pk))
        except PlanError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PlanCopyView(_Plan):
    def post(self, request):
        try:
            source = date.fromisoformat(str(request.data.get("source", "")))
            target = date.fromisoformat(str(request.data.get("target", "")))
        except ValueError:
            return _error("Give the day to copy and the day to copy it to.")
        try:
            copied = plan.copy_day(request.user, source, target)
        except PlanError as error:
            return _error(error)
        return Response({"copied": copied})


class MyPlanView(_Plan):
    def get(self, request):
        return Response(plan.mine(request.user))


class _Reports(APIView):
    """P3-08: supervisors (shop floor) enter their sections' shift reports; the Production
    Manager reads them (production approvals). The service checks who may change them."""

    permission_classes = [AreaAccess]
    access_area = "shop_floor"
    access_also_area = "production_approvals"
    access_write_level = "view"


def _report_body(report, user) -> dict:
    return shift_reports.payload(report, user) | shift_approval.approval_fields(report, user)


class ShiftReportListView(_Reports):
    def get(self, request):
        user = request.user
        recent = shift_reports.visible(user)[:60]
        return Response(
            {
                "open": shift_reports.open_shifts(user),
                "recent": [shift_reports.row(r) for r in recent],
                "can_enter": shift_reports.can_enter(user),
            }
        )

    def post(self, request):
        try:
            report = shift_reports.open_report(request.user, request.data)
        except ShiftReportError as error:
            return _error(error)
        return Response(_report_body(report, request.user), status=status.HTTP_201_CREATED)


class ShiftReportDetailView(_Reports):
    def _report(self, request, pk):
        return get_object_or_404(shift_reports.visible(request.user), pk=pk)

    def get(self, request, pk):
        return Response(_report_body(self._report(request, pk), request.user))

    def put(self, request, pk):
        try:
            report = shift_reports.save(request.user, self._report(request, pk), request.data)
        except shift_reports.ShiftReportConflict as error:
            # P3-21: the current report goes back so the supervisor can compare.
            current = self._report(request, pk)
            return Response(
                {"detail": str(error), "current": _report_body(current, request.user)},
                status=status.HTTP_409_CONFLICT,
            )
        except ShiftReportError as error:
            return _error(error)
        return Response(_report_body(report, request.user))


class ShiftReportSubmitView(_Reports):
    def post(self, request, pk):
        report = get_object_or_404(shift_reports.visible(request.user), pk=pk)
        try:
            report = shift_reports.submit(request.user, report)
        except ShiftReportError as error:
            return _error(error)
        return Response(_report_body(report, request.user))


class ShiftReportDecideView(_Reports):
    """P3-09: the Production Manager approves or returns a submitted report."""

    def post(self, request, pk):
        report = get_object_or_404(shift_reports.visible(request.user), pk=pk)
        try:
            report = shift_approval.decide(
                request.user, report, request.data.get("action", ""), request.data.get("reason", "")
            )
        except ShiftReportError as error:
            return _error(error)
        return Response(_report_body(report, request.user))


class ShiftCorrectionAskView(_Reports):
    def post(self, request, pk):
        report = get_object_or_404(shift_reports.visible(request.user), pk=pk)
        try:
            shift_approval.ask(request.user, report, request.data.get("reason", ""))
        except ShiftReportError as error:
            return _error(error)
        return Response(_report_body(report, request.user), status=status.HTTP_201_CREATED)


class ShiftCorrectionDecideView(_Reports):
    def post(self, request, pk):
        fix = get_object_or_404(
            ShiftCorrection.objects.filter(report__in=shift_reports.visible(request.user)), pk=pk
        )
        try:
            shift_approval.decide_fix(
                request.user, fix, request.data.get("action", ""), request.data.get("reason", "")
            )
        except ShiftReportError as error:
            return _error(error)
        report = shift_reports.visible(request.user).get(pk=fix.report_id)
        return Response(_report_body(report, request.user))


class MouldMaintenanceView(APIView):
    """P3-10: production planning reads the moulds due and their maintenance; the
    Production Manager or the Planner records it (checked in the service)."""

    permission_classes = [AreaAccess]
    access_area = "production_planning"
    access_write_level = "view"

    def get(self, request):
        return Response(
            maintenance.overview(request.user, request.query_params.get("mould", "").strip())
        )

    def post(self, request):
        try:
            maintenance.record(request.user, request.data)
        except MaintenanceError as error:
            return _error(error)
        return Response(maintenance.overview(request.user), status=status.HTTP_201_CREATED)


class _Jobs(APIView):
    """P3-11: the Planner works job orders; the stores person issues and takes back their
    material; the Production Manager decides requests to issue more. The services check who
    does what."""

    permission_classes = [AreaAccess]
    access_area = "production_planning"
    access_also_area = "stores"
    access_write_level = "view"


class JobOrderListView(_Jobs):
    def get(self, request):
        p = request.query_params
        found = jobs.search(
            request.user, p.get("q", "").strip(), p.get("status", ""), p.get("purpose", "")
        )
        return Response(
            {
                "results": [jobs.row(j) for j in found[:500]],
                "can_plan": jobs.can_plan(request.user),
                "divisions": [d.code for d in division_scope(request.user)],
                "statuses": [{"value": v, "label": x} for v, x in JobOrder.Status.choices],
                "purposes": [{"value": v, "label": x} for v, x in JobOrder.Purpose.choices],
            }
        )

    def post(self, request):
        try:
            job = jobs.create(request.user, request.data)
        except JobError as error:
            return _error(error)
        return Response(jobs.payload(job, request.user), status=status.HTTP_201_CREATED)


class JobOrderDetailView(_Jobs):
    def get(self, request, pk):
        return Response(
            jobs.payload(get_object_or_404(jobs.visible(request.user), pk=pk), request.user)
        )

    def patch(self, request, pk):
        job = get_object_or_404(jobs.visible(request.user), pk=pk)
        try:
            job = jobs.update(request.user, job, request.data)
        except JobError as error:
            return _error(error)
        return Response(jobs.payload(job, request.user))


class JobOrderActionView(_Jobs):
    def post(self, request, pk, action):
        job = get_object_or_404(jobs.visible(request.user), pk=pk)
        d = request.data
        try:
            if action == "release":
                job = jobs.release(request.user, job)
            elif action == "complete":
                job = jobs.complete(request.user, job)
            elif action == "close":
                job = jobs.close(request.user, job)
            elif action == "cancel":
                job = jobs.cancel(request.user, job, d.get("reason", ""))
            elif action == "issue":
                made = jobs.issue(request.user, job, d)
                body = jobs.payload(job, request.user)
                return Response(body | {"stock_issue": made.number}, status=status.HTTP_201_CREATED)
            elif action == "return":
                made = jobs.give_back(request.user, job, d)
                body = jobs.payload(job, request.user)
                return Response(body | {"stock_issue": made.number}, status=status.HTTP_201_CREATED)
            elif action == "ask-more":
                jobs.ask_more(request.user, job, d)
            elif action == "send-out":
                made = subcontract.send_out(request.user, job, d)
                body = jobs.payload(job, request.user)
                return Response(
                    body | {"dispatch": {"id": made.pk, "number": made.number}},
                    status=status.HTTP_201_CREATED,
                )
            elif action == "receive-back":
                subcontract.receive_back(request.user, job, d)
            elif action == "inspect":
                job_inspections.start(request.user, job, d)
            elif action == "transfer":
                transfers.post(request.user, job, d.get("notes", ""))
            elif action == "refresh-costs":
                _refresh(request.user, job)
            else:
                return _error("Unknown action.", status.HTTP_404_NOT_FOUND)
        except (JobError, SubcontractError, JobInspectionError, TransferError) as error:
            return _error(error)
        return Response(jobs.payload(job, request.user))


class JobOrderLotsView(_Jobs):
    def get(self, request, pk):
        job = get_object_or_404(jobs.visible(request.user), pk=pk)
        p = request.query_params
        try:
            return Response(
                {"results": jobs.lots_for(request.user, job, p.get("store"), p.get("item", ""))}
            )
        except JobError as error:
            return _error(error)


class JobOrderSalesLinesView(_Jobs):
    def get(self, request):
        return Response(
            {"results": orders.sales_lines(request.user, request.query_params.get("q", "").strip())}
        )


class JobExcessWaitingView(_Jobs):
    def get(self, request):
        return Response({"results": jobs.waiting(request.user)})


class JobExcessDecideView(_Jobs):
    def post(self, request, pk):
        excess = get_object_or_404(
            JobExcess.objects.filter(job__division__in=division_scope(request.user)), pk=pk
        )
        try:
            excess = jobs.decide_more(
                request.user, excess, request.data.get("action", ""), request.data.get("reason", "")
            )
        except JobError as error:
            return _error(error)
        return Response({"status": excess.status})


class JobCardsView(_Jobs):
    """P3-12: the printed job cards of a released job, one per operation, with QR codes."""

    def get(self, request, pk):
        job = get_object_or_404(jobs.visible(request.user), pk=pk)
        if job.status not in (JobOrder.Status.RELEASED, JobOrder.Status.COMPLETED):
            return _error("Job cards are printed for a released job.")
        response = HttpResponse(job_cards.render(job), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="job-cards-{job.number}.pdf"'
        return response


class SubcontractNoteView(_Jobs):
    """P3-13: the note that goes with parts sent out to a supplier."""

    def get(self, request, pk):
        dispatch = get_object_or_404(
            SubcontractDispatch.objects.filter(job__in=jobs.visible(request.user)).select_related(
                "job__item", "operation", "supplier"
            ),
            pk=pk,
        )
        response = HttpResponse(subcontract.render(dispatch), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{dispatch.number}.pdf"'
        return response


class JobInspectionActionView(_Jobs):
    """P3-14: the QC Inspector enters and finishes; the Production Manager decides; the
    Director approves a deviation on a failed critical check."""

    access_also_area = "quality"

    def post(self, request, pk, action):
        inspection = get_object_or_404(
            JobInspection.objects.filter(job__in=jobs.visible(request.user)), pk=pk
        )
        d = request.data
        try:
            if action == "save":
                job_inspections.save(request.user, inspection, d)
            elif action == "finish":
                job_inspections.save(request.user, inspection, d)
                job_inspections.finish(request.user, inspection)
            elif action == "decide":
                job_inspections.decide(request.user, inspection, d)
            elif action == "director":
                job_inspections.director_decides(
                    request.user, inspection, d.get("action", ""), d.get("reason", "")
                )
            else:
                return _error("Unknown action.", status.HTTP_404_NOT_FOUND)
        except JobInspectionError as error:
            return _error(error)
        return Response(jobs.payload(inspection.job, request.user))
