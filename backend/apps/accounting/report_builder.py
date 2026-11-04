"""Custom report builder (backlog P2-26, spec 7A).

- A report starts from a data source (journal lines, vouchers, customer tax invoices,
  supplier invoices, stock movements) or from a ready-made one built on them. The person
  chooses the columns and their order, filters, a grouping with subtotals, the sort, and
  optionally period columns: one measure spread over months or divisions.
- Every run goes through the same visibility as the module's own pages: a source needs its
  area (e.g. Sales for invoices) and only the person's divisions are read. A report shared
  with a role shows each person only what their own access allows.
- Reports are saved by name, kept private or shared with a role, exported to Excel or PDF and
  emailed (the "report" message of Settings → Document email) with the Excel file attached.
"""

import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import F, QuerySet, Sum
from django.db.models.functions import TruncMonth

from apps.core.access import division_scope, effective_access, filter_by_division
from apps.core.models import User

MAX_ROWS = 5000
ZERO = Decimal("0")


class ReportError(Exception):
    pass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    path: str
    kind: str = "text"  # text, date, money, number


@dataclass(frozen=True)
class Source:
    key: str
    label: str
    area: str
    date_field: str
    fields: tuple

    def field(self, key: str) -> Field:
        for f in self.fields:
            if f.key == key:
                return f
        raise ReportError(f"{self.label} has no column {key!r}.")


# --- Data sources ----------------------------------------------------------------------------


def _journal_lines(user: User) -> QuerySet:
    from .models import JournalLine

    return filter_by_division(JournalLine.objects.all(), user)


def _vouchers(user: User) -> QuerySet:
    from apps.vouchers import services

    return services.visible(user)


def _sales_invoices(user: User) -> QuerySet:
    from apps.sales import invoices

    return invoices.visible(user).exclude(status="draft")


def _supplier_invoices(user: User) -> QuerySet:
    from apps.purchasing import invoices

    return invoices.visible(user)


def _stock(user: User) -> QuerySet:
    from apps.inventory.models import StockMovement

    return StockMovement.objects.filter(division__in=division_scope(user))


SOURCES = {
    "journal_lines": Source(
        "journal_lines",
        "Journal lines (the ledger)",
        "financial_reports",
        "entry__entry_date",
        (
            Field("date", "Date", "entry__entry_date", "date"),
            Field("entry", "Entry", "entry__number"),
            Field("narration", "Narration", "entry__narration"),
            Field("source", "Posted by", "entry__source_type"),
            Field("account_number", "Account no.", "account__number"),
            Field("account", "Account", "account__name"),
            Field("account_type", "Account type", "account__account_type"),
            Field("division", "Division", "division__code"),
            Field("supplier", "Supplier", "supplier__name"),
            Field("customer", "Customer", "customer__name"),
            Field("description", "Description", "description"),
            Field("debit", "Debit", "debit", "money"),
            Field("credit", "Credit", "credit", "money"),
        ),
    ),
    "vouchers": Source(
        "vouchers",
        "Payment vouchers",
        "vouchers",
        "voucher_date",
        (
            Field("date", "Date", "voucher_date", "date"),
            Field("number", "Voucher", "number"),
            Field("type", "Type", "voucher_type__name"),
            Field("division", "Division", "division__code"),
            Field("payee", "Payee", "payee__name"),
            Field("description", "Description", "description"),
            Field("status", "Status", "status"),
            Field("amount", "Amount", "total_amount", "money"),
            Field("wht", "WHT", "wht_total", "money"),
        ),
    ),
    "sales_invoices": Source(
        "sales_invoices",
        "Customer tax invoices",
        "sales",
        "invoice_date",
        (
            Field("date", "Date", "invoice_date", "date"),
            Field("due", "Due date", "due_date", "date"),
            Field("number", "Invoice", "number"),
            Field("customer", "Customer", "customer__name"),
            Field("division", "Division", "division__code"),
            Field("currency", "Currency", "currency__code"),
            Field("status", "Status", "status"),
            Field("amount", "Total (currency)", "total_amount", "money"),
            Field("tax", "Tax (currency)", "tax_total", "money"),
            Field("amount_lkr", "Total (LKR)", "total_lkr", "money"),
        ),
    ),
    "supplier_invoices": Source(
        "supplier_invoices",
        "Supplier invoices",
        "vouchers",
        "invoice_date",
        (
            Field("date", "Date", "invoice_date", "date"),
            Field("due", "Due date", "due_date", "date"),
            Field("number", "Our number", "number"),
            Field("invoice_no", "Supplier's number", "invoice_no"),
            Field("supplier", "Supplier", "supplier__name"),
            Field("division", "Division", "division__code"),
            Field("currency", "Currency", "currency__code"),
            Field("status", "Status", "status"),
            Field("amount", "Total (currency)", "total_amount", "money"),
            Field("amount_lkr", "Total (LKR)", "total_lkr", "money"),
        ),
    ),
    "stock_movements": Source(
        "stock_movements",
        "Stock movements",
        "stores",
        "movement_date",
        (
            Field("date", "Date", "movement_date", "date"),
            Field("item_code", "Item code", "item__code"),
            Field("item", "Item", "item__name"),
            Field("store", "Store", "store__code"),
            Field("division", "Division", "division__code"),
            Field("kind", "Movement", "kind"),
            Field("lot", "Lot", "lot_no"),
            Field("quantity", "Quantity", "quantity", "number"),
            Field("value", "Value (LKR)", "value", "money"),
        ),
    ),
}
QUERIES = {
    "journal_lines": _journal_lines,
    "vouchers": _vouchers,
    "sales_invoices": _sales_invoices,
    "supplier_invoices": _supplier_invoices,
    "stock_movements": _stock,
}

