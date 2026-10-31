"""Quotations API (P15-03). Rules live in services.py; every endpoint checks Sales access and
returns only quotations the user may see."""

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting.models import TaxCode
from apps.core import approvals
from apps.core.models import ApprovalState, Division
from apps.core.permissions import AreaAccess
from apps.masters.models import Customer, CustomerContact, Machine, Material

from . import costing, services, workflow
from .models import Quotation, QuotationFile
from .services import BreakInput, LineInput, SalesError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class _Sales(APIView):
    permission_classes = [AreaAccess]
    access_area = "sales"
    access_write_level = "enter"


def _get(user, pk) -> Quotation:
    return get_object_or_404(services.visible(user), pk=pk)


# --- Output -----------------------------------------------------------------------------


def _summary(q: Quotation) -> dict:
    return {
        "id": q.id,
        "number": q.number,
        "revision": q.revision,
        "status": q.status,
        "quote_date": q.quote_date,
        "valid_until": q.valid_until,
        "division": q.division.code,
        "customer": {"id": q.customer_id, "code": q.customer.code, "name": q.customer.name},
        "enquiry_ref": q.enquiry_ref,
        "currency": q.currency.code,
        "total_amount": str(q.total_amount),
        "total_lkr": str(q.total_lkr),
        "created_by": q.created_by.full_name,
    }


def _detail(q: Quotation, user) -> dict:
    body = _summary(q)
    contact = q.contact
    body |= {
        "contact": None
        if contact is None
        else {"id": contact.id, "name": contact.name, "email": contact.email},
        "exchange_rate": str(q.exchange_rate),
        "rate_date": q.rate_date,
        "payment_terms": q.payment_terms,
        "delivery_lead_time": q.delivery_lead_time,
        "incoterm": q.incoterm,
        "notes": q.notes,
        "subtotal": str(q.subtotal),
        "tax_total": str(q.tax_total),
        "created_by_id": q.created_by_id,
        "created_at": q.created_at,
        "lines": [
            {
                "id": line.id,
                "line_no": line.line_no,
                "description": line.description,
                "drawing_no": line.drawing_no,
                "drawing_rev": line.drawing_rev,
                "quantity": str(line.quantity),
                "unit": line.unit,
                "min_order_qty": None if line.min_order_qty is None else str(line.min_order_qty),
                "unit_price": str(line.unit_price),
                "is_tooling": line.is_tooling,
                "tax_code": line.tax_code.code if line.tax_code else None,
                "amount": str(line.amount),
                "tax_amount": str(line.tax_amount),
                "total": str(line.total),
                "breaks": [
                    {"quantity": str(b.quantity), "unit_price": str(b.unit_price)}
                    for b in line.breaks.all()
                ],
            }
            for line in q.lines.select_related("tax_code").prefetch_related("breaks")
        ],
        "files": [
            {
                "id": f.id,
                "line_no": f.line_no,
                "file_name": f.file_name,
                "content_type": f.content_type,
                "size": f.size,
                "uploaded_at": f.uploaded_at,
            }
            for f in q.files.all()
        ],
        "can_edit": services.can_edit(user, q),
        "approved_at": q.approved_at,
        "sent_at": q.sent_at,
        "outcome": None
        if not q.outcome_at
        else {
            "reason": q.outcome_reason,
            "reason_label": q.get_outcome_reason_display() if q.outcome_reason else "",
            "note": q.outcome_note,
            "at": q.outcome_at,
            "by": q.outcome_by.full_name if q.outcome_by else "",
        },
        "is_final": workflow.is_final(q),
        "can_submit": workflow.can_submit(user, q),
        "can_approve": workflow.can_approve(user, q),
        "can_mark_sent": workflow.can_mark_sent(user, q),
        "can_record_outcome": workflow.can_record_outcome(user, q),
        "can_revise": workflow.can_revise(user, q),
        "approval": _approval(q),
        "revisions": [
            {"id": r.id, "revision": r.revision, "status": r.status, "quote_date": r.quote_date}
            for r in workflow.revisions(q)
            if services.visible(user).filter(pk=r.pk).exists()
        ],
        # Whether this user may open the costing (P15-04); the costing itself is only ever
        # sent by the costing endpoint, never with the quotation.
        "can_see_costing": costing.can_see(user, q),
    }
    if body["can_see_costing"]:
        # The Director's warnings come from the costing: shown only to those who see it.
        found = workflow.review(q)
        body["review"] = {
            key: (str(value) if value is not None and key != "warnings" else value)
            for key, value in found.items()
        }
    return body


