"""Tax reports for filing (backlog P2-20, spec 6): the VAT return, SSCL and WHT, by month,
each line traced to its document. Amounts are in LKR (foreign-currency invoices at their own
rate, as posted). Rates are the dated tax master data the documents used.

- VAT return. Supplies from issued tax invoices less approved credit notes, by the tax code
  on each line: standard-rated (a code with VAT), zero-rated (ZERO-RATED: exports), exempt
  (EXEMPT) and outside VAT (no code or no VAT). Output VAT is what the documents charged, and
  is checked against the VAT payable account. Input VAT is what the books claimed: every
  posting to VAT receivable in the month (supplier invoices, and the recoverable VAT of
  vouchers when they are paid), each with its document and supplier.
- SSCL: the levy charged on each invoice less credit notes, with its base.
- WHT: tax kept from supplier payments, with the certificate, the supplier's TIN, gross,
  rate and tax.
"""

import calendar
from collections import OrderedDict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q, Sum

from .models import Account, JournalLine, TaxComponent

ZERO = Decimal("0")
CENT = Decimal("0.01")
CATEGORIES = OrderedDict(
    [
        ("standard", "Standard-rated supplies"),
        ("zero", "Zero-rated supplies (exports)"),
        ("exempt", "Exempt supplies"),
        ("outside", "Outside VAT (no VAT on the line)"),
    ]
)


def month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def _lkr(amount: Decimal, rate: Decimal) -> Decimal:
    return (Decimal(amount) * rate).quantize(CENT, ROUND_HALF_UP)


def _system(role: str) -> Account | None:
    return Account.objects.filter(system_role=role).first()


def is_vat(component: TaxComponent) -> bool:
    payable = _system("vat_payable")
    return component.code == "VAT" or (
        payable is not None and component.sales_account_id == payable.pk
    )


def is_sscl(component: TaxComponent) -> bool:
    return component.code.startswith("SSCL") or component.printed_as == "SSCL"


def category(tax_code) -> str:
    if tax_code is None:
        return "outside"
    if tax_code.code == "ZERO-RATED":
        return "zero"
    if tax_code.code.startswith("EXEMPT"):
        return "exempt"
    if any(is_vat(line.component) for line in tax_code.lines.select_related("component")):
        return "standard"
    return "outside"


def _documents(start: date, end: date):
    """Issued tax invoices dated in the month, and approved credit notes dated in it."""
    from apps.sales.models import CreditNote, TaxInvoice

    invoices = (
        TaxInvoice.objects.filter(status=TaxInvoice.Status.ISSUED, invoice_date__range=(start, end))
        .exclude(number="")
        .select_related("customer", "currency")
        .order_by("invoice_date", "number")
    )
    notes = (
        CreditNote.objects.filter(
            status=CreditNote.Status.APPROVED, credit_date__range=(start, end)
        )
        .select_related("customer", "invoice", "invoice__currency")
        .order_by("credit_date", "number")
    )
    return invoices, notes


def vat_return(year: int, month: int) -> dict:
    start, end = month_range(year, month)
    invoices, notes = _documents(start, end)
    supplies = {key: ZERO for key in CATEGORIES}
    output_vat = ZERO
    rows = []
    codes = {}

    def cat(code):
        if code is None:
            return "outside"
        if code.pk not in codes:
            codes[code.pk] = category(code)
        return codes[code.pk]

    for invoice in invoices:
        rate = invoice.exchange_rate
        values = {key: ZERO for key in CATEGORIES}
        for line in invoice.lines.select_related("tax_code"):
            values[cat(line.tax_code)] += _lkr(line.amount - line.discount, rate)
        vat = sum(
            (
                _lkr(t.amount, rate)
                for t in invoice.taxes.select_related("component")
                if is_vat(t.component)
            ),
            ZERO,
        )
        for key in CATEGORIES:
            supplies[key] += values[key]
        output_vat += vat
        rows.append(
            {
                "date": invoice.invoice_date,
                "document": invoice.number,
                "kind": "Tax invoice",
                "link": f"/tax-invoices/{invoice.pk}",
                "customer": invoice.customer_name or invoice.customer.name,
                "tin": invoice.customer_tin,
                **{key: values[key] for key in CATEGORIES},
                "vat": vat,
            }
        )
    for note in notes:
        rate = note.invoice.exchange_rate
        values = {key: ZERO for key in CATEGORIES}
        for line in note.lines.select_related("invoice_line__tax_code"):
            values[cat(line.invoice_line.tax_code)] -= _lkr(line.amount, rate)
        vat = -sum(
            (
                _lkr(t.amount, rate)
                for t in note.taxes.select_related("component")
                if is_vat(t.component)
            ),
            ZERO,
        )
        for key in CATEGORIES:
            supplies[key] += values[key]
        output_vat += vat
        rows.append(
            {
                "date": note.credit_date,
                "document": note.number,
                "kind": f"Credit note on {note.invoice.number}",
                "link": f"/credit-notes/{note.pk}",
                "customer": note.customer.name,
                "tin": note.invoice.customer_tin,
                **{key: values[key] for key in CATEGORIES},
                "vat": vat,
            }
        )
    inputs = input_vat(start, end)
    payable = _system("vat_payable")
    ledger_output = ZERO
    if payable is not None:
        found = JournalLine.objects.filter(
            account=payable, entry__entry_date__range=(start, end)
        ).aggregate(c=Sum("credit"), d=Sum("debit"))
        ledger_output = (found["c"] or ZERO) - (found["d"] or ZERO)
    input_total = sum((r["vat"] for r in inputs), ZERO)
    return {
        "start": start,
        "end": end,
        "supplies": supplies,
        "output_vat": output_vat,
        "ledger_output_vat": ledger_output,
        "input_vat": input_total,
        "payable": output_vat - input_total,
        "sales": rows,
        "purchases": inputs,
    }


