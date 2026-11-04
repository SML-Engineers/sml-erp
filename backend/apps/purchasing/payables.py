"""Payables aging and supplier statements (backlog P2-10, spec 6).

What we owe a supplier comes from our own documents, so it covers both ways suppliers are
paid:
- matched supplier invoices (Phase 1.6): the LKR total, less advances set off, debit notes,
  and the part of the vouchers on it that has been paid;
- invoices paid on vouchers directly (Phase 1): each voucher line, less the part of the
  voucher that has been paid.
A voucher's payments pay its lines in proportion, as the ledger books them (payments.journal
lines). Advances paid before the goods (P16-11a) are not payables. Aged by days past the due
date: the supplier invoice's, or the voucher line's invoice date plus the supplier's terms.

Supplier statements are typed in or imported (Excel or CSV: Date, Reference, Description,
Debit, Credit), then matched line by line against our invoices, debit notes and payments of
the period: by reference (case and spaces ignored), and payments without a match by the
same amount within a week. The differences are listed, with the supplier's closing balance
against ours. The Accountant marks a statement checked, with a note; it then never changes.
Payments are compared in the statement's currency (what left our account, P2-11); for a
supplier in another currency the balances are not compared, as our books keep it in LKR.
"""

import csv
import io
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.masters.models import Supplier
from apps.payments.models import SupplierPayment
from apps.vouchers.models import VoucherLine
from apps.vouchers.services import INVOICE_FREED

from .models import (
    AdvanceSetOff,
    DebitNote,
    SupplierInvoice,
    SupplierStatement,
    SupplierStatementLine,
)
from .orders import PurchasingError

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
BUCKETS = (
    ("current", "Not yet due"),
    ("d30", "1-30 days"),
    ("d60", "31-60 days"),
    ("d90", "61-90 days"),
    ("over90", "Over 90 days"),
)
MAX_LINES = 2000
MAX_BYTES = 5 * 1024 * 1024
WEEK = timedelta(days=7)
St = SupplierStatement.Status


# --- Who may do what ---------------------------------------------------------------------


def can_view(user: User) -> bool:
    access = effective_access(user)
    return access.has("vouchers", "view") or access.has("accounting", "view")


def can_enter(user: User) -> bool:
    """Typing in or importing a statement: the Clerk or the Accountant."""
    access = effective_access(user)
    return access.has("vouchers", "enter") or access.has("accounting", "enter")


def can_check(user: User) -> bool:
    """Marking a statement checked: the Accountant (Accounting: Enter)."""
    return effective_access(user).has("accounting", "enter")


def _bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "d30"
    if days_overdue <= 60:
        return "d60"
    if days_overdue <= 90:
        return "d90"
    return "over90"


def _part(total: Decimal, paid: Decimal, of: Decimal) -> Decimal:
    """The share of `paid` that falls on a line of `total` in a voucher of `of`."""
    if not of:
        return ZERO
    share = min(paid, of) * total / of
    return share.quantize(CENT, ROUND_HALF_UP)


# --- What we owe ----------------------------------------------------------------------------


def _paid(voucher_ids, as_at: date) -> dict[int, Decimal]:
    rows = (
        SupplierPayment.objects.filter(
            voucher_id__in=voucher_ids, cancelled=False, payment_date__lte=as_at
        )
        .values("voucher")
        .annotate(total=Sum("amount"))
    )
    return {r["voucher"]: r["total"] for r in rows}


