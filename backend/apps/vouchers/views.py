"""Payment vouchers API (spec 4). Rules live in services.py."""

from datetime import date

from django.db.models import Q
from django.http import FileResponse, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting import taxes
from apps.accounting.models import TaxCode, TaxComponent
from apps.core import approvals, exports
from apps.core.models import Division
from apps.core.permissions import AreaAccess, ReadForAllAreaWrite
from apps.masters.models import CompanyAccount, Supplier
from apps.masters.services import is_in_use

from . import dashboard, printing, reports, services
from .models import Voucher, VoucherAttachment, VoucherCancellation, VoucherType
from .services import VoucherError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _type(vt: VoucherType) -> dict:
    return {
        "id": vt.pk,
        "code": vt.code,
        "name": vt.name,
        "payment_method": vt.payment_method,
        "needs_payee": vt.needs_payee,
        "payee_category": vt.payee_category,
        "is_advance": vt.is_advance,
        "notes": vt.notes,
        "sort_order": vt.sort_order,
        "is_active": vt.is_active,
        "in_use": is_in_use(vt),
    }


class TypeInput(serializers.Serializer):
    code = serializers.CharField(max_length=20, required=False)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    payment_method = serializers.CharField(max_length=30, required=False)
    needs_payee = serializers.BooleanField(required=False)
    payee_category = serializers.CharField(max_length=20, required=False, allow_blank=True)
    is_advance = serializers.BooleanField(required=False)
    notes = serializers.CharField(max_length=300, required=False, allow_blank=True)
    sort_order = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class _Types(APIView):
    """Everyone signed in may read the types (the voucher form lists them); only the
    Admin changes them."""

    permission_classes = [ReadForAllAreaWrite]
    access_area = "settings"
    access_write_level = "manage"


class TypeListView(_Types):
    def get(self, request):
        rows = VoucherType.objects.all()
        if request.query_params.get("include_inactive") not in ("1", "true"):
            rows = rows.filter(is_active=True)
        return Response([_type(vt) for vt in rows])

    def post(self, request):
        data = TypeInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("is_active", None)
        try:
            vt = services.create_type(
                request.user,
                code=values.pop("code", ""),
                name=values.pop("name", ""),
                payment_method=values.pop("payment_method", ""),
                **values,
            )
        except VoucherError as error:
            return _error(error)
        return Response(_type(vt), status=status.HTTP_201_CREATED)


class TypeDetailView(_Types):
    def patch(self, request, pk):
        vt = get_object_or_404(VoucherType, pk=pk)
        data = TypeInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            vt = services.update_type(request.user, vt, values, reason)
        except VoucherError as error:
            return _error(error)
        return Response(_type(vt))

    def delete(self, request, pk):
        vt = get_object_or_404(VoucherType, pk=pk)
        try:
            services.delete_type(request.user, vt, str(request.data.get("reason", "")))
        except VoucherError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


# --- Vouchers (P1-02) -------------------------------------------------------------------


def _summary(v: Voucher, user=None, waiting=None) -> dict:
    """One row of a voucher list; with `user`, also the row actions they may take."""
    row = {
        "id": v.pk,
        "number": v.number,
        "status": v.status,
        "voucher_type": {"code": v.voucher_type.code, "name": v.voucher_type.name},
        "division": v.division.code,
        "payee": None if v.payee is None else {"id": v.payee_id, "name": v.payee.name},
        "voucher_date": v.voucher_date,
        "total_amount": f"{v.total_amount:.2f}",
        "created_by": v.created_by.full_name,
        "attachments": v.attachments.count(),
    }
    if user is not None:
        row["actions"] = services.actions(user, v, waiting)
    if v.status == Voucher.Status.DELETED:
        row["deleted"] = {
            "at": v.deleted_at,
            "by": v.deleted_by.full_name if v.deleted_by else "",
            "reason": v.delete_reason,
        }
    return row


