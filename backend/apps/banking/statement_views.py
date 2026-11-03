"""Bank statement import API (P2-15). Rules live in statements.py."""

from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import AreaAccess
from apps.masters.models import CompanyAccount

from . import statements
from .models import BankStatement, StatementTemplate
from .services import BankingError


class _Statements(APIView):
    permission_classes = [AreaAccess]
    access_area = "banking"
    access_write_level = "enter"


def _error(error):
    return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def _template(t: StatementTemplate) -> dict:
    return {"id": t.pk, "code": t.code} | {
        name: getattr(t, name) for name in statements.TEMPLATE_FIELDS
    }


def _money(value) -> str | None:
    return None if value is None else f"{value:.2f}"


def _line(line, already: bool | None = None) -> dict:
    row = {
        "date": line.date,
        "description": line.description,
        "reference": line.reference,
        "money_out": _money(line.money_out),
        "money_in": _money(line.money_in),
        "balance": _money(line.balance),
    }
    if already is not None:
        row["already"] = already
    if hasattr(line, "line_no"):
        row["line_no"] = line.line_no
    return row


def _statement(s: BankStatement, lines: bool = False) -> dict:
    body = {
        "id": s.pk,
        "account": {"id": s.account_id, "code": s.account.code, "name": s.account.name},
        "template": s.template.code,
        "file_name": s.file_name,
        "from_date": s.from_date,
        "to_date": s.to_date,
        "opening_balance": _money(s.opening_balance),
        "closing_balance": _money(s.closing_balance),
        "skipped": s.skipped,
        "line_count": s.lines.count(),
        "imported_by": s.imported_by.full_name,
        "imported_at": s.imported_at,
    }
    if lines:
        body["lines"] = [_line(x) for x in s.lines.all()]
    return body


class TemplateListView(_Statements):
    def get(self, request):
        return Response([_template(t) for t in StatementTemplate.objects.all()])

    def post(self, request):
        try:
            made = statements.save_template(request.user, None, dict(request.data))
        except BankingError as error:
            return _error(error)
        return Response(_template(made), status=status.HTTP_201_CREATED)


class TemplateDetailView(_Statements):
    def patch(self, request, pk):
        template = get_object_or_404(StatementTemplate, pk=pk)
        try:
            saved = statements.save_template(request.user, template, dict(request.data))
        except BankingError as error:
            return _error(error)
        return Response(_template(saved))


class StatementListView(_Statements):
    def get(self, request):
        rows = statements.statements(request.user)
        if request.query_params.get("account"):
            rows = rows.filter(account_id=request.query_params["account"])
        return Response([_statement(s) for s in rows[:500]])


class ImportView(_Statements):
    """multipart: account, template, file, opening (optional), preview=1 to only read it."""

    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            return _error("Choose the statement file.")
        account = CompanyAccount.objects.filter(pk=request.data.get("account") or 0).first()
        template = StatementTemplate.objects.filter(pk=request.data.get("template") or 0).first()
        content = upload.read()
        opening = request.data.get("opening") or None
        try:
            if request.data.get("preview") in ("1", "true", True):
                found = statements.read(
                    request.user,
                    account=account,
                    template=template,
                    content=content,
                    opening=opening,
                )
                return Response(
                    {
                        "opening": _money(found["opening"]),
                        "lines": [
                            _line(x, old)
                            for x, old in zip(found["lines"], found["already"], strict=True)
                        ],
                        "problems": found["problems"],
                    }
                )
            made = statements.import_file(
                request.user,
                account=account,
                template=template,
                content=content,
                file_name=upload.name,
                opening=opening,
            )
        except BankingError as error:
            return _error(error)
        return Response(_statement(made, lines=True), status=status.HTTP_201_CREATED)


class StatementDetailView(_Statements):
    def get(self, request, pk):
        found = get_object_or_404(statements.statements(request.user), pk=pk)
        return Response(_statement(found, lines=True))

    def delete(self, request, pk):
        found = get_object_or_404(statements.statements(request.user), pk=pk)
        try:
            statements.delete(request.user, found)
        except BankingError as error:
            return _error(error)
        return Response(status=status.HTTP_204_NO_CONTENT)
