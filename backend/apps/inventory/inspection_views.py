"""Incoming inspection API (P16-08). Rules live in inspections.py; every endpoint needs
Quality access and shows only the user's divisions."""

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.permissions import AreaAccess

from . import inspections
from .inspections import InspectionError, ParameterInput, ResultInput
from .models import IncomingInspection, InspectionAttachment, InspectionPlan, Item


class _Quality(APIView):
    """Changes are checked by the service: the QC Inspector inspects, the Director approves
    deviations through the approval engine."""

    permission_classes = [AreaAccess]
    access_area = "quality"
    access_write_level = "view"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _s(value) -> str | None:
    return None if value is None else str(value)


# --- Plans ---------------------------------------------------------------------------------


def _plan(p: InspectionPlan) -> dict:
    return {
        "id": p.id,
        "name": p.name,
        "item": None
        if p.item_id is None
        else {"id": p.item_id, "code": p.item.code, "name": p.item.name},
        "category": p.category,
        "sampling": p.sampling,
        "sample_value": _s(p.sample_value),
        "notes": p.notes,
        "is_active": p.is_active,
        "parameters": [
            {
                "name": q.name,
                "kind": q.kind,
                "minimum": _s(q.minimum),
                "maximum": _s(q.maximum),
                "unit": q.unit,
                "critical": q.critical,
            }
            for q in p.parameters.all()
        ],
    }


class ParameterIn(serializers.Serializer):
    name = serializers.CharField(max_length=100, allow_blank=True)
    kind = serializers.CharField(max_length=10)
    minimum = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    maximum = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    unit = serializers.CharField(max_length=20, required=False, allow_blank=True)
    critical = serializers.BooleanField(required=False, default=False)


class PlanIn(serializers.Serializer):
    name = serializers.CharField(max_length=100, allow_blank=True)
    item = serializers.IntegerField(required=False, allow_null=True)
    category = serializers.CharField(max_length=20, required=False, allow_blank=True)
    sampling = serializers.CharField(max_length=10)
    sample_value = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    notes = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False, default=True)
    parameters = ParameterIn(many=True)


def _save_plan(request, plan):
    body = PlanIn(data=request.data)
    body.is_valid(raise_exception=True)
    values = dict(body.validated_data)
    parameters = [ParameterInput(**row) for row in values.pop("parameters")]
    item_id = values.pop("item", None)
    values["item"] = Item.objects.filter(pk=item_id).first() if item_id else None
    if item_id and values["item"] is None:
        return _error("There is no such item.")
    try:
        saved = inspections.save_plan(request.user, plan, values, parameters)
    except InspectionError as error:
        return _error(error)
    return Response(
        _plan(InspectionPlan.objects.select_related("item").get(pk=saved.pk)),
        status=status.HTTP_200_OK if plan else status.HTTP_201_CREATED,
    )


class PlanListView(_Quality):
    def get(self, request):
        rows = InspectionPlan.objects.select_related("item").prefetch_related("parameters")
        if request.query_params.get("include_inactive") not in ("1", "true"):
            rows = rows.filter(is_active=True)
        return Response(
            {
                "can_edit": inspections.can_inspect(request.user),
                "categories": [{"value": v, "label": label} for v, label in Item.Category.choices],
                "plans": [_plan(p) for p in rows],
            }
        )

    def post(self, request):
        return _save_plan(request, None)


class PlanDetailView(_Quality):
    def get(self, request, pk):
        return Response(_plan(get_object_or_404(InspectionPlan, pk=pk)))

    def put(self, request, pk):
        return _save_plan(request, get_object_or_404(InspectionPlan, pk=pk))


# --- Inspections ---------------------------------------------------------------------------