def input_vat(start: date, end: date) -> list[dict]:
    """Every posting to VAT receivable in the month, with its document."""
    receivable = _system("vat_receivable")
    if receivable is None:
        return []
    rows = []
    lines = (
        JournalLine.objects.filter(account=receivable, entry__entry_date__range=(start, end))
        .exclude(Q(debit=0) & Q(credit=0))
        .select_related("entry", "supplier")
        .order_by("entry__entry_date", "entry__number", "line_no")
    )
    for line in lines:
        entry = line.entry
        rows.append(
            {
                "date": entry.entry_date,
                "entry": entry.number,
                "source_type": entry.source_type,
                "document": entry.source_id,
                "supplier": line.supplier.name if line.supplier_id else "",
                "tin": line.supplier.tin if line.supplier_id else "",
                "narration": entry.narration,
                "vat": line.debit - line.credit,
            }
        )
    return rows


def sscl(year: int, month: int) -> dict:
    start, end = month_range(year, month)
    invoices, notes = _documents(start, end)
    rows = []
    for doc, sign, when, rate, kind in [
        *[(i, 1, i.invoice_date, i.exchange_rate, "Tax invoice") for i in invoices],
        *[(n, -1, n.credit_date, n.invoice.exchange_rate, "Credit note") for n in notes],
    ]:
        if kind == "Tax invoice":
            nets = [
                (x.tax_code, x.amount - x.discount) for x in doc.lines.select_related("tax_code")
            ]
        else:
            nets = [
                (x.invoice_line.tax_code, x.amount)
                for x in doc.lines.select_related("invoice_line__tax_code")
            ]
        for tax in doc.taxes.select_related("component").order_by("seq"):
            if not is_sscl(tax.component):
                continue
            # The base: the lines whose tax code charges this levy.
            base = sum(
                (
                    net
                    for code, net in nets
                    if code is not None and code.lines.filter(component=tax.component).exists()
                ),
                ZERO,
            )
            rows.append(
                {
                    "date": when,
                    "document": doc.number,
                    "kind": kind,
                    "customer": doc.customer.name,
                    "component": tax.component.code,
                    "rate": tax.rate,
                    "base": sign * _lkr(base, rate),
                    "sscl": sign * _lkr(tax.amount, rate),
                }
            )
    return {
        "start": start,
        "end": end,
        "rows": rows,
        "total": sum((r["sscl"] for r in rows), ZERO),
    }


def wht(year: int, month: int) -> dict:
    from apps.payments.models import SupplierPayment

    start, end = month_range(year, month)
    payments = (
        SupplierPayment.objects.filter(
            payment_date__range=(start, end), wht_amount__gt=0, cancelled=False
        )
        .select_related("voucher__payee")
        .order_by("payment_date", "number")
    )
    rows = []
    for p in payments:
        payee = p.voucher.payee
        rates = sorted(
            {f"{line.wht_rate.normalize():f}%" for line in p.voucher.lines.filter(wht_amount__gt=0)}
        )
        rows.append(
            {
                "date": p.payment_date,
                "certificate": p.wht_certificate,
                "payment": p.number,
                "voucher": p.voucher.number,
                "supplier": payee.name if payee else "",
                "tin": payee.tin if payee else "",
                "rate": ", ".join(rates),
                "gross": p.amount,
                "wht": p.wht_amount,
                "paid": p.paid_amount,
            }
        )
    return {
        "start": start,
        "end": end,
        "rows": rows,
        "total": sum((r["wht"] for r in rows), ZERO),
    }