def open_items(
    as_at: date, *, user: User | None = None, supplier: Supplier | None = None, division=None
) -> list[dict]:
    """Everything still owed at `as_at`, oldest first: one row per supplier invoice or
    voucher line, with its LKR amount, what is open, and its age. `user` limits it to their
    divisions."""
    invoices = SupplierInvoice.objects.filter(
        status=SupplierInvoice.Status.POSTED, invoice_date__lte=as_at
    ).select_related("supplier", "division")
    lines = (
        VoucherLine.objects.filter(voucher__payee__isnull=False, advance_order__isnull=True)
        .exclude(voucher__status__in=INVOICE_FREED)
        .select_related("voucher__payee", "voucher__division")
    )
    if user is not None:
        scope = division_scope(user)
        invoices = invoices.filter(division__in=scope)
        lines = lines.filter(voucher__division__in=scope)
    if supplier is not None:
        invoices = invoices.filter(supplier=supplier)
        lines = lines.filter(voucher__payee=supplier)
    if division is not None:
        invoices = invoices.filter(division=division)
        lines = lines.filter(voucher__division=division)
    lines = list(lines)
    paid = _paid({line.voucher_id for line in lines}, as_at)
    paid_on: dict[int, Decimal] = defaultdict(lambda: ZERO)
    items = []
    for line in lines:
        voucher = line.voucher
        share = _part(line.total, paid.get(voucher.pk, ZERO), voucher.total_amount)
        if line.supplier_invoice_id:
            paid_on[line.supplier_invoice_id] += share
            continue
        when = line.invoice_date or voucher.voucher_date
        if when > as_at:
            continue
        left = line.total - share
        if not left:
            continue
        due = when + timedelta(days=voucher.payee.payment_terms_days)
        items.append(
            {
                "kind": "voucher",
                "supplier": voucher.payee,
                "division": voucher.division,
                "reference": line.invoice_no or line.description,
                "document": voucher.number,
                "link": f"/vouchers/{voucher.pk}",
                "date": when,
                "due_date": due,
                "total": line.total,
                "open": left,
            }
        )
    invoices = list(invoices)
    keys = [i.pk for i in invoices]
    set_off = dict(
        AdvanceSetOff.objects.filter(invoice__in=keys, created_at__date__lte=as_at)
        .values("invoice")
        .annotate(t=Sum("amount"))
        .values_list("invoice", "t")
    )
    debited = dict(
        DebitNote.objects.filter(invoice__in=keys, created_at__date__lte=as_at)
        .values("invoice")
        .annotate(t=Sum("total_lkr"))
        .values_list("invoice", "t")
    )
    for invoice in invoices:
        left = (
            invoice.total_lkr
            - set_off.get(invoice.pk, ZERO)
            - debited.get(invoice.pk, ZERO)
            - paid_on[invoice.pk]
        )
        if not left:
            continue
        items.append(
            {
                "kind": "invoice",
                "supplier": invoice.supplier,
                "division": invoice.division,
                "reference": invoice.invoice_no,
                "document": invoice.number,
                "link": f"/supplier-invoices/{invoice.pk}",
                "date": invoice.invoice_date,
                "due_date": invoice.due_date,
                "total": invoice.total_lkr,
                "open": left,
                "invoice": invoice,  # month-end revaluation reads its currency (P2-21)
            }
        )
    for item in items:
        item["days_overdue"] = (as_at - item["due_date"]).days
        item["bucket"] = _bucket(item["days_overdue"])
    items.sort(key=lambda i: (i["date"], i["document"]))
    return items


def aging(user: User, as_at: date, *, supplier=None, division=None) -> list[dict]:
    """One row per supplier: what we owe by age, and the total, in LKR."""
    rows: dict[int, dict] = {}
    for item in open_items(as_at, user=user, supplier=supplier, division=division):
        s = item["supplier"]
        row = rows.setdefault(
            s.pk,
            {
                "supplier_id": s.pk,
                "code": s.code,
                "supplier": s.name,
                **{key: ZERO for key, _ in BUCKETS},
                "total": ZERO,
            },
        )
        row[item["bucket"]] += item["open"]
        row["total"] += item["open"]
    ordered = sorted(rows.values(), key=lambda r: r["supplier"].lower())
    return [
        {k: (f"{v:.2f}" if isinstance(v, Decimal) else v) for k, v in r.items()} for r in ordered
    ]


def owed(supplier: Supplier, as_at: date) -> Decimal:
    """What we owe the supplier at `as_at`, in LKR, in every division."""
    return sum((i["open"] for i in open_items(as_at, supplier=supplier)), ZERO)


# --- Supplier statements: entering ------------------------------------------------------------


@dataclass
class LineInput:
    date: object
    reference: str = ""
    description: str = ""
    debit: object = "0"
    credit: object = "0"


def _amount(value, what: str) -> Decimal:
    if isinstance(value, float):
        value = repr(value)  # Excel numbers: the shortest exact form, never float arithmetic
    text = str(value if value not in (None, "") else "0").replace(",", "").strip()
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise PurchasingError(f"{what} is not an amount.") from None
    if not amount.is_finite() or abs(amount) >= Decimal("1e16"):
        raise PurchasingError(f"{what} is not an amount.")
    if amount != amount.quantize(CENT):
        raise PurchasingError(f"{what} has more than two decimals.")
    return amount.quantize(CENT)


