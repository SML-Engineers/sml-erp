"""Payment vouchers API (spec 4). Rules live in services.py."""

from django.db.models import Q
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounting.models import TaxCode
from apps.core import approvals
from apps.core.models import Division
from apps.core.permissions import AreaAccess, ReadForAllAreaWrite
from apps.masters.models import CompanyAccount, Supplier
from apps.masters.services import is_in_use

from . import services
from .models import Voucher, VoucherAttachment, VoucherType
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


def _summary(v: Voucher) -> dict:
    return {
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


def _detail(v: Voucher, user) -> dict:
    body = _summary(v)
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
                    "account": None
                    if line.account is None
                    else {
                        "id": line.account_id,
                        "number": line.account.number,
                        "name": line.account.name,
                    },
                    "division": line.division.code if line.division else None,
                }
                for line in v.lines.select_related("tax_code", "account", "division")
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
        lines.append(
            services.LineInput(
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


def _get(user, pk) -> Voucher:
    return get_object_or_404(
        services.visible(user).select_related("voucher_type", "division", "payee", "created_by"),
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
        if params.get("mine") in ("1", "true"):
            rows = rows.filter(created_by=request.user)
        text = (params.get("q") or "").strip()
        if text:
            rows = rows.filter(
                Q(number__icontains=text)
                | Q(payee__name__icontains=text)
                | Q(lines__invoice_no__icontains=text)
            ).distinct()
        return Response([_summary(v) for v in rows[:500]])

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
        return Response(_detail(_get(request.user, pk), request.user))

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
        voucher = _get(request.user, pk)
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
