"""Report builder API (P2-26). Open to every signed-in person with the Dashboard; what each
data source shows is decided by report_builder.py from the person's own access and
divisions, as on the modules' pages."""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import document_email, exports
from apps.core.document_email import EmailError
from apps.core.exports import STRONG, Column
from apps.core.models import Role
from apps.core.permissions import AreaAccess

from . import report_builder as rb
from .models import SavedReport
from .report_builder import ReportError


class _Builder(APIView):
    permission_classes = [AreaAccess]
    access_area = "dashboard"
    access_write_level = "view"  # the service checks each data source's own area


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _saved(r: SavedReport, user) -> dict:
    return {
        "id": r.pk,
        "name": r.name,
        "definition": r.definition,
        "owner": r.owner.full_name,
        "mine": r.owner_id == user.pk,
        "shared_role": r.shared_role.code if r.shared_role_id else None,
        "shared_role_name": r.shared_role.name if r.shared_role_id else None,
        "updated_at": r.updated_at,
    }


class BuilderView(_Builder):
    def get(self, request):
        sources = rb.sources_for(request.user)
        keys = {s.key for s in sources}
        return Response(
            {
                "sources": [
                    {
                        "key": s.key,
                        "label": s.label,
                        "fields": [
                            {"key": f.key, "label": f.label, "kind": f.kind} for f in s.fields
                        ],
                    }
                    for s in sources
                ],
                "ops": rb.OPS,
                "presets": [p for p in rb.PRESETS if p["definition"]["source"] in keys],
                "saved": [_saved(r, request.user) for r in rb.saved_for(request.user)],
                "roles": [
                    {"code": r.code, "name": r.name}
                    for r in Role.objects.filter(is_active=True).order_by("name")
                ],
                "max_rows": rb.MAX_ROWS,
            }
        )


def _flat(result: dict) -> tuple[list[Column], list[dict]]:
    columns = [
        Column(
            c["key"], c["label"], c["kind"] if c["kind"] in ("money", "date", "number") else "text"
        )
        for c in result["columns"]
    ]
    rows = [r["cells"] | ({STRONG: True} if r["kind"] != "line" else {}) for r in result["rows"]]
    return columns, rows


class RunView(_Builder):
    """?d=<the definition as JSON>; &export=xlsx or pdf gives the file."""

    def get(self, request):
        try:
            d = rb.parse(request.user, request.query_params.get("d", ""))
            result = rb.run(request.user, d)
        except ReportError as error:
            return _error(error)
        fmt = (request.query_params.get("export") or "").lower()
        if fmt in exports.FORMATS:
            columns, rows = _flat(result)
            name = rb.title_of(d, request.query_params.get("name", "")[:100])
            return exports.response(
                fmt,
                title=name,
                subtitle=f"{d.source.label} · {result['count']} rows",
                columns=columns,
                rows=rows,
                filename="report",
                user=request.user,
                totals=False,
            )
        return Response(result)


class EmailView(_Builder):
    def get(self, request):
        name = request.query_params.get("name", "")[:100] or "Report"
        try:
            return Response(
                document_email.draft(request.user, "report", {"report_name": name, "period": ""})
            )
        except EmailError as error:
            return _error(error)

    def post(self, request):
        data = request.data
        try:
            d = rb.parse(request.user, data.get("definition"))
            result = rb.run(request.user, d)
        except ReportError as error:
            return _error(error)
        name = str(data.get("name") or "")[:100] or d.source.label
        columns, rows = _flat(result)
        content = exports.xlsx(name, d.source.label, columns, rows, False)
        try:
            record = document_email.send(
                request.user,
                kind="report",
                label=name,
                to=data.get("to") or [],
                cc=data.get("cc") or [],
                subject=str(data.get("subject", "")),
                body=str(data.get("body", "")),
                attachment=(f"{name}.xlsx", content, exports.XLSX),
            )
        except EmailError as error:
            return _error(error)
        if record.status != "sent":
            return Response(
                {"detail": f"The email could not be sent: {record.error}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"status": "sent"})


def _role(code):
    if not code:
        return None
    role = Role.objects.filter(code=str(code), is_active=True).first()
    if role is None:
        raise ReportError("Unknown role.")
    return role


class SavedListView(_Builder):
    def post(self, request):
        try:
            made = rb.save(
                request.user,
                name=str(request.data.get("name", "")),
                raw=request.data.get("definition"),
                shared_role=_role(request.data.get("shared_role")),
            )
        except ReportError as error:
            return _error(error)
        return Response(_saved(made, request.user), status=status.HTTP_201_CREATED)


class SavedDetailView(_Builder):
    def put(self, request, pk):
        found = get_object_or_404(rb.saved_for(request.user), pk=pk)
        try:
            saved = rb.save(
                request.user,
                name=str(request.data.get("name", "")),
                raw=request.data.get("definition"),
                shared_role=_role(request.data.get("shared_role")),
                report=found,
            )
        except ReportError as error:
            return _error(error)
        return Response(_saved(saved, request.user))

    def delete(self, request, pk):
        try:
            rb.delete(request.user, get_object_or_404(rb.saved_for(request.user), pk=pk))
        except ReportError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)