def _approval(q: Quotation) -> dict | None:
    state = approvals.state_of(workflow.DOC, q.pk)
    if state is None:
        return None
    waiting_with = ""
    if state.status == ApprovalState.Status.IN_PROGRESS:
        step = next(s for s in state.route if s["level"] == state.current_level)
        waiting_with = step["role_name"]
    return {
        "status": state.status,
        "waiting_with": waiting_with,
        "history": [
            {
                "action": row.action,
                "action_label": row.get_action_display(),
                "level": row.level,
                "by": row.user.full_name,
                "at": row.acted_at,
                "reason": row.reason,
            }
            for row in approvals.history(workflow.DOC, q.pk)
        ],
    }


# --- Input ------------------------------------------------------------------------------


class BreakSerializer(serializers.Serializer):
    quantity = serializers.CharField(max_length=30)
    unit_price = serializers.CharField(max_length=30)


class LineSerializer(serializers.Serializer):
    id = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(allow_blank=True)
    drawing_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    drawing_rev = serializers.CharField(max_length=20, required=False, allow_blank=True)
    quantity = serializers.CharField(max_length=30)
    unit = serializers.CharField(max_length=20, required=False, allow_blank=True)
    min_order_qty = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    unit_price = serializers.CharField(max_length=30)
    tax_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    breaks = BreakSerializer(many=True, required=False)
    is_tooling = serializers.BooleanField(required=False, default=False)


class QuotationInput(serializers.Serializer):
    customer = serializers.IntegerField(required=False)
    contact = serializers.IntegerField(required=False, allow_null=True)
    division = serializers.CharField(max_length=2, required=False)
    currency = serializers.CharField(max_length=3, required=False, allow_blank=True)
    valid_until = serializers.DateField(required=False)
    enquiry_ref = serializers.CharField(max_length=100, required=False, allow_blank=True)
    payment_terms = serializers.CharField(max_length=200, required=False, allow_blank=True)
    delivery_lead_time = serializers.CharField(max_length=100, required=False, allow_blank=True)
    incoterm = serializers.CharField(max_length=3, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    lines = LineSerializer(many=True)


def _values(data: dict) -> tuple[dict, list[LineInput]]:
    """Turn the request into the service's inputs; unknown references become errors."""
    values = {}
    if "customer" in data:
        values["customer"] = Customer.objects.filter(pk=data["customer"]).first()
    if "contact" in data:
        values["contact"] = (
            None
            if data["contact"] is None
            else CustomerContact.objects.filter(pk=data["contact"]).first() or "unknown"
        )
    if "division" in data:
        values["division"] = Division.objects.filter(code=data["division"].upper()).first()
    for name in (
        "currency",
        "valid_until",
        "enquiry_ref",
        "payment_terms",
        "delivery_lead_time",
        "incoterm",
        "notes",
    ):
        if name in data:
            values[name] = data[name]
    lines = []
    for n, line in enumerate(data["lines"], start=1):
        code = (line.get("tax_code") or "").strip().upper()
        tax_code = None
        if code:
            tax_code = TaxCode.objects.filter(code=code).first()
            if tax_code is None:
                raise SalesError(f"Line {n}: there is no tax code {code}.")
        lines.append(
            LineInput(
                description=line["description"],
                quantity=line["quantity"],
                unit_price=line["unit_price"],
                drawing_no=line.get("drawing_no", ""),
                drawing_rev=line.get("drawing_rev", ""),
                unit=line.get("unit") or "pcs",
                min_order_qty=line.get("min_order_qty"),
                tax_code=tax_code,
                breaks=[BreakInput(b["quantity"], b["unit_price"]) for b in line.get("breaks", [])],
                id=line.get("id"),
                is_tooling=line.get("is_tooling", False),
            )
        )
    return values, lines


# --- Views ------------------------------------------------------------------------------


class QuotationListView(_Sales):
    def get(self, request):
        rows = services.visible(request.user).select_related(
            "division", "customer", "currency", "created_by"
        )
        rows = services.search(rows, request.query_params.get("q", ""))
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("division"):
            rows = rows.filter(division__code=params["division"].upper())
        if params.get("customer"):
            rows = rows.filter(customer_id=params["customer"])
        if params.get("waiting") == "me":
            waiting = approvals.waiting_for(request.user, workflow.DOC)
            rows = rows.filter(pk__in=[state.document_id for state in waiting])
        return Response([_summary(q) for q in rows[:2000]])

    def post(self, request):
        data = QuotationInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            values, lines = _values(data.validated_data)
            quotation = services.save(request.user, None, lines=lines, **values)
        except SalesError as error:
            return _error(error)
        return Response(_detail(quotation, request.user), status=status.HTTP_201_CREATED)


class QuotationDetailView(_Sales):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk), request.user))

    def put(self, request, pk):
        quotation = _get(request.user, pk)
        data = QuotationInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            values, lines = _values(data.validated_data)
            quotation = services.save(request.user, quotation, lines=lines, **values)
        except SalesError as error:
            return _error(error)
        return Response(_detail(quotation, request.user))


