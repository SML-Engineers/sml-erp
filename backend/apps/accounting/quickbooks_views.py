"""Opening balances from QuickBooks API (P2-28). Rules live in quickbooks.py."""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals
from apps.core.permissions import AreaAccess

from . import quickbooks as qb
from .models import OpeningBalance
from .quickbooks import MigrationError

FILES = ("trial_balance", "receivables", "payables", "items")


class _Migration(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _doc(d: OpeningBalance, user) -> dict:
    state = approvals.state_of(qb.DOC, d.pk)
    lines = list(d.lines.select_related("account", "customer", "supplier"))
    return {
        "id": d.pk,
        "as_at": d.as_at,
        "status": d.status,
        "report": d.report,
        "created_by": d.created_by.full_name,
        "journal_entry": d.journal_entry.number if d.journal_entry_id else None,
        "total_debit": f"{sum((x.debit for x in lines), qb.ZERO):.2f}",
        "total_credit": f"{sum((x.credit for x in lines), qb.ZERO):.2f}",
        "lines": [
            {
                "account": f"{x.account.number} {x.account.name}".strip(),
                "party": (x.customer or x.supplier).name if (x.customer or x.supplier) else "",
                "description": x.description,
                "debit": f"{x.debit:.2f}",
                "credit": f"{x.credit:.2f}",
            }
            for x in lines
        ],
        "can_send": d.status == qb.St.DRAFT and d.created_by_id == user.pk,
        "can_approve": qb.can_approve(user, d),
        "history": []
        if state is None
        else [
            {
                "action": h.get_action_display(),
                "by": h.user.full_name,
                "at": h.acted_at,
                "reason": h.reason,
            }
            for h in approvals.history(qb.DOC, d.pk)
        ],
    }


class MigrationView(_Migration):
    parser_classes = [MultiPartParser]

    def get(self, request):
        from django.db.models import Count, Sum

        from apps.purchasing.models import SupplierInvoice
        from apps.sales.models import TaxInvoice

        docs = OpeningBalance.objects.select_related("created_by", "journal_entry")[:10]

        def loaded(model):
            got = model.objects.filter(opening=True).aggregate(n=Count("id"), t=Sum("total_lkr"))
            return {"count": got["n"], "total": f"{got['t'] or 0:.2f}"}

        return Response(
            {
                "can_enter": qb.can_enter(request.user),
                "documents": [_doc(d, request.user) for d in docs],
                "posted": OpeningBalance.objects.filter(status=qb.St.POSTED).exists(),
                "open_invoices": loaded(TaxInvoice),
                "open_bills": loaded(SupplierInvoice),
            }
        )

    def post(self, request):
        """Check the uploaded files; with make=yes, also make the draft when all is in order."""
        files = {k: request.FILES[k].read() for k in FILES if k in request.FILES}
        if "trial_balance" not in files:
            return _error("Choose QuickBooks' trial balance (Excel).")
        try:
            found = qb.check(**files)
            made = None
            if str(request.data.get("make", "")).lower() in ("1", "yes", "true"):
                made = qb.make(request.user, **files)
        except MigrationError as error:
            return _error(error)
        return Response(
            {"report": found["report"], "document": _doc(made, request.user) if made else None}
        )


class MigrationActionView(_Migration):
    action = "submit"

    def get_permissions(self):
        if self.action in ("approve", "return", "reject"):
            self.access_write_level = "view"  # the approval engine checks the Director
        return super().get_permissions()

    def post(self, request, pk):
        doc = get_object_or_404(OpeningBalance, pk=pk)
        text = str(request.data.get("comment") or request.data.get("reason") or "")
        act = {
            "submit": qb.submit,
            "approve": qb.approve,
            "return": qb.send_back,
            "reject": qb.reject,
        }.get(self.action)
        if act is None:
            return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)
        try:
            done = act(request.user, doc, text)
        except MigrationError as error:
            return _error(error)
        return Response(_doc(OpeningBalance.objects.get(pk=done.pk), request.user))

    def delete(self, request, pk):
        try:
            qb.delete(request.user, get_object_or_404(OpeningBalance, pk=pk))
        except MigrationError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class OpenItemsView(_Migration):
    """Part 2: check (and with load=yes, bring over) the open invoices and bills, line by line."""

    parser_classes = [MultiPartParser]

    def post(self, request):
        from apps.core.models import Division

        division_code = str(request.data.get("division") or "HO")
        default = Division.objects.filter(code=division_code.upper(), is_active=True).first()
        load = str(request.data.get("load", "")).lower() in ("1", "yes", "true")
        out = {}
        try:
            for kind in ("receivables", "payables"):
                if kind not in request.FILES:
                    continue
                content = request.FILES[kind].read()
                if load:
                    out[kind] = qb.load_open_items(request.user, kind, content, division_code)
                    out[kind]["loaded"] = True
                else:
                    out[kind] = qb.plan_open_items(kind, content, default)["report"]
        except MigrationError as error:
            return _error(error)
        if not out:
            return _error("Choose the A/R aging, the A/P aging, or both.")
        return Response(out)


class ParallelRunView(APIView):
    """The ERP against QuickBooks for the same date (P2-29): a comparison only."""

    permission_classes = [AreaAccess]
    access_area = "financial_reports"
    access_write_level = "view"  # posts nothing: the files are read and compared
    parser_classes = [MultiPartParser]

    def post(self, request):
        from . import parallel

        if "trial_balance" not in request.FILES:
            return _error("Choose QuickBooks' trial balance (Excel).")
        files = {
            k: request.FILES[k].read()
            for k in ("trial_balance", "receivables", "payables")
            if k in request.FILES
        }
        try:
            return Response(parallel.compare(**files))
        except MigrationError as error:
            return _error(error)
