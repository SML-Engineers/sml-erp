"""Company profile and Divisions control panel API (P0-07). Rules live in organisation.py."""

import mimetypes

from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView

from . import organisation
from .models import Company, Division
from .permissions import AreaAccess, IsFullyAuthenticated


class CompanySerializer(serializers.ModelSerializer):
    has_logo = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "name",
            "registration_no",
            "tin",
            "vat_no",
            "address",
            "phone",
            "email",
            "website",
            "base_currency",
            "financial_year_start_month",
            "has_logo",
            "updated_at",
        ]
        read_only_fields = ["base_currency", "updated_at"]

    def get_has_logo(self, company) -> bool:
        return bool(company.logo)


class CompanyInput(serializers.Serializer):
    name = serializers.CharField(max_length=200, required=False)
    registration_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    tin = serializers.CharField(max_length=50, required=False, allow_blank=True)
    vat_no = serializers.CharField(max_length=50, required=False, allow_blank=True)
    address = serializers.CharField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    website = serializers.CharField(max_length=200, required=False, allow_blank=True)
    base_currency = serializers.CharField(max_length=3, required=False)
    financial_year_start_month = serializers.IntegerField(min_value=1, max_value=12, required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class DivisionAdminSerializer(serializers.ModelSerializer):
    in_use = serializers.SerializerMethodField()
    users = serializers.SerializerMethodField()

    class Meta:
        model = Division
        fields = [
            "id",
            "code",
            "name",
            "division_type",
            "is_active",
            "in_use",
            "first_used_at",
            "users",
            "created_at",
        ]

    def get_in_use(self, division) -> bool:
        return organisation.is_in_use(division)

    def get_users(self, division) -> int:
        return division.users.count()


class DivisionInput(serializers.Serializer):
    code = serializers.CharField(max_length=10, required=False)
    name = serializers.CharField(max_length=100, required=False)
    division_type = serializers.CharField(required=False)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


def _error(error: organisation.OrganisationError):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class _ReadForAllWriteForSettings(APIView):
    """Anyone signed in may read (printing, page headers); changes need Settings: Manage."""

    access_area = "settings"
    access_write_level = "manage"

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [IsFullyAuthenticated()]
        return [AreaAccess()]


class CompanyView(_ReadForAllWriteForSettings):
    def get(self, request):
        return Response(CompanySerializer(Company.get()).data)

    def put(self, request):
        data = CompanyInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            company = organisation.update_company(values, reason=reason)
        except organisation.OrganisationError as error:
            return _error(error)
        return Response(CompanySerializer(company).data)


class CompanyLogoView(_ReadForAllWriteForSettings):
    parser_classes = [MultiPartParser]

    def get(self, request):
        company = Company.get()
        if not company.logo:
            raise Http404("No logo has been uploaded.")
        content_type = mimetypes.guess_type(company.logo.name)[0] or "application/octet-stream"
        response = FileResponse(company.logo.open("rb"), content_type=content_type)
        response["Cache-Control"] = "private, max-age=300"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def put(self, request):
        uploaded = request.FILES.get("logo")
        if uploaded is None:
            return Response(
                {"detail": "Choose an image file to upload."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            company = organisation.set_company_logo(uploaded)
        except organisation.OrganisationError as error:
            return _error(error)
        return Response(CompanySerializer(company).data)

    def delete(self, request):
        company = organisation.remove_company_logo()
        return Response(CompanySerializer(company).data)


class DivisionAdminListView(APIView):
    """The Divisions control panel: every division, active or not."""

    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"

    def get(self, request):
        return Response(DivisionAdminSerializer(Division.objects.all(), many=True).data)

    def post(self, request):
        data = DivisionInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        try:
            division = organisation.create_division(
                code=values.get("code", ""),
                name=values.get("name", ""),
                division_type=values.get("division_type", Division.Type.PRODUCTION),
                reason=values["reason"],
            )
        except organisation.OrganisationError as error:
            return _error(error)
        return Response(DivisionAdminSerializer(division).data, status=status.HTTP_201_CREATED)


class DivisionAdminDetailView(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"

    def get(self, request, pk):
        return Response(DivisionAdminSerializer(get_object_or_404(Division, pk=pk)).data)

    def patch(self, request, pk):
        division = get_object_or_404(Division, pk=pk)
        data = DivisionInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            division = organisation.update_division(division, values, reason=reason)
        except organisation.OrganisationError as error:
            return _error(error)
        return Response(DivisionAdminSerializer(division).data)

    def delete(self, request, pk):
        division = get_object_or_404(Division, pk=pk)
        reason = str(request.data.get("reason", "")) if hasattr(request.data, "get") else ""
        try:
            organisation.delete_division(division, reason=reason)
        except organisation.OrganisationError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)