class QuotationFileListView(_Sales):
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        quotation = _get(request.user, pk)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose a file to attach.")
        line = str(request.data.get("line_no", "")).strip()
        if line and not line.isdigit():
            return _error("The line number must be a whole number.")
        try:
            _record, warnings = services.add_file(
                request.user, quotation, uploaded, int(line) if line else None
            )
        except SalesError as error:
            return _error(error)
        body = _detail(Quotation.objects.get(pk=quotation.pk), request.user)
        body["upload_warnings"] = warnings
        return Response(body, status=status.HTTP_201_CREATED)


class QuotationFileDetailView(_Sales):
    def get(self, request, pk, file_pk):
        quotation = _get(request.user, pk)
        record = get_object_or_404(QuotationFile, pk=file_pk, quotation=quotation)
        return FileResponse(
            record.file.open("rb"),
            content_type=record.content_type,
            filename=record.file_name,
            as_attachment=request.query_params.get("download") in ("1", "true"),
        )

    def delete(self, request, pk, file_pk):
        quotation = _get(request.user, pk)
        record = get_object_or_404(QuotationFile, pk=file_pk, quotation=quotation)
        try:
            services.remove_file(request.user, record)
        except SalesError as error:
            return _error(error)
        return Response(_detail(Quotation.objects.get(pk=quotation.pk), request.user))


# --- Costing (P15-04): internal only, for those who may see it --------------------------


class OperationSerializer(serializers.Serializer):
    machine = serializers.IntegerField(allow_null=True)
    minutes = serializers.CharField(max_length=30, allow_blank=True)
    description = serializers.CharField(max_length=100, required=False, allow_blank=True)


class ExtraSerializer(serializers.Serializer):
    description = serializers.CharField(max_length=100, allow_blank=True)
    amount = serializers.CharField(max_length=30, allow_blank=True)
    per_order = serializers.BooleanField(required=False, default=False)


def _optional_text():
    return serializers.CharField(max_length=30, required=False, allow_blank=True, allow_null=True)


class CostingInputSerializer(serializers.Serializer):
    material = serializers.IntegerField(required=False, allow_null=True)
    size_a_mm = _optional_text()
    size_b_mm = _optional_text()
    length_mm = _optional_text()
    cutting_allowance_mm = _optional_text()
    weight_kg = _optional_text()
    setup_hours = _optional_text()
    overhead_pct = _optional_text()
    margin_pct = _optional_text()
    notes = serializers.CharField(required=False, allow_blank=True)
    operations = OperationSerializer(many=True, required=False)
    extras = ExtraSerializer(many=True, required=False)
    method = serializers.ChoiceField(
        choices=["machining", "moulding"], required=False, allow_null=True
    )
    masterbatch = serializers.IntegerField(required=False, allow_null=True)
    masterbatch_pct = _optional_text()
    part_weight_g = _optional_text()
    runner_weight_g = _optional_text()
    cavities = _optional_text()
    machine = serializers.IntegerField(required=False, allow_null=True)
    cycle_time_s = _optional_text()
    reject_pct = _optional_text()
    packing_amount = _optional_text()
    packing_per = serializers.CharField(max_length=10, required=False, allow_blank=True)
    pcs_per_carton = _optional_text()
    tooling = serializers.CharField(max_length=10, required=False, allow_blank=True)
    tooling_cost = _optional_text()
    tooling_qty = _optional_text()


def _record(model, pk, what: str):
    if pk is None:
        return None
    rows = model.objects.select_related("section") if model is Machine else model.objects
    record = rows.filter(pk=pk).first()
    if record is None:
        raise SalesError(f"That {what} does not exist.")
    return record


