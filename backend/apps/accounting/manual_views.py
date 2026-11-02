"""Manual journals API (P2-01). Rules live in manual.py.

Reading needs Accounting: View; entering needs Accounting: Enter. Approving is open to anyone
who can see journals, because the approval engine itself checks that the person holds the
approving role, did not make the journal and has not approved it at another level."""

from django.db.models import Sum
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import approvals, exports
from apps.core.exports import Column
from apps.core.models import Division
from apps.core.permissions import AreaAccess
from apps.masters.models import Supplier

from . import manual
from .models import Account, ManualJournal, ManualJournalAttachment
from .services import AccountingError


class _Journals(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _get(user, pk) -> ManualJournal:
    return get_object_or_404(manual.visible(user), pk=pk)


def _summary(mj: ManualJournal) -> dict:
    if hasattr(mj, "sum_debit"):
        debits, credits = mj.sum_debit or 0, mj.sum_credit or 0
    else:
        debits, credits = manual.totals(mj)
    return {
        "id": mj.pk,
        "number": mj.number,
        "entry_date": mj.entry_date,
        "narration": mj.narration,
        "status": mj.status,
        "status_label": mj.get_status_display(),
        "total_debit": f"{debits:.2f}",
        "total_credit": f"{credits:.2f}",
        "created_by": mj.created_by.full_name,
        "journal_entry": None
        if mj.journal_entry_id is None
        else {"id": mj.journal_entry_id, "number": mj.journal_entry.number},
        "reverse_on": mj.reverse_on,
        "recurring": None
        if mj.recurring_id is None
        else {"id": mj.recurring_id, "name": mj.recurring.name},
    }


def _detail(mj: ManualJournal, user) -> dict:
    state = approvals.state_of(manual.DOC, mj.pk)
    return _summary(mj) | {
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
            for x in mj.lines.select_related("account", "division", "supplier")
        ],
        "attachments": [
            {
                "id": a.pk,
                "file_name": a.file_name,
                "content_type": a.content_type,
                "size": a.size,
                "uploaded_by": a.uploaded_by.full_name,
                "uploaded_at": a.uploaded_at,
            }
            for a in mj.attachments.select_related("uploaded_by").order_by("pk")
        ],
        "can_edit": manual.can_edit(user, mj),
        "can_approve": manual.can_approve(user, mj),
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
                for row in approvals.history(manual.DOC, mj.pk)
            ],
        },
    }


def _fresh(mj: ManualJournal, user) -> dict:
    return _detail(_rows().get(pk=mj.pk), user)


def _rows():
    rows = ManualJournal.objects.select_related("created_by", "journal_entry", "recurring")
    return rows.annotate(sum_debit=Sum("lines__debit"), sum_credit=Sum("lines__credit"))


class LineIn(serializers.Serializer):
    account = serializers.IntegerField()
    debit = serializers.CharField(max_length=30, required=False, allow_blank=True)
    credit = serializers.CharField(max_length=30, required=False, allow_blank=True)
    division = serializers.CharField(
        max_length=10, required=False, allow_blank=True, allow_null=True
    )
    supplier = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True)


class JournalIn(serializers.Serializer):
    entry_date = serializers.DateField()
    narration = serializers.CharField(max_length=500, allow_blank=True)
    reverse_next_month = serializers.BooleanField(required=False)
    lines = LineIn(many=True)


def _lines(rows) -> list[manual.LineInput]:
    result = []
    for n, row in enumerate(rows, start=1):
        code = (row.get("division") or "").strip().upper()
        division = None
        if code:
            division = Division.objects.filter(code=code).first()
            if division is None:
                raise AccountingError(f"Line {n}: there is no division {code}.")
        supplier = None
        if row.get("supplier"):
            supplier = Supplier.objects.filter(pk=row["supplier"]).first()
            if supplier is None:
                raise AccountingError(f"Line {n}: choose the supplier again.")
        result.append(
            manual.LineInput(
                account=Account.objects.select_related("merged_into")
                .filter(pk=row["account"])
                .first(),
                debit=row.get("debit") or "0",
                credit=row.get("credit") or "0",
                division=division,
                supplier=supplier,
                description=row.get("description", ""),
            )
        )
    return result


def _values(data: dict) -> dict:
    return {k: v for k, v in data.items() if k != "lines"}


COLUMNS = [
    Column("number", "Journal", width=1.2),
    Column("entry_date", "Date", "date"),
    Column("narration", "Narration", width=3),
    Column("status_label", "Status", width=1.4),
    Column("total_debit", "Amount (LKR)", "money"),
    Column("created_by", "Entered by", width=1.3),
    Column("entry", "Posted as", width=1.2),
]