def _date(value, what: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d-%b-%Y", "%d %b %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise PurchasingError(f"{what}: the date {text or '(empty)'} is not a date.")


def _check_lines(given: list[LineInput]) -> list[dict]:
    if not given:
        raise PurchasingError("Enter the statement's lines.")
    if len(given) > MAX_LINES:
        raise PurchasingError(f"A statement can have at most {MAX_LINES} lines.")
    rows = []
    for n, line in enumerate(given, start=1):
        where = f"Line {n}"
        debit = _amount(line.debit, f"{where}: the debit")
        credit = _amount(line.credit, f"{where}: the credit")
        if debit < 0:  # a negative debit is a credit, as some suppliers print it
            debit, credit = ZERO, credit - debit
        if credit < 0:
            debit, credit = debit - credit, ZERO
        if (debit > 0) == (credit > 0):
            raise PurchasingError(f"{where}: enter either a debit or a credit.")
        rows.append(
            {
                "line_no": n,
                "date": _date(line.date, where),
                "reference": (line.reference or "").strip()[:60],
                "description": (line.description or "").strip()[:300],
                "debit": debit,
                "credit": credit,
            }
        )
    return rows


def _header(values: dict, statement: SupplierStatement | None) -> dict:
    statement_date = values.get("statement_date", statement and statement.statement_date)
    if not isinstance(statement_date, date):
        raise PurchasingError("Enter the statement date.")
    if statement_date > timezone.localdate():
        raise PurchasingError("The statement date cannot be in the future.")
    from_date = values.get("from_date", statement.from_date if statement else None)
    if from_date is not None and from_date > statement_date:
        raise PurchasingError("The statement starts after its own date.")
    closing = _amount(
        values.get("closing_balance", statement and statement.closing_balance),
        "The closing balance",
    )
    return {
        "statement_date": statement_date,
        "from_date": from_date,
        "closing_balance": closing,
        "notes": (values.get("notes", statement.notes if statement else "") or "").strip()[:2000],
    }


def create(user: User, supplier: Supplier, *, lines: list[LineInput], **values):
    if not can_enter(user):
        raise PurchasingError("The Clerk or the Accountant enters supplier statements.")
    if not isinstance(supplier, Supplier):
        raise PurchasingError("Choose the supplier.")
    header = _header(values, None)
    checked = _check_lines(lines)
    with audit_context("supplier_statement_entered"), transaction.atomic():
        statement = SupplierStatement.objects.create(
            supplier=supplier, currency=supplier.currency, created_by=user, **header
        )
        SupplierStatementLine.objects.bulk_create(
            SupplierStatementLine(statement=statement, **row) for row in checked
        )
        return statement


def save(user: User, statement: SupplierStatement, *, lines: list[LineInput], **values):
    """Correct an open statement: its header and all its lines."""
    if not can_enter(user):
        raise PurchasingError("The Clerk or the Accountant enters supplier statements.")
    header = _header(values, statement)
    checked = _check_lines(lines)
    with audit_context("supplier_statement_changed"), transaction.atomic():
        statement = SupplierStatement.objects.select_for_update().get(pk=statement.pk)
        if statement.status != St.OPEN:
            raise PurchasingError("A checked statement never changes.")
        for key, value in header.items():
            setattr(statement, key, value)
        statement.save()
        statement.lines.all().delete()
        SupplierStatementLine.objects.bulk_create(
            SupplierStatementLine(statement=statement, **row) for row in checked
        )
        return statement


def delete(user: User, statement: SupplierStatement) -> None:
    if not can_enter(user):
        raise PurchasingError("The Clerk or the Accountant enters supplier statements.")
    with audit_context("supplier_statement_deleted"), transaction.atomic():
        statement = SupplierStatement.objects.select_for_update().get(pk=statement.pk)
        if statement.status != St.OPEN:
            raise PurchasingError("A checked statement is kept for good.")
        statement.delete()


def check(user: User, statement: SupplierStatement, note: str) -> SupplierStatement:
    """The Accountant marks the statement checked, with what was found; it then never
    changes."""
    if not can_check(user):
        raise PurchasingError("The Accountant marks supplier statements checked.")
    note = (note or "").strip()
    if not note:
        raise PurchasingError("Write what was found (for example: agrees, or the differences).")
    with audit_context("supplier_statement_checked", note), transaction.atomic():
        statement = SupplierStatement.objects.select_for_update().get(pk=statement.pk)
        if statement.status != St.OPEN:
            raise PurchasingError("The statement has already been checked.")
        statement.status = St.CHECKED
        statement.checked_by = user
        statement.checked_at = timezone.now()
        statement.check_note = note[:2000]
        statement.save()
        return statement


# --- Importing ---------------------------------------------------------------------------------

HEADINGS = {
    "date": ("date", "txn date", "transaction date", "doc date", "document date"),
    "reference": (
        "reference",
        "ref",
        "ref no",
        "num",
        "no",
        "number",
        "document",
        "document no",
        "invoice no",
        "invoice",
        "doc no",
    ),
    "description": ("description", "details", "particulars", "narration", "memo", "type"),
    "debit": ("debit", "dr", "invoice amount", "charges", "amount due"),
    "credit": ("credit", "cr", "payment", "payments", "receipts", "paid"),
}


def _heading(value) -> str:
    return " ".join(str(value or "").replace(".", " ").lower().split())


def _heading_row(rows: list[list]) -> tuple[int, dict]:
    """The heading row (it has Date and Debit or Credit) and where each field is."""
    for at, row in enumerate(rows[:30]):
        names = [_heading(c) for c in row]
        columns: dict[str, int] = {}
        for field, words in HEADINGS.items():
            for i, name in enumerate(names):
                if name in words and field not in columns and i not in columns.values():
                    columns[field] = i
        if "date" in columns and ("debit" in columns or "credit" in columns):
            return at, columns
    raise PurchasingError(
        "No heading row found: the file needs columns Date, Reference, Description, Debit "
        "and Credit."
    )


def _table(rows: list[list]) -> list[LineInput]:
    """The rows under the heading row, without totals and balance lines."""
    at, columns = _heading_row(rows)
    lines = []

    def cell(row, field):
        i = columns.get(field)
        return row[i] if i is not None and i < len(row) else None

    for row in rows[at + 1 :]:
        if not any(c not in (None, "") for c in row):
            continue
        when = cell(row, "date")
        if when in (None, "") or _heading(when).startswith(("total", "balance", "opening")):
            continue  # totals and balance lines are not transactions
        lines.append(
            LineInput(
                date=when,
                reference=str(cell(row, "reference") or ""),
                description=str(cell(row, "description") or ""),
                debit=cell(row, "debit") or "0",
                credit=cell(row, "credit") or "0",
            )
        )
    if not lines:
        raise PurchasingError("The file has a heading row but no lines under it.")
    return lines


def parse(content: bytes, name: str) -> list[dict]:
    """Read a statement file (Excel .xlsx or CSV) into lines for the person to check before
    saving. Nothing is saved."""
    if len(content) > MAX_BYTES:
        raise PurchasingError("The file must be 5 MB or smaller.")
    if name.lower().endswith(".csv"):
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = content.decode("latin-1")
        rows = [list(r) for r in csv.reader(io.StringIO(text))]
    else:
        try:
            book = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
            raise PurchasingError("The file is not an Excel workbook (.xlsx) or a CSV.") from None
        rows = [list(r) for r in book.worksheets[0].iter_rows(values_only=True)]
    return [
        {**row, "debit": f"{row['debit']:.2f}", "credit": f"{row['credit']:.2f}"}
        for row in _check_lines(_table(rows))
    ]


# --- Supplier statements: matching ------------------------------------------------------------


def _key(text: str) -> str:
    """A reference however it is written: only its letters and digits ("inv 7" = "INV-7")."""
    return re.sub(r"[^0-9A-Z]", "", (text or "").upper())


def _same(theirs: str, keys: set[str]) -> bool:
    """The same reference, or one ends with the other ("CHQ000100" and cheque "000100")."""
    if not theirs:
        return False
    return any(
        k
        and (
            k == theirs
            or (len(k) >= 4 and theirs.endswith(k))
            or (len(theirs) >= 4 and k.endswith(theirs))
        )
        for k in keys
    )


def our_records(supplier: Supplier, currency, start: date, end: date) -> tuple[list, list]:
    """Our invoices (what the supplier charged) and our payments and debit notes (what
    reduces it) for the supplier in the period, in the statement's currency."""
    lkr = currency.code == "LKR"
    charges = [
        {
            "date": i.invoice_date,
            "reference": i.invoice_no,
            "document": i.number,
            "link": f"/supplier-invoices/{i.pk}",
            "amount": i.total_amount if i.currency_id == currency.pk else i.total_lkr,
        }
        for i in SupplierInvoice.objects.filter(
            supplier=supplier,
            status=SupplierInvoice.Status.POSTED,
            currency=currency,
            invoice_date__range=(start, end),
        )
    ]
    credits = []
    if lkr:
        for line in (
            VoucherLine.objects.filter(
                voucher__payee=supplier, supplier_invoice__isnull=True, advance_order__isnull=True
            )
            .exclude(voucher__status__in=INVOICE_FREED)
            .select_related("voucher")
        ):
            when = line.invoice_date or line.voucher.voucher_date
            if start <= when <= end:
                charges.append(
                    {
                        "date": when,
                        "reference": line.invoice_no,
                        "document": line.voucher.number,
                        "link": f"/vouchers/{line.voucher_id}",
                        "amount": line.total,
                    }
                )
        for d in DebitNote.objects.filter(
            invoice__supplier=supplier, created_at__date__range=(start, end)
        ):
            credits.append(
                {
                    "date": d.created_at.date(),
                    "reference": d.number,
                    "keys": {_key(d.number)},
                    "document": d.number,
                    "link": f"/supplier-invoices/{d.invoice_id}",
                    "amount": d.total_lkr,
                }
            )
    for p in SupplierPayment.objects.filter(
        voucher__payee=supplier,
        cancelled=False,
        currency=currency,
        payment_date__range=(start, end),
    ).select_related("cheque", "voucher"):
        refs = [p.reference] + ([str(p.cheque.number)] if p.cheque_id else [])
        credits.append(
            {
                "date": p.payment_date,
                "reference": " / ".join(r for r in refs if r),
                "keys": {_key(r) for r in refs if r}
                | ({_key(f"{p.cheque.number:06d}")} if p.cheque_id else set()),
                "document": p.number,
                "link": f"/vouchers/{p.voucher_id}",
                "amount": p.paid_amount,
            }
        )
        if p.wht_amount:
            # The WHT kept (P2-12): the supplier credits it against the certificate.
            credits.append(
                {
                    "date": p.payment_date,
                    "reference": p.wht_certificate,
                    "keys": {_key(p.wht_certificate)},
                    "document": p.number,
                    "link": f"/vouchers/{p.voucher_id}",
                    "amount": p.wht_amount,
                }
            )
    for row in charges:
        row["keys"] = {_key(row["reference"])} if row["reference"] else set()
    return charges, credits


def reconcile(statement: SupplierStatement) -> dict:
    """The statement's lines against our records of the period, and the balances."""
    lines = list(statement.lines.all())
    start = statement.from_date or min([x.date for x in lines] + [statement.statement_date])
    end = statement.statement_date
    charges, credits = our_records(statement.supplier, statement.currency, start, end)
    matched, theirs_only = [], []
    for line in lines:
        side, amount = (charges, line.debit) if line.debit else (credits, line.credit)
        key = _key(line.reference)
        found = next((o for o in side if _same(key, o["keys"])), None)
        if found is None and side is credits:
            found = next(
                (o for o in side if o["amount"] == amount and abs(o["date"] - line.date) <= WEEK),
                None,
            )
        if found is None:
            theirs_only.append(line)
            continue
        side.remove(found)
        matched.append((line, found, amount - found["amount"]))
    ours_only = [("charge", o) for o in charges] + [("credit", o) for o in credits]
    ours = owed(statement.supplier, end) if statement.currency.code == "LKR" else None
    return {
        "from": start,
        "to": end,
        "matched": matched,
        "theirs_only": theirs_only,
        "ours_only": sorted(ours_only, key=lambda x: x[1]["date"]),
        "their_balance": statement.closing_balance,
        "our_balance": ours,
        "difference": None if ours is None else statement.closing_balance - ours,
    }