def _costing_input(data: dict) -> costing.CostingInput:
    material = _record(Material, data.get("material"), "material")
    operations = []
    for op in data.get("operations", []):
        machine = None
        if op["machine"] is not None:
            machine = Machine.objects.select_related("section").filter(pk=op["machine"]).first()
        operations.append(
            costing.OperationInput(
                machine=machine, minutes=op["minutes"], description=op.get("description", "")
            )
        )
    return costing.CostingInput(
        material=material,
        operations=operations,
        extras=[
            costing.ExtraInput(e["description"], e["amount"], e.get("per_order", False))
            for e in data.get("extras", [])
        ],
        notes=data.get("notes", ""),
        method=data.get("method"),
        masterbatch=_record(Material, data.get("masterbatch"), "masterbatch"),
        machine=_record(Machine, data.get("machine"), "machine"),
        packing_per=data.get("packing_per") or "piece",
        tooling=data.get("tooling") or "none",
        **{
            name: data.get(name)
            for name in (
                "masterbatch_pct",
                "part_weight_g",
                "runner_weight_g",
                "cavities",
                "cycle_time_s",
                "reject_pct",
                "packing_amount",
                "pcs_per_carton",
                "tooling_cost",
                "tooling_qty",
                "size_a_mm",
                "size_b_mm",
                "length_mm",
                "cutting_allowance_mm",
                "weight_kg",
                "setup_hours",
                "overhead_pct",
                "margin_pct",
            )
        },
    )


def _costing_quotation(request, pk) -> Quotation:
    """The quotation, if the user may see it at all (404 otherwise), and only if they may
    see its costing (403 otherwise)."""
    quotation = _get(request.user, pk)
    if not costing.can_see(request.user, quotation):
        raise PermissionDenied(
            "The costing is seen by the quotation's creator, the Sales Manager, the "
            "Accountant and the Director."
        )
    return quotation


class QuotationCostingView(_Sales):
    def get(self, request, pk):
        quotation = _costing_quotation(request, pk)
        return Response(costing.page(request.user, quotation))


class QuotationLineCostingView(_Sales):
    def put(self, request, pk, line_no):
        quotation = _costing_quotation(request, pk)
        data = CostingInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            costing.save(request.user, quotation, line_no, _costing_input(data.validated_data))
        except SalesError as error:
            return _error(error)
        return Response(costing.page(request.user, Quotation.objects.get(pk=quotation.pk)))

    def delete(self, request, pk, line_no):
        quotation = _costing_quotation(request, pk)
        try:
            costing.remove(request.user, quotation, line_no)
        except SalesError as error:
            return _error(error)
        return Response(costing.page(request.user, Quotation.objects.get(pk=quotation.pk)))


# --- Approval, sending, outcome and revisions (P15-06) -----------------------------------


class _Action(_Sales):
    def _run(self, request, pk, action):
        quotation = _get(request.user, pk)
        try:
            result = action(quotation)
        except SalesError as error:
            return _error(error)
        return Response(_detail(Quotation.objects.get(pk=result.pk), request.user))


class QuotationSubmitView(_Action):
    access_write_level = "enter"

    def post(self, request, pk):
        comment = str(request.data.get("comment", ""))
        return self._run(request, pk, lambda q: workflow.submit(request.user, q, comment))


class QuotationApproveView(_Action):
    access_write_level = "approve"

    def post(self, request, pk):
        comment = str(request.data.get("comment", ""))
        return self._run(request, pk, lambda q: workflow.approve(request.user, q, comment))


class QuotationReturnView(_Action):
    access_write_level = "approve"

    def post(self, request, pk):
        reason = str(request.data.get("reason", ""))
        return self._run(request, pk, lambda q: workflow.send_back(request.user, q, reason))


class QuotationSentView(_Action):
    # The creator (Sales: Enter) or the Sales Manager (Sales: Approve); the service decides.
    access_write_level = "view"

    def post(self, request, pk):
        return self._run(request, pk, lambda q: workflow.mark_sent(request.user, q))


class QuotationOutcomeView(_Action):
    access_write_level = "view"

    def post(self, request, pk):
        outcome = str(request.data.get("outcome", ""))
        if outcome not in ("accepted", "lost"):
            return _error("Choose won (accepted) or lost.")
        return self._run(
            request,
            pk,
            lambda q: workflow.record_outcome(
                request.user,
                q,
                accepted=outcome == "accepted",
                reason=str(request.data.get("reason", "")),
                note=str(request.data.get("note", "")),
            ),
        )


class QuotationReviseView(_Action):
    access_write_level = "enter"

    def post(self, request, pk):
        quotation = _get(request.user, pk)
        try:
            new = workflow.revise(request.user, quotation)
        except SalesError as error:
            return _error(error)
        return Response(_detail(new, request.user), status=status.HTTP_201_CREATED)