class JournalListView(_Journals):
    """Manual journals, newest first. Filters: status, waiting=me; ?export=xlsx or pdf."""

    def get(self, request):
        rows = _rows().filter(pk__in=manual.visible(request.user).values("pk"))
        params = request.query_params
        if params.get("status"):
            rows = rows.filter(status__in=params["status"].split(","))
        if params.get("waiting") == "me":
            waiting = approvals.waiting_for(request.user, manual.DOC)
            rows = rows.filter(pk__in=[s.document_id for s in waiting])
        found = [_summary(mj) for mj in rows[:2000]]
        fmt = (params.get("export") or "").lower()
        if fmt in exports.FORMATS:
            for row in found:
                row["entry"] = row["journal_entry"]["number"] if row["journal_entry"] else ""
            return exports.response(
                fmt,
                title="Manual journals",
                subtitle=f"As at {timezone.localtime():%d/%m/%Y %H:%M}",
                columns=COLUMNS,
                rows=found,
                filename="manual-journals",
                user=request.user,
            )
        return Response(found)

    def post(self, request):
        body = JournalIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            mj = manual.create(
                request.user,
                lines=_lines(body.validated_data["lines"]),
                **_values(body.validated_data),
            )
        except AccountingError as error:
            return _error(error)
        return Response(_fresh(mj, request.user), status=status.HTTP_201_CREATED)


class JournalDetailView(_Journals):
    def get(self, request, pk):
        return Response(_fresh(_get(request.user, pk), request.user))

    def put(self, request, pk):
        mj = _get(request.user, pk)
        body = JournalIn(data=request.data)
        body.is_valid(raise_exception=True)
        try:
            mj = manual.save(
                request.user,
                mj,
                lines=_lines(body.validated_data["lines"]),
                **_values(body.validated_data),
            )
        except AccountingError as error:
            return _error(error)
        return Response(_fresh(mj, request.user))

    def delete(self, request, pk):
        mj = _get(request.user, pk)
        try:
            manual.delete(request.user, mj)
        except AccountingError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)


class _Action(_Journals):
    def _run(self, request, pk, action):
        mj = _get(request.user, pk)
        try:
            mj = action(mj)
        except AccountingError as error:
            return _error(error)
        return Response(_fresh(mj, request.user))


def _text(request, name: str) -> str:
    return str(request.data.get(name, ""))


class SubmitView(_Action):
    def post(self, request, pk):
        return self._run(
            request, pk, lambda mj: manual.submit(request.user, mj, _text(request, "comment"))
        )


class ApproveView(_Action):
    access_write_level = "view"  # the approval engine checks the approving role

    def post(self, request, pk):
        return self._run(
            request, pk, lambda mj: manual.approve(request.user, mj, _text(request, "comment"))
        )


class ReturnView(_Action):
    access_write_level = "view"

    def post(self, request, pk):
        return self._run(
            request, pk, lambda mj: manual.send_back(request.user, mj, _text(request, "reason"))
        )


class RejectView(_Action):
    access_write_level = "view"

    def post(self, request, pk):
        return self._run(
            request, pk, lambda mj: manual.reject(request.user, mj, _text(request, "reason"))
        )


class AttachmentListView(_Journals):
    parser_classes = [MultiPartParser]

    def post(self, request, pk):
        mj = _get(request.user, pk)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            return _error("Choose a file to attach.")
        try:
            manual.add_attachment(request.user, mj, uploaded)
        except AccountingError as error:
            return _error(error)
        return Response(_fresh(mj, request.user), status=status.HTTP_201_CREATED)


class AttachmentDetailView(_Journals):
    def get(self, request, pk, attachment_pk):
        mj = _get(request.user, pk)
        attachment = get_object_or_404(ManualJournalAttachment, pk=attachment_pk, journal=mj)
        return FileResponse(
            attachment.file.open("rb"),
            content_type=attachment.content_type,
            filename=attachment.file_name,
            as_attachment=request.query_params.get("download") in ("1", "true"),
        )

    def delete(self, request, pk, attachment_pk):
        mj = _get(request.user, pk)
        attachment = get_object_or_404(ManualJournalAttachment, pk=attachment_pk, journal=mj)
        try:
            manual.remove_attachment(request.user, attachment)
        except AccountingError as error:
            return _error(error)
        return Response(_fresh(mj, request.user))
