"""Bank statement import (backlog P2-15, spec 7A).

The Accountant chooses the bank account and its bank's template and uploads the file (Excel,
CSV or a PDF with text). The file is read and checked before anything is saved: every balance
must follow from the one before, so a misread file is refused. Lines already imported from
an earlier, overlapping statement are skipped. The same file is never imported twice. A wrong
import is deleted whole and imported again (until it is reconciled, P2-16).
"""

import hashlib
from decimal import Decimal

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.masters.models import CompanyAccount

from . import parsing
from .models import BankStatement, BankStatementLine, StatementTemplate
from .services import BankingError

BANK_KINDS = (CompanyAccount.Kind.CURRENT, CompanyAccount.Kind.SAVINGS)
TEMPLATE_FIELDS = (
    "bank_name",
    "file_kind",
    "date_format",
    "date_column",
    "description_column",
    "reference_column",
    "out_column",
    "in_column",
    "amount_column",
    "negative_is_out",
    "balance_column",
    "checked",
    "notes",
    "is_active",
)


def can_import(user: User) -> bool:
    return effective_access(user).has("banking", "enter")


def can_view(user: User) -> bool:
    return effective_access(user).has("banking", "view")


def _accountant(user: User) -> None:
    if not can_import(user):
        raise BankingError("Only the Accountant imports bank statements and keeps templates.")


# --- Templates ---------------------------------------------------------------------------


def save_template(user: User, template: StatementTemplate | None, values: dict):
    _accountant(user)
    with audit_context("statement_template_saved"), transaction.atomic():
        if template is None:
            code = str(values.get("code") or "").strip().upper()[:20]
            if not code:
                raise BankingError("Give the template a code, such as SAMPATH-XLSX.")
            if StatementTemplate.objects.filter(code=code).exists():
                raise BankingError(f"There is already a template {code}.")
            template = StatementTemplate(code=code)
        for name in TEMPLATE_FIELDS:
            if name in values:
                value = values[name]
                setattr(template, name, value.strip() if isinstance(value, str) else value)
        if not template.bank_name:
            raise BankingError("Give the bank's name.")
        if template.file_kind not in StatementTemplate.Kind.values:
            raise BankingError("Choose the kind of file: Excel, CSV or PDF.")
        if template.file_kind != StatementTemplate.Kind.PDF:
            if not template.date_column or not template.description_column:
                raise BankingError("Give the headings of the date and description columns.")
            if not template.amount_column and not (template.out_column and template.in_column):
                raise BankingError(
                    "Give the headings of the money out and money in columns, or of the one "
                    "amount column."
                )
        try:
            timezone.now().strftime(template.date_format)
        except ValueError:
            raise BankingError("The date format is not valid (for example %d/%m/%Y).") from None
        template.updated_by, template.updated_at = user, timezone.now()
        template.save()
        return template


def layout(template: StatementTemplate) -> parsing.Layout:
    return parsing.Layout(
        file_kind=template.file_kind,
        date_format=template.date_format,
        date_column=template.date_column,
        description_column=template.description_column,
        reference_column=template.reference_column,
        out_column=template.out_column,
        in_column=template.in_column,
        amount_column=template.amount_column,
        negative_is_out=template.negative_is_out,
        balance_column=template.balance_column,
    )


# --- Importing ---------------------------------------------------------------------------


def _key(account_id: int, line) -> tuple:
    return (
        account_id,
        line.date,
        line.money_out,
        line.money_in,
        line.balance,
        " ".join((line.description or "").split()).upper(),
    )


def _check_account(account) -> CompanyAccount:
    if not isinstance(account, CompanyAccount) or account.kind not in BANK_KINDS:
        raise BankingError("Choose one of the company's bank accounts.")
    return account


def last_closing(account: CompanyAccount) -> Decimal | None:
    latest = BankStatement.objects.filter(account=account).exclude(closing_balance=None).first()
    return latest.closing_balance if latest else None


def read(user: User, *, account, template: StatementTemplate, content: bytes, opening=None) -> dict:
    """Read and check the file; nothing is saved. Returns the lines, which of them were
    already imported, and any problems."""
    _accountant(user)
    account = _check_account(account)
    if not isinstance(template, StatementTemplate) or not template.is_active:
        raise BankingError("Choose an active template.")
    if opening not in (None, ""):
        try:
            opening = parsing.money(opening)
        except parsing.StatementFileError as error:
            raise BankingError(str(error)) from None
    else:
        opening = None
    try:
        parsed = parsing.read(content, layout(template), opening)
    except parsing.StatementFileError as error:
        raise BankingError(str(error)) from None
    if parsed.problems and parsed.opening is None and opening is None:
        # Try again from where the last statement of the account ended.
        before = last_closing(account)
        if before is not None:
            parsed = parsing.read(content, layout(template), before)
            opening = before
    lines = [line for line in parsed.lines if line.money_in or line.money_out]
    seen = {
        _key(account.pk, row)
        for row in BankStatementLine.objects.filter(
            account=account,
            date__gte=min((x.date for x in lines), default=timezone.localdate()),
            date__lte=max((x.date for x in lines), default=timezone.localdate()),
        )
    }
    return {
        "opening": parsed.opening if parsed.opening is not None else opening,
        "lines": lines,
        "already": [_key(account.pk, line) in seen for line in lines],
        "problems": parsed.problems,
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def import_file(
    user: User,
    *,
    account,
    template: StatementTemplate,
    content: bytes,
    file_name: str,
    opening=None,
) -> BankStatement:
    found = read(user, account=account, template=template, content=content, opening=opening)
    if found["problems"]:
        raise BankingError(" ".join(found["problems"][:5]))
    new = [line for line, old in zip(found["lines"], found["already"], strict=True) if not old]
    if not new:
        raise BankingError("Every line of this file has been imported already.")
    with audit_context("bank_statement_imported"), transaction.atomic():
        if BankStatement.objects.filter(account=account, sha256=found["sha256"]).exists():
            raise BankingError("This file has been imported for this account already.")
        lines = found["lines"]
        statement = BankStatement.objects.create(
            account=account,
            template=template,
            file_name=(file_name or "statement")[:200],
            sha256=found["sha256"],
            from_date=min(x.date for x in lines),
            to_date=max(x.date for x in lines),
            opening_balance=found["opening"],
            closing_balance=next(
                (x.balance for x in reversed(lines) if x.balance is not None), None
            ),
            skipped=len(lines) - len(new),
            imported_by=user,
        )
        BankStatementLine.objects.bulk_create(
            BankStatementLine(
                statement=statement,
                account=account,
                line_no=n,
                date=line.date,
                description=line.description[:500],
                reference=line.reference[:60],
                money_out=line.money_out,
                money_in=line.money_in,
                balance=line.balance,
            )
            for n, line in enumerate(new, start=1)
        )
        return statement


def statements(user: User) -> QuerySet[BankStatement]:
    if not can_view(user):
        return BankStatement.objects.none()
    return BankStatement.objects.select_related("account", "template", "imported_by")


def delete(user: User, statement: BankStatement) -> None:
    _accountant(user)
    with audit_context("bank_statement_deleted"):
        statement.delete()