def _detail(v: Voucher, user) -> dict:
    body = _summary(v, user)
    body.update(
        {
            "voucher_type": _type(v.voucher_type),
            "payee": None
            if v.payee is None
            else {
                "id": v.payee_id,
                "code": v.payee.code,
                "name": v.payee.name,
                "category": v.payee.category,
            },
            "transfer_to": None
            if v.transfer_to is None
            else {"id": v.transfer_to_id, "code": v.transfer_to.code, "name": v.transfer_to.name},
            "description": v.description,
            "created_by_id": v.created_by_id,
            "created_at": v.created_at,
            "submitted_at": v.submitted_at,
            "revision": v.revision,
            "amendment_reason": v.amendment_reason,
            "parent": None
            if v.parent_id is None
            else {"id": v.parent_id, "number": v.parent.number},
            "revisions": [
                {"id": r.pk, "number": r.number, "status": r.status}
                for r in v.revisions.order_by("revision", "id")
            ],
            "cancellation": _cancellation(v.cancellations.first(), user),
            **_payments(v, user),
            "lines": [
                {
                    "line_no": line.line_no,
                    "invoice_no": line.invoice_no,
                    "invoice_date": line.invoice_date,
                    "description": line.description,
                    "amount": f"{line.amount:.2f}",
                    "tax_code": line.tax_code.code if line.tax_code else None,
                    "tax_amount": f"{line.tax_amount:.2f}",
                    "total": f"{line.total:.2f}",
                    # P2-12: withholding tax kept from the payment for this line.
                    "wht_component": line.wht_component.code if line.wht_component else None,
                    "wht_rate": f"{line.wht_rate.normalize():f}",
                    "wht_amount": f"{line.wht_amount:.2f}",
                    "account": None
                    if line.account is None
                    else {
                        "id": line.account_id,
                        "number": line.account.number,
                        "name": line.account.name,
                    },
                    "division": line.division.code if line.division else None,
                    "job_ref": line.job_ref,
                    "order_linked": bool(line.job_id or line.production_order_id),
                    "supplier_invoice": _invoice(line.supplier_invoice),
                    "advance_order": None
                    if line.advance_order is None
                    else {
                        "id": line.advance_order_id,
                        "label": line.advance_order.label,
                        "total_lkr": str(line.advance_order.total_lkr),
                        "status": line.advance_order.status,
                    },
                    "splits": [
                        {
                            "division": part.division.code,
                            "amount": f"{part.amount:.2f}",
                            "percent": None
                            if part.percent is None
                            else f"{part.percent.normalize():f}",
                        }
                        for part in line.splits.select_related("division")
                    ],
                }
                for line in v.lines.select_related(
                    "tax_code",
                    "account",
                    "division",
                    "supplier_invoice",
                    "advance_order",
                    "wht_component",
                )
            ],
            "attachments": [
                {
                    "id": a.pk,
                    "file_name": a.file_name,
                    "content_type": a.content_type,
                    "size": a.size,
                    "sha256": a.sha256,
                    "uploaded_at": a.uploaded_at,
                }
                for a in v.attachments.all()
            ],
            "warnings": services.duplicate_invoices(v),
            # P2-12: the WHT kept, what the payee receives, and the withholding taxes the
            # Accountant can choose (none until a rate is confirmed: built switched off).
            "wht_total": f"{v.wht_total:.2f}",
            "payable": f"{services.payable(v):.2f}",
            "wht_choices": [
                {
                    "code": c.code,
                    "name": c.name,
                    "rate": f"{taxes.rate_on(c, v.voucher_date).rate.normalize():f}",
                }
                for c in services.wht_choices(v.voucher_date)
            ]
            if v.payee_id
            else [],
            **_approval(v, user),
            "can_edit": v.created_by_id == user.pk and v.status in services.EDITABLE,
            "payee_balance": services.payee_balance(v.payee) if v.payee else None,
            "approvals": [
                {
                    "level": row.level,
                    "action": row.action,
                    "user": row.user.full_name,
                    "reason": row.reason,
                    "acted_at": row.acted_at,
                }
                for row in approvals.history(services.DOC, v.pk)
            ],
        }
    )
    return body