# Ready-made reports to start from.
PRESETS = [
    {
        "name": "Sales by customer, by month",
        "definition": {
            "source": "sales_invoices",
            "columns": ["customer", "amount_lkr"],
            "group_by": "customer",
            "period": "month",
            "measure": "amount_lkr",
        },
    },
    {
        "name": "Costs by account and division",
        "definition": {
            "source": "journal_lines",
            "columns": ["account", "debit", "credit"],
            "filters": [{"field": "account_type", "op": "equals", "value": "expense"}],
            "group_by": "account",
            "period": "division",
            "measure": "debit",
        },
    },
    {
        "name": "Vouchers by payee",
        "definition": {
            "source": "vouchers",
            "columns": ["date", "number", "payee", "type", "status", "amount"],
            "group_by": "payee",
            "sort": [{"field": "date", "desc": False}],
        },
    },
    {
        "name": "Purchases by supplier, by month",
        "definition": {
            "source": "supplier_invoices",
            "columns": ["supplier", "amount_lkr"],
            "group_by": "supplier",
            "period": "month",
            "measure": "amount_lkr",
        },
    },
    {
        "name": "Stock movement value by item",
        "definition": {
            "source": "stock_movements",
            "columns": ["date", "item_code", "item", "kind", "quantity", "value"],
            "group_by": "item",
        },
    },
]

OPS = {
    "text": {"equals": "iexact", "contains": "icontains"},
    "date": {"from": "gte", "to": "lte", "equals": "exact"},
    "money": {"from": "gte", "to": "lte", "equals": "exact"},
    "number": {"from": "gte", "to": "lte", "equals": "exact"},
}


def sources_for(user: User) -> list[Source]:
    access = effective_access(user)
    return [s for s in SOURCES.values() if access.has(s.area, "view")]


# --- Checking a definition -------------------------------------------------------------------


@dataclass
class Definition:
    source: Source
    columns: list[Field]
    filters: list[tuple[Field, str, object]]
    group_by: Field | None
    sort: list[tuple[Field, bool]]
    period: str
    measure: Field | None


def _value(field: Field, value):
    text = str(value if value is not None else "").strip()
    if not text:
        raise ReportError(f"Give a value for the filter on {field.label}.")
    if field.kind == "date":
        try:
            return date.fromisoformat(text)
        except ValueError:
            raise ReportError(f"{field.label}: give a date like 2026-10-31.") from None
    if field.kind in ("money", "number"):
        try:
            number = Decimal(text.replace(",", ""))
        except InvalidOperation:
            raise ReportError(f"{field.label}: {text!r} is not a number.") from None
        if not number.is_finite():
            raise ReportError(f"{field.label}: {text!r} is not a number.")
        return number
    return text[:200]


