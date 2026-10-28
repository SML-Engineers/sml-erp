"""Shifts and rosters API (P0-10). Rules live in rosters.py."""

from datetime import date

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Division
from apps.core.permissions import AreaAccess

from . import rosters
from .models import Crew, RosterAssignment, RosterPattern, Section, Shift
from .services import MastersError

# --- Serializers ------------------------------------------------------------------------


class ShiftSerializer(serializers.ModelSerializer):
    crosses_midnight = serializers.BooleanField(read_only=True)
    working_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Shift
        fields = [
            "id",
            "code",
            "name",
            "start_time",
            "end_time",
            "break_minutes",
            "crosses_midnight",
            "working_minutes",
            "is_active",
        ]


class PatternSerializer(serializers.ModelSerializer):
    days = serializers.SerializerMethodField()
    summary = serializers.SerializerMethodField()

    class Meta:
        model = RosterPattern
        fields = ["id", "name", "days", "summary", "is_active"]

    def get_days(self, pattern):
        return [d.shift.code if d.shift else None for d in pattern.days.select_related("shift")]

    def get_summary(self, pattern):
        return rosters.pattern_summary(pattern)


class CrewSerializer(serializers.ModelSerializer):
    division = serializers.SlugRelatedField(read_only=True, slug_field="code")

    class Meta:
        model = Crew
        fields = ["id", "code", "name", "division", "is_active"]


class AssignmentSerializer(serializers.ModelSerializer):
    pattern = serializers.SlugRelatedField(read_only=True, slug_field="name")
    pattern_id = serializers.IntegerField(read_only=True)
    division = serializers.SlugRelatedField(read_only=True, slug_field="code")
    section = serializers.SlugRelatedField(read_only=True, slug_field="code")
    crews = serializers.SerializerMethodField()
    started = serializers.SerializerMethodField()

    class Meta:
        model = RosterAssignment
        fields = [
            "id",
            "pattern",
            "pattern_id",
            "division",
            "section",
            "start_date",
            "end_date",
            "note",
            "crews",
            "started",
        ]

    def get_crews(self, assignment):
        return [
            {"crew": rc.crew.code, "start_day": rc.start_position + 1}
            for rc in assignment.crews.select_related("crew")
        ]

    def get_started(self, assignment) -> bool:
        return assignment.start_date <= timezone.localdate()


class ShiftInput(serializers.Serializer):
    code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    name = serializers.CharField(max_length=50, required=False, allow_blank=True)
    start_time = serializers.TimeField(required=False)
    end_time = serializers.TimeField(required=False)
    break_minutes = serializers.IntegerField(required=False, min_value=0, max_value=1440)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class PatternInput(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    # Shift codes in cycle order; empty or null = Off.
    days = serializers.ListField(
        child=serializers.CharField(allow_blank=True, allow_null=True, max_length=5),
        required=False,
    )
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CrewInput(serializers.Serializer):
    code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    division = serializers.CharField(max_length=2, required=False)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class RosterCrewInput(serializers.Serializer):
    crew = serializers.CharField(max_length=20)
    start_day = serializers.IntegerField(min_value=1)  # day of the cycle, 1 = first


class AssignmentInput(serializers.Serializer):
    pattern = serializers.IntegerField(required=False)
    division = serializers.CharField(max_length=2, required=False)
    section = serializers.CharField(
        max_length=30, required=False, allow_blank=True, allow_null=True
    )
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False, allow_null=True)
    crews = RosterCrewInput(many=True, required=False)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


# --- Helpers ----------------------------------------------------------------------------


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _reason(request) -> str:
    return str(request.data.get("reason", "")) if hasattr(request.data, "get") else ""


def _division(code) -> Division:
    division = Division.objects.filter(code=(code or "").strip().upper()).first()
    if division is None:
        raise MastersError(f"Unknown division {code}.")
    return division


def _section(code) -> Section | None:
    if not code:
        return None
    section = Section.objects.filter(code=code.strip().upper()).first()
    if section is None:
        raise MastersError(f"Unknown section {code}.")
    return section


def _shift_ids(codes) -> list:
    ids = []
    for code in codes:
        if not code:
            ids.append(None)
            continue
        shift = Shift.objects.filter(code=code.strip().upper()).first()
        if shift is None:
            raise MastersError(f"Unknown shift {code}.")
        ids.append(shift.pk)
    return ids


def _assignment_values(values: dict, division: Division | None) -> dict:
    if "pattern" in values:
        pattern = RosterPattern.objects.filter(pk=values["pattern"]).first()
        if pattern is None:
            raise MastersError("Unknown roster pattern.")
        values["pattern"] = pattern
    if "division" in values:
        values["division"] = division = _division(values["division"])
    if "section" in values:
        values["section"] = _section(values["section"])
    if "crews" in values:
        crews = []
        for item in values["crews"]:
            crew = Crew.objects.filter(division=division, code=item["crew"].strip().upper()).first()
            if crew is None:
                raise MastersError(f"Unknown crew {item['crew']} in {division.code}.")
            crews.append((crew, item["start_day"] - 1))
        values["crews"] = crews
    return values