def _approval(v: Voucher, user) -> dict:
    state = approvals.state_of(services.DOC, v.pk)
    waiting = state is not None and state.status == "in_progress"
    step = (
        next((s for s in state.route if s["level"] == state.current_level), None)
        if waiting
        else None
    )
    return {
        "waiting_level": state.current_level if waiting else None,
        "waiting_for": step["role_name"] if step else None,
        "can_act": waiting and approvals.why_not(user, state) is None,
        "uncoded_lines": services.uncoded_lines(v) if waiting else [],
    }


def _invoice(invoice) -> dict | None:
    """The matched supplier invoice a line pays, with PO, GRN and invoice side by side for the
    approvers (spec 5A.5)."""
    if invoice is None:
        return None
    from apps.purchasing import invoices

    return {
        "id": invoice.id,
        "number": invoice.number,
        "invoice_no": invoice.invoice_no,
        "invoice_date": invoice.invoice_date,
        "due_date": invoice.due_date,
        "total_lkr": str(invoice.total_lkr),
        "on_vouchers": str(invoices.on_vouchers(invoice)),
        "lines": invoices.match_summary(invoice),
    }


class LineInputSerializer(serializers.Serializer):
    invoice_no = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    invoice_date = serializers.DateField(required=False, allow_null=True, default=None)
    description = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )
    amount = serializers.CharField(max_length=30)
    tax_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    tax_amount = serializers.CharField(max_length=30, required=False, allow_blank=True, default="0")
    supplier_invoice = serializers.IntegerField(required=False, allow_null=True, default=None)
    advance_order = serializers.IntegerField(required=False, allow_null=True, default=None)


class VoucherInput(serializers.Serializer):
    voucher_type = serializers.CharField(max_length=10)
    division = serializers.CharField(max_length=2, required=False, allow_blank=True)
    payee = serializers.IntegerField(required=False, allow_null=True)
    transfer_to = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(
        max_length=500, required=False, allow_blank=True, default=""
    )
    lines = LineInputSerializer(many=True, required=False, default=list)


def _resolve(data: dict) -> dict:
    vt = VoucherType.objects.filter(code=data["voucher_type"].upper()).first()
    if vt is None:
        raise VoucherError("Unknown voucher type.")
    values = {"voucher_type": vt, "description": data["description"]}
    if data.get("division"):
        values["division"] = Division.objects.filter(code=data["division"].upper()).first()
        if values["division"] is None:
            raise VoucherError("Unknown division.")
    values["payee"] = None
    if data.get("payee"):
        values["payee"] = Supplier.objects.filter(pk=data["payee"]).first()
        if values["payee"] is None:
            raise VoucherError("Unknown payee.")
    values["transfer_to"] = None
    if data.get("transfer_to"):
        values["transfer_to"] = CompanyAccount.objects.filter(pk=data["transfer_to"]).first()
        if values["transfer_to"] is None:
            raise VoucherError("Unknown company account.")
    lines = []
    for number, line in enumerate(data["lines"], start=1):
        code = None
        if line.get("tax_code"):
            code = TaxCode.objects.filter(code=line["tax_code"].upper()).first()
            if code is None:
                raise VoucherError(f"Line {number}: unknown tax code {line['tax_code']}.")
        invoice = None
        if line.get("supplier_invoice"):
            from apps.purchasing.models import SupplierInvoice

            invoice = SupplierInvoice.objects.filter(pk=line["supplier_invoice"]).first()
            if invoice is None:
                raise VoucherError(f"Line {number}: unknown supplier invoice.")
        order = None
        if line.get("advance_order"):
            from apps.purchasing.models import PurchaseOrder

            order = PurchaseOrder.objects.filter(pk=line["advance_order"]).first()
            if order is None:
                raise VoucherError(f"Line {number}: unknown purchase order.")
        lines.append(
            services.LineInput(
                advance_order=order,
                supplier_invoice=invoice,
                amount=line["amount"],
                invoice_no=line["invoice_no"],
                invoice_date=line["invoice_date"],
                description=line["description"],
                tax_code=code,
                tax_amount=line["tax_amount"],
            )
        )
    values["lines"] = lines
    return values