def _summary(i: IncomingInspection) -> dict:
    line = i.line
    grn = line.receipt
    return {
        "id": i.id,
        "status": i.status,
        "decision": i.decision,
        "automatic": i.automatic,
        "grn": {"id": grn.id, "number": grn.number, "receipt_date": grn.receipt_date},
        "division": grn.division.code,
        "supplier": {"code": grn.supplier.code, "name": grn.supplier.name},
        "item": {"code": line.item.code, "name": line.item.name, "unit": line.item.unit},
        "good_quantity": str(inspections.good_quantity(line)),
        "accepted_quantity": str(i.accepted_quantity),
        "rejected_quantity": str(i.rejected_quantity),
        "inspector": i.inspector.full_name if i.inspector_id else None,
        "started_at": i.started_at,
        "decided_at": i.decided_at,
    }


def _detail(i: IncomingInspection, user) -> dict:
    line = i.line
    rejected = set(i.rejected_packages.values_list("package_id", flat=True))
    return _summary(i) | {
        "line_no": line.line_no,
        "received_quantity": str(line.received_quantity),
        "damaged_quantity": str(line.damaged_quantity),
        "plan": None if i.plan_id is None else {"id": i.plan_id, "name": i.plan.name},
        "sample_size": i.sample_size,
        "notes": i.notes,
        "reason": i.reason,
        "results": [
            {
                "position": r.position,
                "name": r.name,
                "kind": r.kind,
                "minimum": _s(r.minimum),
                "maximum": _s(r.maximum),
                "unit": r.unit,
                "critical": r.critical,
                "value": _s(r.value),
                "passed": r.passed,
                "within_limits": r.within_limits,
                "notes": r.notes,
            }
            for r in i.results.all()
        ],
        "packages": [
            {
                "package_no": p.package_no,
                "lot_no": p.lot_no,
                "supplier_lot": p.supplier_lot,
                "quantity": _s(p.quantity),
                "damaged": p.damaged,
                "rejected": p.pk in rejected,
            }
            for p in line.packages.all()
        ],
        "attachments": [
            {
                "id": a.id,
                "file_name": a.file_name,
                "uploaded_by": a.uploaded_by.full_name,
                "uploaded_at": a.uploaded_at,
            }
            for a in i.attachments.select_related("uploaded_by").order_by("uploaded_at", "id")
        ],
        "can_edit": inspections.can_edit(user, i),
        "can_attach": inspections.can_inspect(user) and not i.automatic,
        "can_approve": inspections.can_approve(user, i),
        "history": [
            {
                "action": row.action,
                "action_label": row.get_action_display(),
                "by": row.user.full_name,
                "at": row.acted_at,
                "reason": row.reason,
            }
            for row in approvals.history(inspections.DOC, i.pk)
        ],
    }


def _get(user, pk) -> IncomingInspection:
    return get_object_or_404(inspections.visible(user), pk=pk)


def _fresh(i: IncomingInspection, user) -> dict:
    return _detail(inspections.visible(user).get(pk=i.pk), user)


class QueueView(_Quality):
    """GRN lines waiting for QC, with the inspection already started on any of them."""

    def get(self, request):
        rows = list(inspections.queue(request.user)[:1000])
        started = {
            i.line_id: i
            for i in IncomingInspection.objects.filter(line__in=rows).only(
                "id", "line_id", "status"
            )
        }
        return Response(
            {
                "can_inspect": inspections.can_inspect(request.user),
                "lines": [
                    {
                        "line": line.id,
                        "grn": {
                            "id": line.receipt_id,
                            "number": line.receipt.number,
                            "receipt_date": line.receipt.receipt_date,
                        },
                        "division": line.receipt.division.code,
                        "supplier": line.receipt.supplier.name,
                        "item": {
                            "code": line.item.code,
                            "name": line.item.name,
                            "unit": line.item.unit,
                        },
                        "good_quantity": str(inspections.good_quantity(line)),
                        "packages": line.packages.count(),
                        "inspection": None
                        if line.id not in started
                        else {"id": started[line.id].id, "status": started[line.id].status},
                    }
                    for line in rows
                ],
            }
        )


