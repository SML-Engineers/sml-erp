"""Cash flow planner API (P2-25). The projection needs Financial reports: View; what-if
items are added and removed with Accounting: Enter (the service checks it too)."""

from datetime import date

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.access import sees_all_divisions
from apps.core.permissions import AreaAccess

from . import planner
from .models import CashPlanItem
from .services import AccountingError


def _m(value) -> str:
    return f"{value:.2f}"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _body(user, data: dict) -> dict:
    return {
        "today": data["today"],
        "end": data["end"],
        "opening": _m(data["opening"]),
        "closing": _m(data["closing"]),
        "lowest": {"amount": _m(data["lowest"]["amount"]), "day": data["lowest"]["day"]},
        "weeks": [
            {k: (_m(v) if not isinstance(v, date) else v) for k, v in w.items()}
            for w in data["weeks"]
        ],
        "days": [
            {k: (_m(v) if not isinstance(v, date) else v) for k, v in d.items()}
            for d in data["days"]
        ],
        "flows": [
            {
                "day": f.day,
                "amount": _m(f.amount),
                "kind": f.kind,
                "label": f.label,
                "link": f.link,
                "item_id": f.item_id,
            }
            for f in data["flows"]
        ],
        "what_ifs": [
            {
                "id": i.pk,
                "description": i.description,
                "on_date": i.on_date,
                "amount": _m(i.amount),
                "created_by": i.created_by.full_name,
            }
            for i in data["what_ifs"]
        ],
        "can_plan": planner.can_plan(user),
    }


def _without(request) -> set[int]:
    text = request.query_params.get("without") or ""
    return {int(x) for x in text.split(",") if x.strip().isdigit()}


class PlannerView(APIView):
    permission_classes = [AreaAccess]
    access_area = "financial_reports"

    def get(self, request):
        if not sees_all_divisions(request.user):
            return _error("The cash flow planner is for the whole company.")
        return Response(
            _body(request.user, planner.projection(request.user, without=_without(request)))
        )


class WhatIfView(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "enter"

    def post(self, request):
        try:
            on = date.fromisoformat(str(request.data.get("on_date", "")))
        except ValueError:
            return _error("Give the date, for example 2026-12-15.")
        try:
            planner.add_what_if(
                request.user,
                description=str(request.data.get("description", "")),
                on_date=on,
                amount=request.data.get("amount", ""),
                money_in=str(request.data.get("direction", "out")) == "in",
            )
        except AccountingError as error:
            return _error(error)
        return Response(
            _body(request.user, planner.projection(request.user)), status=status.HTTP_201_CREATED
        )


class WhatIfDetailView(WhatIfView):
    def delete(self, request, pk):
        try:
            planner.remove_what_if(request.user, get_object_or_404(CashPlanItem, pk=pk))
        except AccountingError as error:
            return _error(error)
        return Response(_body(request.user, planner.projection(request.user)))