class _Vouchers(APIView):
    permission_classes = [AreaAccess]
    access_area = "vouchers"
    access_write_level = "enter"


def _get(user, pk, *, deleted_too=False) -> Voucher:
    """A voucher the user may see. Deleted ones only for reading (details, files, print)."""
    rows = services.visible(user, deleted=None if deleted_too else False)
    return get_object_or_404(
        rows.select_related("voucher_type", "division", "payee", "created_by", "deleted_by"),
        pk=pk,
    )


class VoucherListView(_Vouchers):
    def get(self, request):
        rows = services.visible(request.user).select_related(
            "voucher_type", "division", "payee", "created_by"
        )
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("type"):
            rows = rows.filter(voucher_type__code=params["type"].upper())
        if params.get("division"):
            rows = rows.filter(division__code=params["division"].upper())
        if _day(request, "from"):
            rows = rows.filter(voucher_date__gte=_day(request, "from"))
        if _day(request, "to"):
            rows = rows.filter(voucher_date__lte=_day(request, "to"))
        if params.get("mine") in ("1", "true"):
            rows = rows.filter(created_by=request.user)
        text = (params.get("q") or "").strip()
        if text:
            rows = rows.filter(
                Q(number__icontains=text)
                | Q(payee__name__icontains=text)
                | Q(lines__invoice_no__icontains=text)
            ).distinct()
        fmt = _export_format(request)
        if fmt:
            keys = ("status", "type", "division", "from", "to", "q")
            filters = [f"{k}: {params[k]}" for k in keys if params.get(k)]
            return exports.response(
                fmt,
                title="Voucher list",
                subtitle=", ".join(filters) or "All vouchers",
                columns=reports.LIST_COLUMNS,
                rows=reports.list_rows(rows[:5000]),
                filename="vouchers",
                user=request.user,
            )
        waiting = services.waiting_levels(request.user)
        return Response([_summary(v, request.user, waiting) for v in rows[:500]])

    def post(self, request):
        data = VoucherInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            voucher = services.save(request.user, None, **_resolve(data.validated_data))
        except VoucherError as error:
            return _error(error)
        return Response(_detail(voucher, request.user), status=status.HTTP_201_CREATED)


class VoucherDetailView(_Vouchers):
    def get(self, request, pk):
        return Response(_detail(_get(request.user, pk, deleted_too=True), request.user))

    def patch(self, request, pk):
        voucher = _get(request.user, pk)
        data = VoucherInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            voucher = services.save(request.user, voucher, **_resolve(data.validated_data))
        except VoucherError as error:
            return _error(error)
        return Response(_detail(voucher, request.user))


class SubmitView(_Vouchers):
    def post(self, request, pk):
        voucher = _get(request.user, pk)
        try:
            voucher = services.submit(request.user, voucher, str(request.data.get("comment", "")))
        except VoucherError as error:
            return _error(error)
        return Response(_detail(voucher, request.user))


class AttachmentListView(_Vouchers):
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        voucher = _get(request.user, pk)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose a file to attach.")
        try:
            _attachment, warnings = services.add_attachment(request.user, voucher, uploaded)
        except VoucherError as error:
            return _error(error)
        body = _detail(Voucher.objects.get(pk=voucher.pk), request.user)
        body["upload_warnings"] = warnings
        return Response(body, status=status.HTTP_201_CREATED)


class AttachmentDetailView(_Vouchers):
    def get(self, request, pk, attachment_pk):
        voucher = _get(request.user, pk, deleted_too=True)
        attachment = get_object_or_404(VoucherAttachment, pk=attachment_pk, voucher=voucher)
        return FileResponse(
            attachment.file.open("rb"),
            content_type=attachment.content_type,
            filename=attachment.file_name,
            as_attachment=request.query_params.get("download") in ("1", "true"),
        )

    def delete(self, request, pk, attachment_pk):
        voucher = _get(request.user, pk)
        attachment = get_object_or_404(VoucherAttachment, pk=attachment_pk, voucher=voucher)
        try:
            services.remove_attachment(request.user, attachment)
        except VoucherError as error:
            return _error(error)
        return Response(_detail(Voucher.objects.get(pk=voucher.pk), request.user))


