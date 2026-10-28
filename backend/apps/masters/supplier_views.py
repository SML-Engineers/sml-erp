"""Suppliers and payees API (P0-13). Rules live in suppliers.py."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess

from . import suppliers
from .models import Supplier, SupplierBankAccount
from .services import MastersError


class BankAccountSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(read_only=True, slug_field="email")

    class Meta:
        model = SupplierBankAccount
        fields = [
            "id",
            "bank_name",
            "branch",
            "account_name",
            "account_number",
            "swift_code",
            "is_default",
            "is_active",
            "created_by",
            "created_at",
        ]


class SupplierSerializer(serializers.ModelSerializer):
    currency = serializers.SlugRelatedField(read_only=True, slug_field="code")
    bank_changed_by = serializers.SlugRelatedField(read_only=True, slug_field="email")
    bank_change_pending = serializers.BooleanField(read_only=True)
    default_account = serializers.SerializerMethodField()

    class Meta:
        model = Supplier
        fields = [
            "id",
            "code",
            "name",
            "category",
            "address",
            "phone",
            "email",
            "contact_person",
            "contact_phone",
            "vat_no",
            "tin",
            "payment_terms_days",
            "currency",
            "notes",
            "is_active",
            "bank_changed_at",
            "bank_changed_by",
            "bank_change_pending",
            "default_account",
        ]

    def get_default_account(self, supplier):
        account = supplier.bank_accounts.filter(is_default=True, is_active=True).first()
        return None if account is None else BankAccountSerializer(account).data


class SupplierInput(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    category = serializers.CharField(max_length=20, required=False)
    address = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    contact_person = serializers.CharField(max_length=100, required=False, allow_blank=True)
    contact_phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    vat_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    tin = serializers.CharField(max_length=20, required=False, allow_blank=True)
    payment_terms_days = serializers.IntegerField(required=False)
    currency = serializers.CharField(max_length=3, required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    # Set after the user has seen and accepted the duplicate warnings.
    confirm_duplicates = serializers.BooleanField(required=False, default=False)


class BankAccountInput(serializers.Serializer):
    bank_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    branch = serializers.CharField(max_length=100, required=False, allow_blank=True)
    account_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    account_number = serializers.CharField(max_length=40, required=False, allow_blank=True)
    swift_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    is_default = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


def _error(error):
    if isinstance(error, suppliers.NeedsConfirmation):
        return Response(
            {"detail": str(error), "warnings": error.warnings, "needs_confirmation": True},
            status=status.HTTP_409_CONFLICT,
        )
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class _Payees(APIView):
    permission_classes = [AreaAccess]
    access_area = "payees"
    access_write_level = "enter"


class SupplierListView(_Payees):
    def get(self, request):
        rows = Supplier.objects.select_related("currency", "bank_changed_by")
        rows = suppliers.search(rows, request.query_params.get("q", ""))
        if request.query_params.get("category"):
            rows = rows.filter(category=request.query_params["category"])
        if request.query_params.get("include_inactive") not in ("1", "true"):
            rows = rows.filter(is_active=True)
        return Response(SupplierSerializer(rows[:2000], many=True).data)

    def post(self, request):
        data = SupplierInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        confirmed = values.pop("confirm_duplicates")
        values.pop("reason")
        values.pop("is_active", None)
        try:
            supplier = suppliers.create_supplier(request.user, values, confirmed=confirmed)
        except MastersError as error:
            return _error(error)
        return Response(SupplierSerializer(supplier).data, status=status.HTTP_201_CREATED)


class SupplierDetailView(_Payees):
    def get(self, request, pk):
        return Response(SupplierSerializer(get_object_or_404(Supplier, pk=pk)).data)

    def patch(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)
        data = SupplierInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        confirmed = values.pop("confirm_duplicates")
        reason = values.pop("reason")
        try:
            supplier = suppliers.update_supplier(
                request.user, supplier, values, reason=reason, confirmed=confirmed
            )
        except MastersError as error:
            return _error(error)
        return Response(SupplierSerializer(supplier).data)


class BankAccountListView(_Payees):
    def get(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)
        return Response(BankAccountSerializer(supplier.bank_accounts.all(), many=True).data)

    def post(self, request, pk):
        supplier = get_object_or_404(Supplier, pk=pk)
        data = BankAccountInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            account = suppliers.add_bank_account(request.user, supplier, values, reason=reason)
        except MastersError as error:
            return _error(error)
        return Response(BankAccountSerializer(account).data, status=status.HTTP_201_CREATED)


class BankAccountDetailView(_Payees):
    def patch(self, request, pk, account_pk):
        account = get_object_or_404(SupplierBankAccount, pk=account_pk, supplier_id=pk)
        data = BankAccountInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            account = suppliers.update_bank_account(request.user, account, values, reason=reason)
        except MastersError as error:
            return _error(error)
        return Response(BankAccountSerializer(account).data)


class AcknowledgeBankChangeView(_Payees):
    def post(self, request, pk):
        try:
            supplier = suppliers.acknowledge_bank_change(
                request.user, get_object_or_404(Supplier, pk=pk)
            )
        except MastersError as error:
            return _error(error)
        return Response(SupplierSerializer(supplier).data)