class InspectionListView(_Quality):
    def get(self, request):
        rows = inspections.visible(request.user).filter(automatic=False)
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("waiting") == "me":
            ids = [s.document_id for s in approvals.waiting_for(request.user, inspections.DOC)]
            rows = rows.filter(pk__in=ids)
        return Response([_summary(i) for i in rows[:2000]])

    def post(self, request):
        line = inspections.queue(request.user).filter(pk=request.data.get("line")).first()
        if line is None:
            return _error("This GRN line is not waiting for QC.")
        try:
            inspection = inspections.start(request.user, line)
        except InspectionError as error:
            return _error(error)
        return Response(_fresh(inspection, request.user), status=status.HTTP_201_CREATED)


class ResultIn(serializers.Serializer):
    position = serializers.IntegerField()
    value = serializers.CharField(max_length=30, required=False, allow_blank=True, allow_null=True)
    passed = serializers.BooleanField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True)


class InspectionIn(serializers.Serializer):
    results = ResultIn(many=True)
    accepted_quantity = serializers.CharField(max_length=30, required=False, allow_null=True)
    rejected_packages = serializers.ListField(
        child=serializers.IntegerField(), required=False, max_length=1000
    )
    notes = serializers.CharField(required=False, allow_blank=True)


class InspectionDetailView(_Quality):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))

    def put(self, request, pk):
        inspection = _get(request.user, pk)
        body = InspectionIn(data=request.data)
        body.is_valid(raise_exception=True)
        values = body.validated_data
        try:
            inspections.save(
                request.user,
                inspection,
                results=[ResultInput(**row) for row in values["results"]],
                accepted_quantity=values.get("accepted_quantity"),
                rejected_packages=values.get("rejected_packages"),
                notes=values.get("notes"),
            )
        except InspectionError as error:
            return _error(error)
        return Response(_fresh(inspection, request.user))


class _Action(_Quality):
    def _run(self, request, pk, action):
        inspection = _get(request.user, pk)
        try:
            action(inspection)
        except InspectionError as error:
            return _error(error)
        return Response(_fresh(inspection, request.user))


def _text(request, name: str) -> str:
    return str(request.data.get(name, ""))


class DecideView(_Action):
    def post(self, request, pk):
        return self._run(
            request,
            pk,
            lambda i: inspections.decide(
                request.user, i, _text(request, "decision"), _text(request, "reason")
            ),
        )


class ApproveView(_Action):
    def post(self, request, pk):
        return self._run(
            request,
            pk,
            lambda i: inspections.approve_deviation(request.user, i, _text(request, "comment")),
        )


class ReturnView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda i: inspections.send_back(request.user, i, _text(request, "reason"))
        )


class AttachmentListView(_Quality):
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        inspection = _get(request.user, pk)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose a file to add.")
        try:
            inspections.add_attachment(request.user, inspection, uploaded)
        except InspectionError as error:
            return _error(error)
        return Response(_fresh(inspection, request.user), status=status.HTTP_201_CREATED)


class AttachmentDetailView(_Quality):
    def get(self, request, pk, attachment_pk):
        inspection = _get(request.user, pk)
        attachment = get_object_or_404(
            InspectionAttachment, pk=attachment_pk, inspection=inspection
        )
        return FileResponse(
            attachment.file.open("rb"),
            content_type=attachment.content_type,
            filename=attachment.file_name,
            as_attachment=request.query_params.get("download") in ("1", "true"),
        )

    def delete(self, request, pk, attachment_pk):
        inspection = _get(request.user, pk)
        attachment = get_object_or_404(
            InspectionAttachment, pk=attachment_pk, inspection=inspection
        )
        try:
            inspections.remove_attachment(request.user, attachment)
        except InspectionError as error:
            return _error(error)
        return Response(_fresh(inspection, request.user))