class PayeeBalanceView(_Vouchers):
    def get(self, request, payee_pk):
        payee = get_object_or_404(Supplier, pk=payee_pk)
        return Response(services.payee_balance(payee))


class TransferAccountsView(_Vouchers):
    """Open company bank and cash accounts, for the receiving side of internal transfers."""

    def get(self, request):
        return Response(
            [
                {"id": a.pk, "code": a.code, "name": a.name}
                for a in CompanyAccount.objects.filter(is_active=True)
            ]
        )


# --- Review and approval (P1-03) --------------------------------------------------------


class _Approving(_Vouchers):
    access_write_level = "approve"


class WaitingView(_Approving):
    """Vouchers waiting for this user's approval, oldest first, with what the Director's
    page shows in its table (division, Accountant's comment)."""

    def get(self, request):
        rows = (
            services.waiting(request.user)
            .select_related("voucher_type", "division", "payee", "created_by")
            .order_by("submitted_at", "id")
        )
        result = []
        waiting = services.waiting_levels(request.user)
        for v in rows:
            row = _summary(v, request.user, waiting)
            row["submitted_at"] = v.submitted_at
            row["waiting_level"] = _approval(v, request.user)["waiting_level"]
            checked = [h for h in approvals.history(services.DOC, v.pk) if h.action == "approve"]
            row["last_comment"] = checked[-1].reason if checked else ""
            result.append(row)
        return Response(result)


class SplitSerializer(serializers.Serializer):
    division = serializers.CharField(max_length=2)
    amount = serializers.CharField(max_length=30, required=False, allow_blank=True, allow_null=True)
    percent = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )


class CodingSerializer(serializers.Serializer):
    line_no = serializers.IntegerField()
    account = serializers.IntegerField(required=False, allow_null=True)
    division = serializers.CharField(
        max_length=2, required=False, allow_blank=True, allow_null=True
    )
    tax_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    tax_amount = serializers.CharField(max_length=30, required=False, allow_blank=True, default="0")
    job_ref = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    splits = SplitSerializer(many=True, required=False, default=list)
    wht_component = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )


class CodingInput(serializers.Serializer):
    lines = CodingSerializer(many=True)


def _division(code, where):
    if not code:
        return None
    division = Division.objects.filter(code=code.upper()).first()
    if division is None:
        raise VoucherError(f"{where}: unknown division {code}.")
    return division


def _codings(lines) -> list:
    from apps.accounting.models import Account

    result = []
    for line in lines:
        where = f"Line {line['line_no']}"
        account = None
        if line.get("account"):
            account = Account.objects.filter(pk=line["account"]).first()
            if account is None:
                raise VoucherError(f"{where}: unknown account.")
        code = None
        if line.get("tax_code"):
            code = TaxCode.objects.filter(code=line["tax_code"].upper()).first()
            if code is None:
                raise VoucherError(f"{where}: unknown tax code {line['tax_code']}.")
        wht = None
        if line.get("wht_component"):
            wht = TaxComponent.objects.filter(code=line["wht_component"].upper()).first()
            if wht is None:
                raise VoucherError(f"{where}: unknown tax {line['wht_component']}.")
        result.append(
            services.CodingInput(
                line_no=line["line_no"],
                wht_component=wht,
                account=account,
                division=_division(line.get("division"), where),
                tax_code=code,
                tax_amount=line["tax_amount"],
                job_ref=line["job_ref"],
                splits=[
                    services.SplitInput(
                        division=_division(part["division"], where),
                        amount=part.get("amount"),
                        percent=part.get("percent"),
                    )
                    for part in line["splits"]
                ],
            )
        )
    return result


class CodingView(_Approving):
    def patch(self, request, pk):
        voucher = _get(request.user, pk)
        data = CodingInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            voucher = services.code_lines(
                request.user, voucher, _codings(data.validated_data["lines"])
            )
        except VoucherError as error:
            return _error(error)
        return Response(_detail(voucher, request.user))


