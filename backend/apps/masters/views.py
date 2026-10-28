"""Sections, machines and section scope API (P0-09). Rules live in services.py."""

import mimetypes

from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import AccessError
from apps.core.models import Division, User
from apps.core.permissions import AreaAccess

from . import excel, services
from .models import Machine, MachineRate, Section

# --- Serializers ------------------------------------------------------------------------


class SectionSerializer(serializers.ModelSerializer):
    division = serializers.SlugRelatedField(read_only=True, slug_field="code")
    supervisors = serializers.SerializerMethodField()
    in_use = serializers.SerializerMethodField()
    machine_count = serializers.SerializerMethodField()

    class Meta:
        model = Section
        fields = [
            "id",
            "code",
            "name",
            "division",
            "section_type",
            "category",
            "supervisors",
            "is_active",
            "in_use",
            "machine_count",
        ]

    def get_supervisors(self, section):
        return [{"id": u.pk, "name": u.full_name} for u in section.supervisors.all()]

    def get_in_use(self, section) -> bool:
        return services.is_in_use(section)

    def get_machine_count(self, section) -> int:
        return section.machines.count()


class MachineSerializer(serializers.ModelSerializer):
    section = serializers.SlugRelatedField(read_only=True, slug_field="code")
    division = serializers.CharField(source="section.division.code", read_only=True)
    in_use = serializers.SerializerMethodField()
    has_photo = serializers.SerializerMethodField()
    current_rate = serializers.SerializerMethodField()

    class Meta:
        model = Machine
        fields = [
            "id",
            "code",
            "name",
            "section",
            "division",
            "make",
            "model",
            "serial_no",
            "year",
            "status",
            "notes",
            *services.MOULDING_FIELDS,
            "in_use",
            "has_photo",
            "current_rate",
        ]

    def get_in_use(self, machine) -> bool:
        return services.is_in_use(machine)

    def get_has_photo(self, machine) -> bool:
        return bool(machine.photo)

    def get_current_rate(self, machine):
        rate = services.rate_on(machine, timezone.localdate())
        return None if rate is None else str(rate)


class RateSerializer(serializers.ModelSerializer):
    created_by = serializers.SlugRelatedField(read_only=True, slug_field="email")
    in_force = serializers.SerializerMethodField()

    class Meta:
        model = MachineRate
        fields = ["id", "effective_from", "rate", "reason", "created_by", "created_at", "in_force"]

    def get_in_force(self, rate) -> bool:
        return rate.effective_from <= timezone.localdate()


class SectionInput(serializers.Serializer):
    code = serializers.CharField(max_length=30, required=False, allow_blank=True)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    division = serializers.CharField(max_length=2, required=False)
    section_type = serializers.CharField(required=False)
    category = serializers.CharField(required=False, allow_blank=True)
    supervisors = serializers.ListField(child=serializers.IntegerField(), required=False)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


def _optional_decimal():
    return serializers.CharField(required=False, allow_blank=True, allow_null=True)


class MachineInput(serializers.Serializer):
    code = serializers.CharField(max_length=30, required=False, allow_blank=True)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    section = serializers.CharField(max_length=30, required=False)
    make = serializers.CharField(required=False, allow_blank=True)
    model = serializers.CharField(required=False, allow_blank=True)
    serial_no = serializers.CharField(required=False, allow_blank=True)
    year = serializers.IntegerField(required=False, allow_null=True)
    status = serializers.CharField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)
    clamping_force_t = _optional_decimal()
    max_shot_weight_g = _optional_decimal()
    screw_diameter_mm = _optional_decimal()
    tie_bar_h_mm = _optional_decimal()
    tie_bar_v_mm = _optional_decimal()
    max_mould_height_mm = _optional_decimal()
    max_mould_thickness_mm = _optional_decimal()
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class RateInput(serializers.Serializer):
    effective_from = serializers.DateField()
    # Received as text so the amount is exact (rule 1).
    rate = serializers.CharField(max_length=30)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class UserSectionsInput(serializers.Serializer):
    all_sections = serializers.BooleanField()
    sections = serializers.ListField(
        child=serializers.CharField(max_length=30), required=False, default=list
    )


