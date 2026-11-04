"""Stock issues, returns, adjustments and counts API (P2-18). Rules live in issues.py and
adjustments.py; every endpoint needs Stores (or Accounting for adjustments) access."""

from datetime import date

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.permissions import AreaAccess
from apps.masters.models import Section

from . import adjustments, issues
from .models import (
    Item,
    StockAdjustment,
    StockCount,
    StockIssue,
    StockIssueLine,
    Store,
)
from .stock import StockError


class _Stores(APIView):
    permission_classes = [AreaAccess]
    access_area = "stores"
    access_also_area = "accounting"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _q(value) -> str:
    return f"{value:.3f}"


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _item(i: Item) -> dict:
    return {"id": i.pk, "code": i.code, "name": i.name, "unit": i.unit}


def _store(pk) -> Store | None:
    return Store.objects.select_related("division").filter(pk=pk or 0).first()


# --- Issues ------------------------------------------------------------------------------


def _issue(d: StockIssue) -> dict:
    return {
        "id": d.pk,
        "number": d.number,
        "kind": d.kind,
        "store": d.store.code,
        "division": d.division.code,
        "section": d.section.name if d.section_id else None,
        "issue_date": d.issue_date,
        "purpose": d.purpose,
        "returns": None
        if d.returns_id is None
        else {"id": d.returns_id, "number": d.returns.number},
        "total_value": f"{d.total_value:.2f}",
        "journal_entry": d.journal_entry.number if d.journal_entry_id else None,
        "created_by": d.created_by.full_name,
        "lines": [
            {
                "id": x.pk,
                "item": _item(x.item),
                "lot_no": x.lot_no,
                "quantity": _q(x.quantity),
                "unit_cost": f"{x.unit_cost:.4f}",
                "value": f"{x.value:.2f}",
                "returned": _q(issues.returned_already(x)) if d.kind == "issue" else None,
            }
            for x in d.lines.select_related("item")
        ],
    }


class IssueListView(_Stores):
    access_also_area = "accounting"

    def get(self, request):
        rows = issues.visible(request.user).select_related(
            "store", "division", "section", "returns", "journal_entry", "created_by"
        )
        return Response([_issue(d) for d in rows[:500]])

    def post(self, request):
        data = request.data
        section = Section.objects.filter(pk=data.get("section") or 0).first()
        lines = [
            issues.IssueLine(
                item=Item.objects.filter(pk=row.get("item") or 0).first(),
                quantity=row.get("quantity", ""),
                lot_no=str(row.get("lot_no") or ""),
            )
            for row in data.get("lines") or []
        ]
        try:
            made = issues.issue(
                request.user,
                store=_store(data.get("store")),
                issue_date=_day(data.get("issue_date")) or date.today(),
                section=section,
                purpose=str(data.get("purpose") or ""),
                lines=lines,
            )
        except StockError as error:
            return _error(error)
        return Response(_issue(made), status=status.HTTP_201_CREATED)


class IssueDetailView(_Stores):
    def get(self, request, pk):
        return Response(_issue(get_object_or_404(issues.visible(request.user), pk=pk)))


class IssueReturnView(_Stores):
    def post(self, request, pk):
        original = get_object_or_404(issues.visible(request.user), pk=pk)
        pairs = []
        for row in request.data.get("lines") or []:
            line = StockIssueLine.objects.filter(pk=row.get("line") or 0, issue=original).first()
            if line is None:
                return _error(StockError("A line is not on this issue."))
            pairs.append((line, row.get("quantity", "")))
        try:
            made = issues.give_back(
                request.user,
                original,
                return_date=_day(request.data.get("return_date")) or date.today(),
                lines=pairs,
            )
        except StockError as error:
            return _error(error)
        return Response(_issue(made), status=status.HTTP_201_CREATED)


class LotsView(_Stores):
    """The lots of an item in a store, oldest first, with the average cost."""

    def get(self, request):
        item = get_object_or_404(Item, pk=request.query_params.get("item") or 0)
        store = get_object_or_404(Store, pk=request.query_params.get("store") or 0)
        return Response(
            {
                "unit_cost": f"{issues.cost_of(item):.4f}",
                "lots": [{"lot_no": lot, "quantity": _q(q)} for lot, q in issues.lots(item, store)],
            }
        )


# --- Adjustments -------------------------------------------------------------------------


def _adjustment(a: StockAdjustment, user) -> dict:
    return {
        "id": a.pk,
        "number": a.number,
        "kind": a.kind,
        "status": a.status,
        "store": {"id": a.store_id, "code": a.store.code},
        "adjustment_date": a.adjustment_date,
        "reason": a.reason,
        "count": None if a.count_id is None else {"id": a.count_id, "number": a.count.number},
        "total_value": f"{a.total_value:.2f}",
        "journal_entry": a.journal_entry.number if a.journal_entry_id else None,
        "created_by": a.created_by.full_name,
        "can_edit": a.status == "draft" and a.created_by_id == user.pk and not a.count_id,
        "can_submit": a.status == "draft" and a.created_by_id == user.pk,
        "can_approve": adjustments.can_approve(user, a),
        "lines": [
            {
                "item": _item(x.item),
                "lot_no": x.lot_no,
                "quantity": _q(x.quantity),
                "unit_cost": None if x.unit_cost is None else f"{x.unit_cost:.4f}",
                "value": f"{x.value:.2f}",
                "notes": x.notes,
            }
            for x in a.lines.select_related("item")
        ],
        "approvals": [
            {"action": r.action, "user": r.user.full_name, "reason": r.reason, "at": r.acted_at}
            for r in approvals.history(adjustments.DOC, a.pk)
        ],
    }


