"""Customers API (P15-01). Rules live in customers.py; every endpoint checks Sales access."""

from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess

from . import customers, excel
from .models import Customer, CustomerContact
from .services import MastersError


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerContact
        fields = ["id", "name", "position", "phone", "email", "is_main", "is_active"]


class CustomerSerializer(serializers.ModelSerializer):
    currency = serializers.SlugRelatedField(read_only=True, slug_field="code")
    main_contact = serializers.SerializerMethodField()
    in_use = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id",
            "code",
            "name",
            "billing_address",
            "delivery_address",
            "phone",
            "email",
            "vat_no",
            "tin",
            "currency",
            "payment_terms_days",
            "credit_limit",
            "is_export",
            "country",
            "incoterm",
            "port_of_destination",
            "notes",
            "is_active",
            "main_contact",
            "in_use",
        ]

    def get_main_contact(self, customer):
        main = next((c for c in customer.contacts.all() if c.is_main), None)
        return None if main is None else ContactSerializer(main).data

    def get_in_use(self, customer):
        return customer.first_used_at is not None


class CustomerInput(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    billing_address = serializers.CharField(required=False, allow_blank=True)
    delivery_address = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    email = serializers.CharField(max_length=254, required=False, allow_blank=True)
    vat_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    tin = serializers.CharField(max_length=20, required=False, allow_blank=True)
    currency = serializers.CharField(max_length=3, required=False)
    payment_terms_days = serializers.IntegerField(required=False)
    credit_limit = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    is_export = serializers.BooleanField(required=False)
    country = serializers.CharField(max_length=60, required=False, allow_blank=True)
    incoterm = serializers.CharField(max_length=3, required=False, allow_blank=True)
    port_of_destination = serializers.CharField(max_length=100, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    # Set after the user has seen and accepted the duplicate warnings.
    confirm_duplicates = serializers.BooleanField(required=False, default=False)


class ContactInput(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    position = serializers.CharField(max_length=100, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    email = serializers.CharField(max_length=254, required=False, allow_blank=True)
    is_main = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)


def _error(error):
    if isinstance(error, customers.NeedsConfirmation):
        return Response(
            {"detail": str(error), "warnings": error.warnings, "needs_confirmation": True},
            status=status.HTTP_409_CONFLICT,
        )
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _rows():
    return Customer.objects.select_related("currency").prefetch_related(
        Prefetch("contacts", queryset=CustomerContact.objects.filter(is_active=True))
    )


class _Sales(APIView):
    permission_classes = [AreaAccess]
    access_area = "sales"
    access_write_level = "enter"


class CustomerListView(_Sales):
    def get(self, request):
        rows = customers.search(_rows(), request.query_params.get("q", ""))
        if request.query_params.get("include_inactive") not in ("1", "true"):
            rows = rows.filter(is_active=True)
        if request.query_params.get("export") in ("1", "true"):
            rows = rows.filter(is_export=True)
        return Response(CustomerSerializer(rows[:2000], many=True).data)

    def post(self, request):
        data = CustomerInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        confirmed = values.pop("confirm_duplicates")
        values.pop("reason")
        values.pop("is_active", None)
        try:
            customer = customers.create_customer(request.user, values, confirmed=confirmed)
        except MastersError as error:
            return _error(error)
        return Response(
            CustomerSerializer(_rows().get(pk=customer.pk)).data, status=status.HTTP_201_CREATED
        )


class CustomerDetailView(_Sales):
    def get(self, request, pk):
        return Response(CustomerSerializer(get_object_or_404(_rows(), pk=pk)).data)

    def patch(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        data = CustomerInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        confirmed = values.pop("confirm_duplicates")
        reason = values.pop("reason")
        try:
            customers.update_customer(
                request.user, customer, values, reason=reason, confirmed=confirmed
            )
        except MastersError as error:
            return _error(error)
        return Response(CustomerSerializer(_rows().get(pk=pk)).data)


class ContactListView(_Sales):
    def get(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        return Response(ContactSerializer(customer.contacts.all(), many=True).data)

    def post(self, request, pk):
        customer = get_object_or_404(Customer, pk=pk)
        data = ContactInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            contact = customers.add_contact(request.user, customer, dict(data.validated_data))
        except MastersError as error:
            return _error(error)
        return Response(ContactSerializer(contact).data, status=status.HTTP_201_CREATED)


class ContactDetailView(_Sales):
    def patch(self, request, pk, contact_pk):
        contact = get_object_or_404(CustomerContact, pk=contact_pk, customer_id=pk)
        data = ContactInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            contact = customers.update_contact(request.user, contact, dict(data.validated_data))
        except MastersError as error:
            return _error(error)
        return Response(ContactSerializer(contact).data)


class CustomerExportView(_Sales):
    def get(self, request):
        rows = _rows()
        if request.query_params.get("include_inactive") not in ("1", "true"):
            rows = rows.filter(is_active=True)
        response = HttpResponse(
            customers.export_workbook(rows.order_by("code")),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        today = timezone.localdate().isoformat()
        response["Content-Disposition"] = f'attachment; filename="customers-{today}.xlsx"'
        return response


class CustomerImportView(_Sales):
    """Import customers from Excel. `dry_run` checks every row without saving."""

    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose an Excel file to import.")
        if uploaded.size > excel.MAX_BYTES:
            return _error("The file must be 5 MB or smaller.")
        dry_run = str(request.data.get("dry_run", "")).lower() in ("1", "true", "yes")
        try:
            counts = customers.import_workbook(
                uploaded.read(),
                user=request.user,
                reason=str(request.data.get("reason", "")),
                dry_run=dry_run,
            )
        except excel.ImportRefused as refused:
            return Response(
                {"detail": "Nothing was imported.", "errors": refused.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"dry_run": dry_run, **counts})
