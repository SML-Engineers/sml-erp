"""Chart of accounts API (P0-15). Rules live in services.py; views only translate."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Division
from apps.core.permissions import AreaAccess

from . import excel, services
from .catalogue import TYPES, section_of
from .models import Account, DetailType
from .services import AccountingError


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _row(account: Account, depth: int, name: str, in_use: set[int], banks: dict) -> dict:
    return {
        "id": account.pk,
        "number": account.number,
        "name": account.name,
        "full_name": name,
        "depth": depth,
        "parent": account.parent_id,
        "account_type": account.account_type,
        "account_type_label": TYPES[account.account_type][0],
        "section": section_of(account.account_type),
        "detail_type": {"id": account.detail_type_id, "name": account.detail_type.name},
        "description": account.description,
        "default_division": account.default_division.code if account.default_division else None,
        "default_tax_code": account.default_tax_code.code if account.default_tax_code else None,
        "system_role": account.system_role or None,
        "is_active": account.is_active,
        "merged_into": None
        if account.merged_into is None
        else {"id": account.merged_into_id, "name": account.merged_into.name},
        "in_use": account.pk in in_use,
        "company_account": banks.get(account.pk),
    }


def _rows(include_inactive: bool) -> list[dict]:
    from apps.masters.models import CompanyAccount

    tree = services.chart(include_inactive=include_inactive)
    in_use = {a.pk for a, _, _ in tree if services.is_in_use(a)}
    banks = dict(
        CompanyAccount.objects.filter(ledger_account__isnull=False).values_list(
            "ledger_account_id", "code"
        )
    )
    return [_row(a, depth, name, in_use, banks) for a, depth, name in tree]


def _one(account: Account) -> dict:
    for row in _rows(include_inactive=True):
        if row["id"] == account.pk:
            return row
    raise AssertionError("account missing from the chart")


class AccountInput(serializers.Serializer):
    number = serializers.CharField(max_length=40, required=False, allow_blank=True)
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    account_type = serializers.CharField(max_length=30, required=False)
    detail_type = serializers.IntegerField(required=False, allow_null=True)
    parent = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(max_length=600, required=False, allow_blank=True)
    default_tax_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True, allow_null=True
    )
    default_division = serializers.CharField(
        max_length=2, required=False, allow_blank=True, allow_null=True
    )
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


def _resolve(values: dict) -> dict:
    """Turn ids and codes from the page into records; unknown ones are refused."""
    if "detail_type" in values and values["detail_type"] is not None:
        found = DetailType.objects.filter(pk=values["detail_type"]).first()
        if found is None:
            raise AccountingError("Unknown detail type.")
        values["detail_type"] = found
    if "parent" in values and values["parent"] is not None:
        found = Account.objects.filter(pk=values["parent"]).first()
        if found is None:
            raise AccountingError("Unknown parent account.")
        values["parent"] = found
    if "default_tax_code" in values:
        from .models import TaxCode

        code = (values["default_tax_code"] or "").strip().upper()
        values["default_tax_code"] = None
        if code:
            values["default_tax_code"] = TaxCode.objects.filter(code=code).first()
            if values["default_tax_code"] is None:
                raise AccountingError(f"Unknown tax code {code}.")
    if "default_division" in values:
        code = (values["default_division"] or "").strip().upper()
        values["default_division"] = None
        if code:
            values["default_division"] = Division.objects.filter(code=code).first()
            if values["default_division"] is None:
                raise AccountingError(f"Unknown division {code}.")
    return values


class _Accounting(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "manage"


class AccountListView(_Accounting):
    def get(self, request):
        include = request.query_params.get("include_inactive") in ("1", "true")
        rows = _rows(include_inactive=include)
        kind = request.query_params.get("type")
        if kind:
            rows = [r for r in rows if r["account_type"] == kind]
        return Response(rows)

    def post(self, request):
        data = AccountInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("is_active", None)
        reason = values.pop("reason")
        try:
            values = _resolve(values)
            account = services.create_account(
                request.user,
                name=values.pop("name", ""),
                account_type=values.pop("account_type", ""),
                detail_type=values.pop("detail_type", None),
                reason=reason,
                **values,
            )
        except AccountingError as error:
            return _error(error)
        return Response(_one(account), status=status.HTTP_201_CREATED)


class AccountDetailView(_Accounting):
    def get(self, request, pk):
        return Response(_one(get_object_or_404(Account, pk=pk)))

    def patch(self, request, pk):
        account = get_object_or_404(Account, pk=pk)
        data = AccountInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            account = services.update_account(request.user, account, _resolve(values), reason)
        except AccountingError as error:
            return _error(error)
        return Response(_one(account))

    def delete(self, request, pk):
        account = get_object_or_404(Account, pk=pk)
        try:
            services.delete_account(request.user, account, str(request.data.get("reason", "")))
        except AccountingError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MergeInput(serializers.Serializer):
    into = serializers.IntegerField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class AccountMergeView(_Accounting):
    def post(self, request, pk):
        source = get_object_or_404(Account, pk=pk)
        data = MergeInput(data=request.data)
        data.is_valid(raise_exception=True)
        target = Account.objects.filter(pk=data.validated_data["into"]).first()
        if target is None:
            return _error("Unknown account to merge into.")
        try:
            target = services.merge_accounts(
                request.user, source, target, data.validated_data["reason"]
            )
        except AccountingError as error:
            return _error(error)
        return Response(_one(target))


class AccountTypesView(_Accounting):
    """The account types in report order, with their detail types."""

    def get(self, request):
        return Response(services.catalogue())


class DetailTypeInput(serializers.Serializer):
    account_type = serializers.CharField(max_length=30, required=False)
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


def _detail(d: DetailType) -> dict:
    return {
        "id": d.pk,
        "account_type": d.account_type,
        "name": d.name,
        "is_active": d.is_active,
        "accounts": d.accounts.count(),
    }


class DetailTypeListView(_Accounting):
    def get(self, request):
        return Response([_detail(d) for d in DetailType.objects.all()])

    def post(self, request):
        data = DetailTypeInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            detail = services.create_detail_type(
                request.user,
                account_type=v.get("account_type", ""),
                name=v.get("name", ""),
                reason=v["reason"],
            )
        except AccountingError as error:
            return _error(error)
        return Response(_detail(detail), status=status.HTTP_201_CREATED)


class DetailTypeDetailView(_Accounting):
    def patch(self, request, pk):
        detail = get_object_or_404(DetailType, pk=pk)
        data = DetailTypeInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("account_type", None)  # a detail type keeps its account type
        reason = values.pop("reason")
        try:
            detail = services.update_detail_type(request.user, detail, values, reason)
        except AccountingError as error:
            return _error(error)
        return Response(_detail(detail))

    def delete(self, request, pk):
        detail = get_object_or_404(DetailType, pk=pk)
        try:
            services.delete_detail_type(request.user, detail)
        except AccountingError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChartExportView(_Accounting):
    def get(self, request):
        today = timezone.localdate().isoformat()
        response = HttpResponse(
            excel.export_workbook(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="chart-of-accounts-{today}.xlsx"'
        return response


class ChartImportView(_Accounting):
    """Import the chart from Excel. `dry_run` checks without saving."""

    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose an Excel file to import.")
        if uploaded.size > excel.MAX_BYTES:
            return _error("The file must be 5 MB or smaller.")
        dry_run = str(request.data.get("dry_run", "")).lower() in ("1", "true", "yes")
        try:
            counts = excel.import_workbook(
                uploaded.read(),
                reason=str(request.data.get("reason", "")),
                user=request.user,
                dry_run=dry_run,
            )
        except AccountingError as error:
            return _error(error)
        except excel.ImportRefused as refused:
            return Response(
                {"detail": "Nothing was imported.", "errors": refused.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"dry_run": dry_run, **counts})