def _adjustment_lines(rows) -> list:
    return [
        adjustments.LineInput(
            item=Item.objects.filter(pk=row.get("item") or 0).first(),
            quantity=row.get("quantity", ""),
            lot_no=str(row.get("lot_no") or ""),
            unit_cost=row.get("unit_cost"),
            notes=str(row.get("notes") or ""),
        )
        for row in rows or []
    ]


class AdjustmentListView(_Stores):
    def get(self, request):
        rows = adjustments.visible(request.user).select_related(
            "store", "count", "journal_entry", "created_by"
        )
        if request.query_params.get("status"):
            rows = rows.filter(status__in=request.query_params["status"].split(","))
        return Response([_adjustment(a, request.user) for a in rows[:500]])

    def post(self, request):
        try:
            made = adjustments.create(
                request.user,
                store=_store(request.data.get("store")),
                kind=str(request.data.get("kind") or ""),
                reason=str(request.data.get("reason") or ""),
                lines=_adjustment_lines(request.data.get("lines")),
            )
        except StockError as error:
            return _error(error)
        return Response(_adjustment(made, request.user), status=status.HTTP_201_CREATED)


def _get_adjustment(user, pk) -> StockAdjustment:
    return get_object_or_404(adjustments.visible(user), pk=pk)


class AdjustmentDetailView(_Stores):
    def get(self, request, pk):
        return Response(_adjustment(_get_adjustment(request.user, pk), request.user))

    def patch(self, request, pk):
        try:
            saved = adjustments.save(
                request.user,
                _get_adjustment(request.user, pk),
                reason=str(request.data.get("reason") or ""),
                lines=_adjustment_lines(request.data.get("lines")),
            )
        except StockError as error:
            return _error(error)
        return Response(_adjustment(saved, request.user))


class AdjustmentActionView(_Stores):
    action = "submit"

    def get_permissions(self):
        # The Director decides; the service checks they are the one waited for.
        if self.action in ("approve", "return", "reject"):
            self.access_write_level = "view"
        return super().get_permissions()

    def post(self, request, pk):
        found = _get_adjustment(request.user, pk)
        comment = str(request.data.get("comment") or "")
        reason = str(request.data.get("reason") or "")
        try:
            if self.action == "submit":
                adjustments.submit(request.user, found, comment)
            elif self.action == "approve":
                adjustments.approve(request.user, found, comment)
            elif self.action == "return":
                adjustments.send_back(request.user, found, reason)
            else:
                adjustments.reject(request.user, found, reason)
        except StockError as error:
            return _error(error)
        return Response(_adjustment(_get_adjustment(request.user, pk), request.user))


# --- Counts ------------------------------------------------------------------------------


def _count(c: StockCount, user) -> dict:
    adjustment = getattr(c, "adjustment", None)
    return {
        "id": c.pk,
        "number": c.number,
        "store": {"id": c.store_id, "code": c.store.code},
        "count_date": c.count_date,
        "status": c.status,
        "notes": c.notes,
        "created_by": c.created_by.full_name,
        "adjustment": None
        if adjustment is None
        else {"id": adjustment.pk, "number": adjustment.number, "status": adjustment.status},
        "lines": [
            {
                "item": _item(x.item),
                "lot_no": x.lot_no,
                "system_quantity": _q(x.system_quantity),
                "counted_quantity": None if x.counted_quantity is None else _q(x.counted_quantity),
            }
            for x in c.lines.select_related("item")
        ],
    }


def _counts(user):
    return StockCount.objects.filter(
        store__division__in=adjustments.division_scope(user)
    ).select_related("store", "created_by")


class CountListView(_Stores):
    def get(self, request):
        return Response([_count(c, request.user) for c in _counts(request.user)[:200]])

    def post(self, request):
        try:
            made = adjustments.start_count(
                request.user,
                store=_store(request.data.get("store")),
                count_date=_day(request.data.get("count_date")),
                notes=str(request.data.get("notes") or ""),
            )
        except StockError as error:
            return _error(error)
        return Response(_count(made, request.user), status=status.HTTP_201_CREATED)


class CountDetailView(_Stores):
    def get(self, request, pk):
        return Response(_count(get_object_or_404(_counts(request.user), pk=pk), request.user))


class CountActionView(_Stores):
    action = "enter"

    def post(self, request, pk):
        count = get_object_or_404(_counts(request.user), pk=pk)
        try:
            if self.action == "enter":
                rows = [
                    (
                        Item.objects.filter(pk=row.get("item") or 0).first(),
                        str(row.get("lot_no") or ""),
                        row.get("counted_quantity"),
                    )
                    for row in request.data.get("lines") or []
                ]
                adjustments.enter_counts(request.user, count, rows)
            elif self.action == "submit":
                adjustments.submit_count(
                    request.user, count, str(request.data.get("comment") or "")
                )
            else:
                adjustments.cancel_count(request.user, count)
        except StockError as error:
            return _error(error)
        return Response(_count(get_object_or_404(_counts(request.user), pk=pk), request.user))