class _Settings(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"


# --- Views ------------------------------------------------------------------------------


class ShiftListView(_Settings):
    def get(self, request):
        return Response(ShiftSerializer(Shift.objects.all(), many=True).data)

    def post(self, request):
        data = ShiftInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        if "start_time" not in v or "end_time" not in v:
            return _error("Give the shift's start and end times.")
        try:
            shift = rosters.create_shift(
                code=v.get("code", ""),
                name=v.get("name", ""),
                start_time=v["start_time"],
                end_time=v["end_time"],
                break_minutes=v.get("break_minutes", 0),
                reason=v["reason"],
            )
        except MastersError as error:
            return _error(error)
        return Response(ShiftSerializer(shift).data, status=status.HTTP_201_CREATED)


class ShiftDetailView(_Settings):
    def get(self, request, pk):
        return Response(ShiftSerializer(get_object_or_404(Shift, pk=pk)).data)

    def patch(self, request, pk):
        shift = get_object_or_404(Shift, pk=pk)
        data = ShiftInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            shift = rosters.update_shift(shift, values, reason=reason)
        except MastersError as error:
            return _error(error)
        return Response(ShiftSerializer(shift).data)


class PatternListView(_Settings):
    def get(self, request):
        return Response(PatternSerializer(RosterPattern.objects.all(), many=True).data)

    def post(self, request):
        data = PatternInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            pattern = rosters.create_pattern(
                name=v.get("name", ""), days=_shift_ids(v.get("days", [])), reason=v["reason"]
            )
        except MastersError as error:
            return _error(error)
        return Response(PatternSerializer(pattern).data, status=status.HTTP_201_CREATED)


class PatternDetailView(_Settings):
    def get(self, request, pk):
        return Response(PatternSerializer(get_object_or_404(RosterPattern, pk=pk)).data)

    def patch(self, request, pk):
        pattern = get_object_or_404(RosterPattern, pk=pk)
        data = PatternInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            if "days" in values:
                values["days"] = _shift_ids(values["days"])
            pattern = rosters.update_pattern(pattern, values, reason=reason)
        except MastersError as error:
            return _error(error)
        return Response(PatternSerializer(pattern).data)


class CrewListView(_Settings):
    def get(self, request):
        crews = Crew.objects.select_related("division")
        return Response(CrewSerializer(crews, many=True).data)

    def post(self, request):
        data = CrewInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            crew = rosters.create_crew(
                division=_division(v.get("division")),
                code=v.get("code", ""),
                name=v.get("name", ""),
                reason=v["reason"],
            )
        except MastersError as error:
            return _error(error)
        return Response(CrewSerializer(crew).data, status=status.HTTP_201_CREATED)


class CrewDetailView(_Settings):
    def patch(self, request, pk):
        crew = get_object_or_404(Crew, pk=pk)
        data = CrewInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("division", None)  # a crew stays in its division
        reason = values.pop("reason")
        try:
            crew = rosters.update_crew(crew, values, reason=reason)
        except MastersError as error:
            return _error(error)
        return Response(CrewSerializer(crew).data)


class AssignmentListView(_Settings):
    def get(self, request):
        assignments = RosterAssignment.objects.select_related("pattern", "division", "section")
        division = request.query_params.get("division")
        if division:
            assignments = assignments.filter(division__code=division.upper())
        return Response(AssignmentSerializer(assignments, many=True).data)

    def post(self, request):
        data = AssignmentInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            for key in ("pattern", "division", "start_date"):
                if key not in values:
                    raise MastersError("Choose the pattern, the division and the start date.")
            values = _assignment_values(values, None)
            assignment = rosters.create_assignment(reason=reason, **values)
        except MastersError as error:
            return _error(error)
        return Response(AssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)


class AssignmentDetailView(_Settings):
    def get(self, request, pk):
        return Response(AssignmentSerializer(get_object_or_404(RosterAssignment, pk=pk)).data)

    def patch(self, request, pk):
        assignment = get_object_or_404(RosterAssignment, pk=pk)
        data = AssignmentInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        reason = values.pop("reason")
        try:
            values = _assignment_values(values, assignment.division)
            assignment = rosters.update_assignment(assignment, values, reason=reason)
        except MastersError as error:
            return _error(error)
        return Response(AssignmentSerializer(assignment).data)

    def delete(self, request, pk):
        try:
            rosters.delete_assignment(
                get_object_or_404(RosterAssignment, pk=pk), reason=_reason(request)
            )
        except MastersError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RosterPreviewView(_Settings):
    """Who is on each shift each day (default: 4 weeks from today), with warnings."""

    def get(self, request):
        params = request.query_params
        try:
            division = _division(params.get("division"))
            section = _section(params.get("section"))
            start = date.fromisoformat(params["start"]) if params.get("start") else None
            days = int(params.get("days", 28))
            start = start or timezone.localdate()
            plan = rosters.schedule(division, start, days, section)
            found = rosters.warnings(division, start, days, section)
        except (MastersError, ValueError) as error:
            return _error(error)
        return Response(
            {
                "start": start,
                "days": [
                    {
                        "date": day,
                        "shifts": [
                            {
                                "shift": e.shift.code,
                                "shift_name": e.shift.name,
                                "crew": e.crew.code if e.crew else None,
                                "section": e.assignment.section.code
                                if e.assignment.section
                                else None,
                                "starts": e.starts,
                                "ends": e.ends,
                            }
                            for e in entries
                        ],
                    }
                    for day, entries in plan
                ],
                "warnings": found,
            }
        )
