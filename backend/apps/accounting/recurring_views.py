"""Recurring journals API (P2-02). Rules live in recurring.py. Reading needs Accounting:
View; keeping templates needs Accounting: Enter."""

from django.shortcuts import get_object_or_404
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess

from . import recurring
from .manual_views import LineIn, _lines
from .models import RecurringJournal
from .services import AccountingError


class _Recurring(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _detail(t: RecurringJournal) -> dict:
    lines = list(t.lines.select_related("account", "division", "supplier"))
    return {
        "id": t.pk,
        "name": t.name,
        "narration": t.narration,
        "frequency": t.frequency,
        "day_of_month": t.day_of_month,
        "start_date": t.start_date,
        "end_date": t.end_date,
        "next_date": t.next_date,
        "reverse_next_month": t.reverse_next_month,
        "is_active": t.is_active,
        "created_by": t.created_by.full_name,
        "amount": f"{sum(x.debit for x in lines):.2f}",
        "made": [
            {"id": j.pk, "number": j.number, "entry_date": j.entry_date, "status": j.status}
            for j in t.journals.order_by("-entry_date", "-number")[:24]
        ],
        "lines": [
            {
                "line_no": x.line_no,
                "account": {
                    "id": x.account_id,
                    "number": x.account.number,
                    "name": x.account.name,
                    "account_type": x.account.account_type,
                },
                "division": x.division.code if x.division else None,
                "supplier": None
                if x.supplier is None
                else {"id": x.supplier_id, "code": x.supplier.code, "name": x.supplier.name},
                "description": x.description,
                "debit": f"{x.debit:.2f}",
                "credit": f"{x.credit:.2f}",
            }
            for x in lines
        ],
    }


class TemplateIn(serializers.Serializer):
    name = serializers.CharField(max_length=100, allow_blank=True)
    narration = serializers.CharField(max_length=400, allow_blank=True)
    frequency = serializers.CharField(max_length=10)
    day_of_month = serializers.IntegerField()
    start_date = serializers.DateField()
    end_date = serializers.DateField(required=False, allow_null=True)
    reverse_next_month = serializers.BooleanField(required=False, default=False)
    lines = LineIn(many=True)


def _save(request, template):
    body = TemplateIn(data=request.data)
    body.is_valid(raise_exception=True)
    v = body.validated_data
    values = recurring.Values(
        name=v["name"],
        narration=v["narration"],
        frequency=v["frequency"],
        day_of_month=v["day_of_month"],
        start_date=v["start_date"],
        end_date=v.get("end_date"),
        reverse_next_month=v["reverse_next_month"],
    )
    return recurring.save(request.user, template, values, _lines(v["lines"]))


class TemplateListView(_Recurring):
    def get(self, request):
        rows = recurring.visible(request.user).select_related("created_by")
        return Response([_detail(t) for t in rows])

    def post(self, request):
        try:
            made = _save(request, None)
        except AccountingError as error:
            return _error(error)
        return Response(_detail(made), status=status.HTTP_201_CREATED)


class TemplateDetailView(_Recurring):
    def get(self, request, pk):
        return Response(_detail(get_object_or_404(recurring.visible(request.user), pk=pk)))

    def put(self, request, pk):
        template = get_object_or_404(recurring.visible(request.user), pk=pk)
        try:
            saved = _save(request, template)
        except AccountingError as error:
            return _error(error)
        return Response(_detail(saved))


class TemplateActiveView(_Recurring):
    def post(self, request, pk):
        template = get_object_or_404(recurring.visible(request.user), pk=pk)
        try:
            saved = recurring.set_active(request.user, template, bool(request.data.get("active")))
        except AccountingError as error:
            return _error(error)
        return Response(_detail(saved))