def parse(user: User, raw) -> Definition:
    """Check a definition (a dict, or its JSON) against what the user may see."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            raise ReportError("The report could not be read.") from None
    if not isinstance(raw, dict):
        raise ReportError("The report could not be read.")
    source = SOURCES.get(str(raw.get("source", "")))
    if source is None:
        raise ReportError("Choose a data source.")
    if source not in sources_for(user):
        raise ReportError(f"You do not have access to {source.label.lower()}.")
    columns = [source.field(str(k)) for k in (raw.get("columns") or [])][:20]
    if not columns:
        raise ReportError("Choose at least one column.")
    filters = []
    for f in (raw.get("filters") or [])[:20]:
        if not isinstance(f, dict):
            raise ReportError("A filter could not be read.")
        field = source.field(str(f.get("field", "")))
        op = str(f.get("op", ""))
        if op not in OPS[field.kind]:
            raise ReportError(f"{field.label} cannot be filtered with {op!r}.")
        filters.append((field, op, _value(field, f.get("value"))))
    group_by = source.field(str(raw["group_by"])) if raw.get("group_by") else None
    if group_by is not None and group_by.kind in ("money", "number"):
        raise ReportError("Group by a name, a code or a date, not an amount.")
    sort = []
    for s in (raw.get("sort") or [])[:3]:
        if isinstance(s, dict) and s.get("field"):
            sort.append((source.field(str(s["field"])), bool(s.get("desc"))))
    period = str(raw.get("period") or "")
    if period not in ("", "month", "division"):
        raise ReportError("Period columns are by month or by division.")
    measure = None
    if period:
        measure = source.field(str(raw.get("measure") or ""))
        if measure.kind not in ("money", "number"):
            raise ReportError("Choose an amount to spread over the period columns.")
    return Definition(source, columns, filters, group_by, sort, period, measure)


# --- Running ---------------------------------------------------------------------------------


def _rows(user: User, d: Definition) -> QuerySet:
    rows = QUERIES[d.source.key](user)
    for field, op, value in d.filters:
        rows = rows.filter(**{f"{field.path}__{OPS[field.kind][op]}": value})
    return rows


def _cell(field: Field, value):
    if value is None:
        return ""
    if field.kind == "money":
        return f"{Decimal(value):.2f}"
    if field.kind == "number":
        return f"{Decimal(value).normalize():f}"
    return value


def _sums(fields: list[Field], rows: list[dict]) -> dict:
    out = {}
    for f in fields:
        if f.kind in ("money", "number"):
            total = sum((Decimal(r[f.key] or 0) for r in rows), ZERO)
            out[f.key] = _cell(f, total)
    return out


def run(user: User, d: Definition) -> dict:
    if d.period:
        return _pivot(user, d)
    fields = list(d.columns)
    if d.group_by and d.group_by not in fields:
        fields.insert(0, d.group_by)
    order = [("-" if desc else "") + f.path for f, desc in d.sort]
    if d.group_by:
        order.insert(0, d.group_by.path)
    rows = _rows(user, d).order_by(*(order or ["pk"]))
    found = list(rows.values(*[f.path for f in fields])[: MAX_ROWS + 1])
    truncated = len(found) > MAX_ROWS
    found = [{f.key: r[f.path] for f in fields} for r in found[:MAX_ROWS]]
    # Subtotal and total labels go in the first text column (a date column holds dates only).
    label = next((f.key for f in fields if f.kind == "text"), None)

    def labelled(text: str) -> dict:
        return {label: text} if label else {}

    out = []
    if d.group_by:
        groups: OrderedDict = OrderedDict()
        for r in found:
            groups.setdefault(r[d.group_by.key], []).append(r)
        for key, members in groups.items():
            for r in members:
                out.append({"kind": "line", "cells": {f.key: _cell(f, r[f.key]) for f in fields}})
            out.append(
                {
                    "kind": "subtotal",
                    "cells": labelled(f"{_cell(d.group_by, key) or '(none)'}: total")
                    | _sums(fields, members),
                }
            )
    else:
        out = [
            {"kind": "line", "cells": {f.key: _cell(f, r[f.key]) for f in fields}} for r in found
        ]
    if any(f.kind in ("money", "number") for f in fields):
        out.append({"kind": "total", "cells": labelled("Total") | _sums(fields, found)})
    return {
        "columns": [{"key": f.key, "label": f.label, "kind": f.kind} for f in fields],
        "rows": out,
        "count": len(found),
        "truncated": truncated,
    }


def _pivot(user: User, d: Definition) -> dict:
    rows = _rows(user, d)
    if d.period == "month":
        bucket = TruncMonth(d.source.date_field)
    else:
        bucket = F("division__code")
    group = d.group_by.path if d.group_by else None
    values = [group] if group else []
    found = (
        rows.annotate(bucket=bucket)
        .values(*values, "bucket")
        .annotate(total=Sum(d.measure.path))
        .order_by(*values, "bucket")
    )
    buckets: list = []
    table: OrderedDict = OrderedDict()
    for r in found:
        b = r["bucket"]
        b = b.strftime("%Y-%m") if hasattr(b, "strftime") else (b or "(none)")
        if b not in buckets:
            buckets.append(b)
        key = r[group] if group else "Total"
        table.setdefault(key, {})[b] = table.get(key, {}).get(b, ZERO) + (r["total"] or ZERO)
    buckets.sort()
    label_key = d.group_by.key if d.group_by else "row"
    columns = [{"key": label_key, "label": d.group_by.label if d.group_by else "", "kind": "text"}]
    columns += [{"key": b, "label": b, "kind": d.measure.kind} for b in buckets]
    columns.append({"key": "total", "label": "Total", "kind": d.measure.kind})
    out = []
    grand = {b: ZERO for b in buckets}
    for key, cells in table.items():
        line = {label_key: _cell(d.group_by, key) if d.group_by else key}
        for b in buckets:
            line[b] = _cell(d.measure, cells.get(b, ZERO))
            grand[b] += cells.get(b, ZERO)
        line["total"] = _cell(d.measure, sum(cells.values(), ZERO))
        out.append({"kind": "line", "cells": line})
    total = {label_key: "Total"} | {b: _cell(d.measure, grand[b]) for b in buckets}
    total["total"] = _cell(d.measure, sum(grand.values(), ZERO))
    out.append({"kind": "total", "cells": total})
    return {"columns": columns, "rows": out, "count": len(table), "truncated": False}


def title_of(d: Definition, name: str = "") -> str:
    return name or d.source.label


# --- Saved reports ---------------------------------------------------------------------------


def saved_for(user: User):
    """The reports the user saved, and those shared with a role they hold."""
    from django.db.models import Q

    from apps.core.models import UserRole

    from .models import SavedReport

    roles = UserRole.objects.filter(user=user).values_list("role_id", flat=True)
    return (
        SavedReport.objects.filter(Q(owner=user) | Q(shared_role_id__in=list(roles)))
        .select_related("owner", "shared_role")
        .order_by("name")
    )


def save(user: User, *, name: str, raw, shared_role=None, report=None):
    from django.utils import timezone

    from apps.core.audit import audit_context

    from .models import SavedReport

    name = " ".join((name or "").split())
    if not name:
        raise ReportError("Give the report a name.")
    d = parse(user, raw)
    definition = raw if isinstance(raw, dict) else json.loads(raw)
    definition = {**definition, "source": d.source.key}
    if report is not None and report.owner_id != user.pk:
        raise ReportError("Only the person who saved a report changes it.")
    with audit_context("report_saved"):
        if report is None:
            return SavedReport.objects.create(
                name=name[:100], definition=definition, owner=user, shared_role=shared_role
            )
        report.name = name[:100]
        report.definition = definition
        report.shared_role = shared_role
        report.updated_at = timezone.now()
        report.save()
        return report


def delete(user: User, report) -> None:
    from apps.core.audit import audit_context

    if report.owner_id != user.pk:
        raise ReportError("Only the person who saved a report deletes it.")
    with audit_context("report_deleted"):
        report.delete()
