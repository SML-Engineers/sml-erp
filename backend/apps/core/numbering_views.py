"""Number series settings API (P0-08). Rules live in numbering.py."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import numbering
from .models import Division, NumberSeries
from .permissions import AreaAccess


def _examples(series: NumberSeries, number_format=None, reset_period=None) -> list[dict]:
    """The next number for each active division (or one shared example without {PP})."""
    parsed = numbering.check(
        series.format if number_format is None else number_format,
        series.reset_period if reset_period is None else reset_period,
    )
    divisions = list(Division.objects.filter(is_active=True)) if parsed.has_division else [None]
    return [
        {
            "division": division.code if division else None,
            "next": numbering.preview(
                series,
                division=division,
                number_format=number_format,
                reset_period=reset_period,
            ),
        }
        for division in divisions
    ]


class NumberSeriesSerializer(serializers.ModelSerializer):
    next_numbers = serializers.SerializerMethodField()

    class Meta:
        model = NumberSeries
        fields = ["id", "document_type", "name", "format", "reset_period", "next_numbers"]

    def get_next_numbers(self, series) -> list[dict]:
        try:
            return _examples(series)
        except numbering.NumberSeriesError:
            return []


class SeriesInput(serializers.Serializer):
    format = serializers.CharField(max_length=60)
    reset_period = serializers.ChoiceField(choices=NumberSeries.Reset.choices)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class _SettingsArea(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"


class NumberSeriesListView(_SettingsArea):
    def get(self, request):
        series = NumberSeries.objects.all()
        return Response(NumberSeriesSerializer(series, many=True).data)


class NumberSeriesDetailView(_SettingsArea):
    def get(self, request, pk):
        return Response(NumberSeriesSerializer(get_object_or_404(NumberSeries, pk=pk)).data)

    def patch(self, request, pk):
        series = get_object_or_404(NumberSeries, pk=pk)
        data = SeriesInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            series = numbering.update_series(
                series,
                number_format=data.validated_data["format"],
                reset_period=data.validated_data["reset_period"],
                reason=data.validated_data["reason"],
            )
        except numbering.NumberSeriesError as error:
            return _error(error)
        return Response(NumberSeriesSerializer(series).data)


class NumberSeriesPreviewView(_SettingsArea):
    """Check a proposed format and show the numbers it would give next, without saving."""

    def post(self, request, pk):
        series = get_object_or_404(NumberSeries, pk=pk)
        data = SeriesInput(data=request.data)
        data.is_valid(raise_exception=True)
        try:
            examples = _examples(
                series,
                number_format=data.validated_data["format"],
                reset_period=data.validated_data["reset_period"],
            )
        except numbering.NumberSeriesError as error:
            return _error(error)
        return Response({"next_numbers": examples})