# --- Views ------------------------------------------------------------------------------


def _error(error, code=status.HTTP_400_BAD_REQUEST):
    return Response({"detail": str(error)}, status=code)


def _reason(request) -> str:
    return str(request.data.get("reason", "")) if hasattr(request.data, "get") else ""


class _Settings(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"


def _resolve_division(values):
    if "division" in values:
        code = values["division"].strip().upper()
        division = Division.objects.filter(code=code).first()
        if division is None:
            raise services.MastersError(f"Unknown division {code}.")
        values["division"] = division


def _resolve_section(values):
    if "section" in values:
        code = values["section"].strip().upper()
        section = Section.objects.filter(code=code).first()
        if section is None:
            raise services.MastersError(f"Unknown section {code}.")
        values["section"] = section


class SectionListView(_Settings):
    """Every section (the tree on the Divisions, sections and machines page)."""

    def get(self, request):
        sections = Section.objects.select_related("division").prefetch_related("supervisors")
        return Response(SectionSerializer(sections, many=True).data)

    def post(self, request):
        data = SectionInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            _resolve_division(values)
            if "division" not in values:
                raise services.MastersError("Choose the section's division.")
            section = services.create_section(
                code=values.pop("code", ""),
                name=values.pop("name", ""),
                section_type=values.pop("section_type", ""),
                reason=reason,
                **values,
            )
        except services.MastersError as error:
            return _error(error)
        return Response(SectionSerializer(section).data, status=status.HTTP_201_CREATED)


class SectionDetailView(_Settings):
    def get(self, request, pk):
        return Response(SectionSerializer(get_object_or_404(Section, pk=pk)).data)

    def patch(self, request, pk):
        section = get_object_or_404(Section, pk=pk)
        data = SectionInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            _resolve_division(values)
            section = services.update_section(section, values, reason=reason)
        except services.MastersError as error:
            return _error(error)
        return Response(SectionSerializer(section).data)

    def delete(self, request, pk):
        try:
            services.delete_section(get_object_or_404(Section, pk=pk), reason=_reason(request))
        except services.MastersError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MachineListView(_Settings):
    def get(self, request):
        machines = Machine.objects.select_related("section__division")
        return Response(MachineSerializer(machines, many=True).data)

    def post(self, request):
        data = MachineInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            _resolve_section(values)
            if "section" not in values:
                raise services.MastersError("Choose the machine's section.")
            machine = services.create_machine(
                code=values.pop("code", ""), section=values.pop("section"), reason=reason, **values
            )
        except services.MastersError as error:
            return _error(error)
        return Response(MachineSerializer(machine).data, status=status.HTTP_201_CREATED)


class MachineDetailView(_Settings):
    def get(self, request, pk):
        return Response(MachineSerializer(get_object_or_404(Machine, pk=pk)).data)

    def patch(self, request, pk):
        machine = get_object_or_404(Machine, pk=pk)
        data = MachineInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            _resolve_section(values)
            machine = services.update_machine(machine, values, reason=reason)
        except services.MastersError as error:
            return _error(error)
        return Response(MachineSerializer(machine).data)

    def delete(self, request, pk):
        try:
            services.delete_machine(get_object_or_404(Machine, pk=pk), reason=_reason(request))
        except services.MastersError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MachineRatesView(_Settings):
    def get(self, request, pk):
        machine = get_object_or_404(Machine, pk=pk)
        return Response(RateSerializer(machine.rates.all(), many=True).data)

    def post(self, request, pk):
        machine = get_object_or_404(Machine, pk=pk)
        data = RateInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            rate = services.add_rate(machine, user=request.user, **data.validated_data)
        except services.MastersError as error:
            return _error(error)
        return Response(RateSerializer(rate).data, status=status.HTTP_201_CREATED)


class MachineRateDetailView(_Settings):
    def delete(self, request, pk, rate_pk):
        rate = get_object_or_404(MachineRate, pk=rate_pk, machine_id=pk)
        try:
            services.remove_rate(rate, reason=_reason(request))
        except services.MastersError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MachinePhotoView(_Settings):
    parser_classes = [MultiPartParser, JSONParser]

    def get(self, request, pk):
        machine = get_object_or_404(Machine, pk=pk)
        if not machine.photo:
            raise Http404("No photo has been uploaded.")
        content_type = mimetypes.guess_type(machine.photo.name)[0] or "application/octet-stream"
        response = FileResponse(machine.photo.open("rb"), content_type=content_type)
        response["Cache-Control"] = "private, max-age=300"
        response["X-Content-Type-Options"] = "nosniff"
        return response

    def put(self, request, pk):
        machine = get_object_or_404(Machine, pk=pk)
        uploaded = request.FILES.get("photo")
        if uploaded is None:
            return _error("Choose a photo to upload.")
        try:
            machine = services.set_machine_photo(machine, uploaded)
        except services.MastersError as error:
            return _error(error)
        return Response(MachineSerializer(machine).data)

    def delete(self, request, pk):
        machine = services.remove_machine_photo(get_object_or_404(Machine, pk=pk))
        return Response(MachineSerializer(machine).data)


class FactoryExportView(_Settings):
    def get(self, request):
        today = timezone.localdate().isoformat()
        response = HttpResponse(
            excel.export_workbook(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="sections-and-machines-{today}.xlsx"'
        )
        return response


class FactoryImportView(_Settings):
    """Import sections and machines from Excel. `dry_run` checks without saving."""

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
                uploaded.read(), reason=_reason(request), user=request.user, dry_run=dry_run
            )
        except excel.ImportRefused as refused:
            return Response(
                {"detail": "Nothing was imported.", "errors": refused.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"dry_run": dry_run, **counts})


# --- Section scope ----------------------------------------------------------------------


class UserSectionsView(APIView):
    """Which sections a user is limited to (spec 1.1), on the user access page."""

    permission_classes = [AreaAccess]
    access_area = "users"
    access_write_level = "manage"

    def get(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        return Response(
            {
                "all_sections": user.all_sections,
                "sections": sorted(user.sections.values_list("code", flat=True)),
            }
        )

    def put(self, request, pk):
        user = get_object_or_404(User, pk=pk)
        data = UserSectionsInput(data=request.data)
        data.is_valid(raise_exception=True)
        codes = {c.strip().upper() for c in data.validated_data["sections"]}
        sections = list(Section.objects.filter(code__in=codes))
        if len(sections) != len(codes):
            return _error("Unknown section.")
        try:
            services.set_user_sections(
                request.user, user, data.validated_data["all_sections"], sections
            )
        except AccessError as error:
            return _error(error, status.HTTP_403_FORBIDDEN)
        return self.get(request, pk)


class SectionPickerView(APIView):
    """Active sections the user may work in (used by entry pages and filters)."""

    def get(self, request):
        sections = services.section_scope(request.user).select_related("division")
        if request.query_params.get("include_inactive") not in ("1", "true"):
            sections = sections.filter(is_active=True)
        return Response(
            [
                {"id": s.id, "code": s.code, "name": s.name, "division": s.division.code}
                for s in sections
            ]
        )


class MachinePickerView(APIView):
    """Machines in the user's sections; retired machines only when asked for (filters)."""

    def get(self, request):
        machines = services.filter_by_section(
            Machine.objects.select_related("section"), request.user
        )
        if request.query_params.get("include_retired") not in ("1", "true"):
            machines = machines.exclude(status=Machine.Status.RETIRED)
        section = request.query_params.get("section")
        if section:
            machines = machines.filter(section__code=section.upper())
        return Response(
            [
                {
                    "id": m.id,
                    "code": m.code,
                    "name": m.name,
                    "section": m.section.code,
                    "status": m.status,
                }
                for m in machines
            ]
        )
