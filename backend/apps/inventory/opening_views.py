"""Opening stock API (P16-15). Rules live in opening.py.

Reading needs Stores: View (the Accountant, the Director, the stores person and the Auditor
have it). Loading and sending need Accounting: Enter, which the service checks; approving is
checked by the approval engine (the approving role, not the person who loaded it)."""

from datetime import date

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.permissions import AreaAccess
from apps.masters import excel

from . import opening
from .models import OpeningStock
from .opening import OpeningError

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class _Opening(APIView):
    permission_classes = [AreaAccess]
    access_area = "stores"
    access_write_level = "view"  # the service checks Accounting: Enter; the engine, approvers


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _refused(refused: excel.ImportRefused):
    return Response(
        {"detail": "Nothing was loaded.", "errors": refused.errors},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _get(user, pk) -> OpeningStock:
    return get_object_or_404(opening.visible(user), pk=pk)


def _summary(o: OpeningStock) -> dict:
    return {
        "id": o.pk,
        "number": o.number,
        "count_date": o.count_date,
        "status": o.status,
        "notes": o.notes,
        "lines": o.lines.count(),
        "value": f"{opening.total(o):.2f}",
        "created_by": o.created_by.full_name,
        "journal_entry": None
        if o.journal_entry_id is None
        else {"id": o.journal_entry_id, "number": o.journal_entry.number},
    }


def _detail(o: OpeningStock, user) -> dict:
    state = approvals.state_of(opening.DOC, o.pk)
    return _summary(o) | {
        "rows": [
            {
                "line_no": x.line_no,
                "item": {"id": x.item_id, "code": x.item.code, "name": x.item.name},
                "unit": x.item.unit,
                "store": x.store.code,
                "division": x.store.division.code,
                "lot_no": x.lot_no,
                "quantity": str(x.quantity),
                "unit_cost": str(x.unit_cost),
                "value": str(x.value),
            }
            for x in o.lines.select_related("item", "store__division")
        ],
        "can_edit": opening.can_edit(user, o),
        "can_approve": opening.can_approve(user, o),
        "approval": None
        if state is None
        else {
            "status": state.status,
            "history": [
                {
                    "action": row.action,
                    "action_label": row.get_action_display(),
                    "by": row.user.full_name,
                    "at": row.acted_at,
                    "reason": row.reason,
                }
                for row in approvals.history(opening.DOC, o.pk)
            ],
        },
    }


def _fresh(o: OpeningStock, user) -> dict:
    return _detail(
        OpeningStock.objects.select_related("created_by", "journal_entry").get(pk=o.pk), user
    )


def _upload(request):
    uploaded = request.FILES.get("file")
    if uploaded is None:
        raise excel.ImportRefused(["Choose the Excel file with the counted stock."])
    if uploaded.size > excel.MAX_BYTES:
        raise excel.ImportRefused(["The file must be 5 MB or smaller."])
    raw = str(request.data.get("count_date", ""))
    try:
        count_date = date.fromisoformat(raw)
    except ValueError:
        raise excel.ImportRefused(["Give the date the stores were counted."]) from None
    return {
        "content": uploaded.read(),
        "count_date": count_date,
        "notes": str(request.data.get("notes", "")),
        "dry_run": str(request.data.get("dry_run", "")).lower() in ("1", "true", "yes"),
    }


class OpeningListView(_Opening):
    parser_classes = [MultiPartParser]

    def get(self, request):
        rows = opening.visible(request.user).select_related("created_by", "journal_entry")
        if request.query_params.get("waiting") == "me":
            waiting = approvals.waiting_for(request.user, opening.DOC)
            rows = rows.filter(pk__in=[s.document_id for s in waiting])
        return Response([_summary(o) for o in rows[:500]])

    def post(self, request):
        """Load a new draft from the Excel sheet; with dry_run, only check it."""
        try:
            made, summary = opening.load(request.user, None, **_upload(request))
        except excel.ImportRefused as refused:
            return _refused(refused)
        if made is None:
            return Response({"dry_run": True, **summary})
        return Response(_fresh(made, request.user), status=status.HTTP_201_CREATED)


class OpeningTemplateView(_Opening):
    def get(self, request):
        reply = HttpResponse(opening.template(), content_type=XLSX)
        reply["Content-Disposition"] = 'attachment; filename="opening-stock.xlsx"'
        return reply


class OpeningDetailView(_Opening):
    parser_classes = [MultiPartParser]

    def get(self, request, pk):
        return Response(_fresh(_get(request.user, pk), request.user))

    def put(self, request, pk):
        """Load the sheet again into the draft, replacing its lines."""
        current = _get(request.user, pk)
        try:
            made, summary = opening.load(request.user, current, **_upload(request))
        except excel.ImportRefused as refused:
            return _refused(refused)
        if made is None:
            return Response({"dry_run": True, **summary})
        return Response(_fresh(made, request.user))

    def delete(self, request, pk):
        try:
            opening.delete(request.user, _get(request.user, pk))
        except OpeningError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class _Action(_Opening):
    def _run(self, request, pk, action):
        current = _get(request.user, pk)
        try:
            current = action(current)
        except OpeningError as error:
            return _error(error)
        return Response(_fresh(current, request.user))


def _text(request, name: str) -> str:
    return str(request.data.get(name, ""))


class SubmitView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda o: opening.submit(request.user, o, _text(request, "comment"))
        )


class ApproveView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda o: opening.approve(request.user, o, _text(request, "comment"))
        )


class ReturnView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda o: opening.send_back(request.user, o, _text(request, "reason"))
        )


class RejectView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda o: opening.reject(request.user, o, _text(request, "reason"))
        )