class DecisionView(_Approving):
    """Approve (optional comment), return or reject (reason required)."""

    def post(self, request, pk, decision):
        voucher = _get(request.user, pk)
        text = str(request.data.get("comment") or request.data.get("reason") or "")
        try:
            if decision == "approve":
                voucher = services.approve(request.user, voucher, text)
            elif decision == "return":
                voucher = services.send_back(request.user, voucher, text)
            elif decision == "reject":
                voucher = services.reject(request.user, voucher, text)
            else:
                return Response(status=status.HTTP_404_NOT_FOUND)
        except VoucherError as error:
            return _error(error)
        return Response(_detail(voucher, request.user))


class DecisionItem(serializers.Serializer):
    id = serializers.IntegerField()
    decision = serializers.CharField(max_length=10)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class BulkInput(serializers.Serializer):
    decisions = DecisionItem(many=True)


class BulkDecisionView(_Approving):
    """Confirm several Approve / Reject decisions at once (the Director's page)."""

    def post(self, request):
        data = BulkInput(data=request.data)
        data.is_valid(raise_exception=True)
        items = [
            services.Decision(voucher_id=d["id"], decision=d["decision"], reason=d["reason"])
            for d in data.validated_data["decisions"]
        ]
        try:
            done = services.decide_many(request.user, items)
        except services.BulkRefused as refused:
            return Response(
                {
                    "detail": "Nothing was confirmed.",
                    "errors": {str(k): v for k, v in refused.errors.items()},
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except VoucherError as error:
            return _error(error)
        approved = [v for v in done if v.status == Voucher.Status.DIRECTOR_APPROVED]
        return Response(
            {
                "confirmed": len(done),
                "approved": len([v for v in done if v.status != Voucher.Status.REJECTED]),
                "rejected": len([v for v in done if v.status == Voucher.Status.REJECTED]),
                "fully_approved": [v.number for v in approved],
            }
        )


# --- Row actions: print, delete, edit while waiting (P1-04b) ---------------------------


class DeletedListView(_Vouchers):
    """The Deleted Vouchers report: who deleted each one, when and why."""

    def get(self, request):
        rows = (
            services.visible(request.user, deleted=True)
            .select_related("voucher_type", "division", "payee", "created_by", "deleted_by")
            .order_by("-deleted_at", "-id")
        )
        return Response([_summary(v, request.user, {}) for v in rows[:1000]])


class PrintView(_Vouchers):
    """The payment voucher as a PDF (A4, or ?paper=A5). Each print is logged; reprints say
    "COPY"."""

    def get(self, request, pk):
        voucher = _get(request.user, pk, deleted_too=True)
        paper = (request.query_params.get("paper") or "A4").upper()
        try:
            record = services.record_print(request.user, voucher, paper)
        except VoucherError as error:
            return _error(error)
        response = HttpResponse(printing.render(voucher, record), content_type="application/pdf")
        suffix = "-copy" if record.is_copy else ""
        response["Content-Disposition"] = f'inline; filename="{voucher.number}{suffix}.pdf"'
        return response


class DeleteView(_Vouchers):
    # Who may delete is decided by the service: the creator of a draft, or the Director or
    # the Admin for a submitted voucher (the Admin only views vouchers otherwise).
    access_write_level = "view"

    def post(self, request, pk):
        voucher = _get(request.user, pk)
        try:
            voucher = services.delete(request.user, voucher, str(request.data.get("reason", "")))
        except VoucherError as error:
            return _error(error)
        return Response(_detail(voucher, request.user))


class ReviseView(_Approving):
    """An approver's edit while the voucher waits for them (description at any level; the
    payee, amounts and lines from the Director, which sends it back to the Accountant)."""

    def patch(self, request, pk):
        voucher = _get(request.user, pk)
        data = VoucherInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            values = _resolve(data.validated_data)
            if values["voucher_type"].pk != voucher.voucher_type_id:
                raise VoucherError("The voucher type cannot change here.")
            values.pop("voucher_type")
            values.pop("division", None)
            voucher = services.revise(request.user, voucher, **values)
        except VoucherError as error:
            return _error(error)
        return Response(_detail(voucher, request.user))


# --- Amendments (P1-05) -----------------------------------------------------------------


class AmendView(_Vouchers):
    """Start an amendment of a Director-approved voucher; returns the new draft revision."""

    def post(self, request, pk):
        voucher = _get(request.user, pk)
        try:
            amendment = services.amend(request.user, voucher, str(request.data.get("reason", "")))
        except VoucherError as error:
            return _error(error)
        return Response(_detail(amendment, request.user), status=status.HTTP_201_CREATED)


class AmendmentListView(_Vouchers):
    """The Amendments List: each revision with the voucher it amends and why."""

    def get(self, request):
        rows = (
            services.amendments(request.user)
            .select_related("voucher_type", "division", "payee", "created_by", "parent")
            .order_by("-created_at", "-id")
        )
        fmt = _export_format(request)
        if fmt:
            return exports.response(
                fmt,
                title="Amendments list",
                subtitle="Revisions of approved vouchers",
                columns=AMENDMENT_COLUMNS,
                rows=[
                    {
                        "number": v.number,
                        "original": v.parent.number,
                        "voucher_date": v.voucher_date,
                        "payee": v.payee.name if v.payee else "",
                        "reason": v.amendment_reason,
                        "was": f"{v.parent.total_amount:.2f}",
                        "total_amount": f"{v.total_amount:.2f}",
                        "status": v.get_status_display(),
                    }
                    for v in rows[:5000]
                ],
                filename="amendments",
                user=request.user,
            )
        waiting = services.waiting_levels(request.user)
        result = []
        for v in rows[:1000]:
            row = _summary(v, request.user, waiting)
            row["revision"] = v.revision
            row["amendment_reason"] = v.amendment_reason
            row["parent"] = {
                "id": v.parent_id,
                "number": v.parent.number,
                "total_amount": f"{v.parent.total_amount:.2f}",
            }
            result.append(row)
        return Response(result)


# --- Cancellation (P1-06) ---------------------------------------------------------------


def _cancellation(request: VoucherCancellation | None, user) -> dict | None:
    if request is None:
        return None
    return {
        "id": request.pk,
        "status": request.status,
        "reason": request.reason,
        "requested_by": request.requested_by.full_name,
        "requested_at": request.requested_at,
        "decided_by": request.decided_by.full_name if request.decided_by else None,
        "decided_at": request.decided_at,
        "decision_reason": request.decision_reason,
        "can_decide": services.can_decide(user, request),
    }


class CancelRequestView(_Approving):
    """The Accountant asks the Director to cancel an approved, unpaid voucher."""

    def post(self, request, pk):
        voucher = _get(request.user, pk)
        try:
            services.request_cancellation(
                request.user, voucher, str(request.data.get("reason", ""))
            )
        except VoucherError as error:
            return _error(error)
        return Response(_detail(Voucher.objects.get(pk=voucher.pk), request.user))


class CancellationListView(_Vouchers):
    """Cancellation requests, newest first; ?pending=1 for those waiting."""

    def get(self, request):
        rows = services.cancellations(request.user)
        if request.query_params.get("pending") in ("1", "true"):
            rows = rows.filter(status=VoucherCancellation.Status.PENDING)
        return Response(
            [
                {
                    **_cancellation(row, request.user),
                    "voucher": {
                        "id": row.voucher_id,
                        "number": row.voucher.number,
                        "status": row.voucher.status,
                        "payee": row.voucher.payee.name if row.voucher.payee else "",
                        "total_amount": f"{row.voucher.total_amount:.2f}",
                    },
                }
                for row in rows[:500]
            ]
        )


class CancellationDecisionView(_Approving):
    """The Director approves or rejects a cancellation request (reject needs a reason)."""

    def post(self, request, pk, decision):
        row = get_object_or_404(services.cancellations(request.user), pk=pk)
        try:
            row = services.decide_cancellation(
                request.user, row, decision == "approve", str(request.data.get("reason", ""))
            )
        except VoucherError as error:
            return _error(error)
        return Response(_detail(Voucher.objects.get(pk=row.voucher_id), request.user))


def _payments(v: Voucher, user) -> dict:
    """Payments made against the voucher (P1-07), for those who may see payments."""
    from apps.core.access import has_access
    from apps.payments.services import paid_on, to_receive
    from apps.payments.views import payment_row

    paid = paid_on(v)
    rows = (
        [
            payment_row(p, user)
            for p in v.payments.select_related(
                "voucher", "voucher__payee", "account", "journal_entry", "created_by"
            ).order_by("payment_date", "id")
        ]
        if has_access(user, "payments", "view")
        else []
    )
    return {
        "paid": f"{paid:.2f}",
        "remaining": f"{v.total_amount - paid:.2f}",
        "to_receive": f"{to_receive(v):.2f}",
        "payments": rows,
    }


# --- Lists and reports (P1-08) ----------------------------------------------------------

AMENDMENT_COLUMNS = [
    exports.Column("number", "Amendment", width=1.5),
    exports.Column("original", "Amends", width=1.3),
    exports.Column("voucher_date", "Date", "date"),
    exports.Column("payee", "Payee", width=2),
    exports.Column("reason", "Reason", width=2.5),
    exports.Column("status", "Status", width=1.2),
    exports.Column("was", "Was (LKR)", "money"),
    exports.Column("total_amount", "Now (LKR)", "money"),
]


def _export_format(request) -> str | None:
    """?export=xlsx or ?export=pdf asks for a download instead of the rows."""
    fmt = (request.query_params.get("export") or "").lower()
    return fmt if fmt in exports.FORMATS else None


def _day(request, name):
    value = request.query_params.get(name) or ""
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


class ApprovedReportView(_Vouchers):
    """The Approved List: vouchers approved by the Director in a period."""

    def get(self, request):
        start, end = _day(request, "from"), _day(request, "to")
        division = request.query_params.get("division") or ""
        rows = reports.approved(request.user, start=start, end=end, division=division)
        fmt = _export_format(request)
        if fmt:
            period = f"{start or 'start'} to {end or 'today'}"
            return exports.response(
                fmt,
                title="Approved vouchers",
                subtitle=f"Approved by the Director, {period}"
                + (f", division {division.upper()}" if division else ""),
                columns=reports.APPROVED_COLUMNS,
                rows=rows,
                filename="approved-vouchers",
                user=request.user,
            )
        return Response(rows)


class PendingReportView(_Vouchers):
    """Vouchers waiting for approval, by approver and age."""

    def get(self, request):
        division = request.query_params.get("division") or ""
        level = request.query_params.get("level") or ""
        rows = reports.pending(
            request.user, division=division, level=int(level) if level.isdigit() else None
        )
        fmt = _export_format(request)
        if fmt:
            return exports.response(
                fmt,
                title="Vouchers pending approval",
                subtitle=f"By approver and age, as at {timezone.localtime():%d/%m/%Y %H:%M}"
                + (f", division {division.upper()}" if division else "")
                + (f", level {level}" if level.isdigit() else ""),
                columns=reports.PENDING_COLUMNS,
                rows=rows,
                filename="pending-vouchers",
                user=request.user,
            )
        return Response({"rows": rows, "summary": reports.pending_summary(rows)})


class HistoryView(_Vouchers):
    """The full approval history of one voucher (cancellation requests included)."""

    def get(self, request, pk):
        voucher = _get(request.user, pk, deleted_too=True)
        rows = reports.history(voucher)
        fmt = _export_format(request)
        if fmt:
            return exports.response(
                fmt,
                title=f"Approval history of voucher {voucher.number}",
                subtitle=f"{voucher.voucher_type.name}, {voucher.get_status_display()}, "
                f"LKR {voucher.total_amount:,.2f}",
                columns=reports.HISTORY_COLUMNS,
                rows=rows,
                filename=f"history-{voucher.number}",
                user=request.user,
            )
        return Response(rows)


class DashboardView(_Vouchers):
    """The vouchers dashboard on the home page (P1-08b); ?division=WS for one division."""

    def get(self, request):
        return Response(dashboard.figures(request.user, request.query_params.get("division", "")))
