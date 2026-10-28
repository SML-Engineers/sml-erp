"""Currencies and exchange rates API (P0-11). Rules live in currencies.py."""

from datetime import date

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess, ReadForAllAreaWrite

from . import currencies
from .models import Currency, ExchangeRate
from .services import MastersError


class CurrencySerializer(serializers.ModelSerializer):
    latest_rate = serializers.SerializerMethodField()

    class Meta:
        model = Currency
        fields = [
            "id",
            "code",
            "name",
            "symbol",
            "decimal_places",
            "is_base",
            "is_active",
            "latest_rate",
        ]

    def get_latest_rate(self, currency):
        if currency.is_base:
            return None
        latest = currency.rates.order_by("-date").first()
        return None if latest is None else {"date": latest.date, "rate": str(latest.rate)}


class RateSerializer(serializers.ModelSerializer):
    currency = serializers.SlugRelatedField(read_only=True, slug_field="code")
    created_by = serializers.SlugRelatedField(read_only=True, slug_field="email")
    used = serializers.SerializerMethodField()

    class Meta:
        model = ExchangeRate
        fields = [
            "id",
            "currency",
            "date",
            "rate",
            "buying",
            "selling",
            "source",
            "created_by",
            "created_at",
            "used",
        ]

    def get_used(self, rate) -> bool:
        return rate.first_used_at is not None


class CurrencyInput(serializers.Serializer):
    code = serializers.CharField(max_length=10, required=False, allow_blank=True)
    name = serializers.CharField(max_length=60, required=False, allow_blank=True)
    symbol = serializers.CharField(max_length=8, required=False, allow_blank=True)
    decimal_places = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class RateInput(serializers.Serializer):
    currency = serializers.CharField(max_length=3)
    date = serializers.DateField()
    # Text, so amounts stay exact (rule 1).
    rate = serializers.CharField(max_length=30, required=False, allow_blank=True)
    buying = serializers.CharField(max_length=30, required=False, allow_blank=True)
    selling = serializers.CharField(max_length=30, required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


class _CurrencySettings(APIView):
    permission_classes = [AreaAccess]
    access_area = "settings"
    access_write_level = "manage"


class _Rates(APIView):
    """Anyone signed in may read rates (documents need them); the Accountant enters them."""

    permission_classes = [ReadForAllAreaWrite]
    access_area = "accounting"
    access_write_level = "enter"


class CurrencyListView(_CurrencySettings):
    def get(self, request):
        return Response(CurrencySerializer(Currency.objects.all(), many=True).data)

    def post(self, request):
        data = CurrencyInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            currency = currencies.create_currency(
                code=v.get("code", ""),
                name=v.get("name", ""),
                symbol=v.get("symbol", ""),
                decimal_places=v.get("decimal_places", 2),
                reason=v["reason"],
            )
        except MastersError as error:
            return _error(error)
        return Response(CurrencySerializer(currency).data, status=status.HTTP_201_CREATED)


class CurrencyDetailView(_CurrencySettings):
    def patch(self, request, code):
        currency = get_object_or_404(Currency, code=code.upper())
        data = CurrencyInput(data=request.data)
        data.is_valid(raise_exception=True)
        values = dict(data.validated_data)
        values.pop("code", None)  # the ISO code never changes
        reason = values.pop("reason")
        try:
            currency = currencies.update_currency(currency, values, reason=reason)
        except MastersError as error:
            return _error(error)
        return Response(CurrencySerializer(currency).data)


class CurrencyPickerView(APIView):
    """Active currencies, for every currency picker (customers, quotations, invoices)."""

    def get(self, request):
        return Response(
            [
                {
                    "code": c.code,
                    "name": c.name,
                    "symbol": c.symbol,
                    "decimal_places": c.decimal_places,
                }
                for c in Currency.objects.filter(is_active=True)
            ]
        )


class RateListView(_Rates):
    def get(self, request):
        rates = ExchangeRate.objects.select_related("currency", "created_by")
        params = request.query_params
        if params.get("currency"):
            rates = rates.filter(currency__code=params["currency"].upper())
        try:
            if params.get("from"):
                rates = rates.filter(date__gte=date.fromisoformat(params["from"]))
            if params.get("to"):
                rates = rates.filter(date__lte=date.fromisoformat(params["to"]))
        except ValueError:
            return _error("Dates must be written as YYYY-MM-DD.")
        return Response(RateSerializer(rates[:1000], many=True).data)

    def post(self, request):
        data = RateInput(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        try:
            rate = currencies.set_rate(
                currency=currencies._currency_for_rates(v["currency"]),
                on_date=v["date"],
                rate=v.get("rate"),
                buying=v.get("buying"),
                selling=v.get("selling"),
                user=request.user,
                reason=v["reason"],
            )
        except MastersError as error:
            return _error(error)
        return Response(RateSerializer(rate).data, status=status.HTTP_201_CREATED)


class RateDetailView(_Rates):
    def delete(self, request, pk):
        rate = get_object_or_404(ExchangeRate, pk=pk)
        reason = str(request.data.get("reason", "")) if hasattr(request.data, "get") else ""
        try:
            currencies.delete_rate(rate, reason=reason)
        except MastersError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class RateImportView(_Rates):
    parser_classes = [MultiPartParser]

    def post(self, request):
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose a CSV file to import.")
        if uploaded.size > currencies.IMPORT_MAX_BYTES:
            return _error("The file must be 1 MB or smaller.")
        dry_run = str(request.data.get("dry_run", "")).lower() in ("1", "true", "yes")
        try:
            result = currencies.import_rates(
                uploaded.read(),
                user=request.user,
                reason=str(request.data.get("reason", "")),
                dry_run=dry_run,
            )
        except currencies.ImportRefused as refused:
            return Response(
                {"detail": "Nothing was imported.", "errors": refused.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(result)


class RateLookupView(APIView):
    """The rate a document dated `date` uses, and whether it was carried forward."""

    def get(self, request):
        try:
            on_date = (
                date.fromisoformat(request.query_params.get("date") or "")
                if request.query_params.get("date")
                else timezone.localdate()
            )
            lookup = currencies.rate_on(request.query_params.get("currency", ""), on_date)
        except (MastersError, ValueError) as error:
            return _error(error)
        return Response(
            {
                "currency": lookup.currency,
                "date": lookup.asked_for,
                "rate": str(lookup.rate),
                "rate_date": lookup.rate_date,
                "carried_forward": lookup.carried_forward,
            }
        )
