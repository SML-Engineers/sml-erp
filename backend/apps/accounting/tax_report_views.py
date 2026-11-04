"""Tax reports API (P2-20): ?year=&month=, and &export=xlsx|pdf for the filing copy."""

from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import exports
from apps.core.permissions import AreaAccess

from . import tax_reports
from .tax_reports import CATEGORIES


class _Tax(APIView):
    permission_classes = [AreaAccess]
    access_area = "accounting"
    access_also_area = "financial_reports"


def _month(request) -> tuple[int, int]:
    today = timezone.localdate()
    default = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
    try:
        year = int(request.query_params.get("year") or default[0])
        month = int(request.query_params.get("month") or default[1])
    except ValueError:
        return default
    if not 1 <= month <= 12 or not 2000 <= year <= 2100:
        return default
    return year, month


def _m(value) -> str:
    return f"{value:.2f}"


def _fmt(request) -> str:
    fmt = (request.query_params.get("export") or "").lower()
    return fmt if fmt in exports.FORMATS else ""


SALES_COLUMNS = [
    exports.Column("date", "Date", "date"),
    exports.Column("document", "Document", width=1.3),
    exports.Column("customer", "Customer", width=2),
    exports.Column("tin", "TIN"),
    exports.Column("standard", "Standard-rated", "money"),
    exports.Column("zero", "Zero-rated", "money"),
    exports.Column("exempt", "Exempt", "money"),
    exports.Column("outside", "Outside VAT", "money"),
    exports.Column("vat", "Output VAT", "money"),
]
PURCHASE_COLUMNS = [
    exports.Column("date", "Date", "date"),
    exports.Column("entry", "Journal entry"),
    exports.Column("document", "Document", width=1.3),
    exports.Column("supplier", "Supplier", width=2),
    exports.Column("tin", "TIN"),
    exports.Column("vat", "Input VAT", "money"),
]


class VatView(_Tax):
    def get(self, request):
        year, month = _month(request)
        data = tax_reports.vat_return(year, month)
        period = f"{data['start']:%B %Y}"
        fmt = _fmt(request)
        if fmt:
            rows = data["sales"] + [
                {
                    "document": "Total supplies and output VAT",
                    **data["supplies"],
                    "vat": data["output_vat"],
                    exports.STRONG: True,
                },
                {
                    "document": "Input VAT (claimed in the books)",
                    "vat": -data["input_vat"],
                    exports.STRONG: True,
                },
                {
                    "document": "VAT payable for the month",
                    "vat": data["payable"],
                    exports.STRONG: True,
                },
            ]
            return exports.response(
                fmt,
                title="VAT return",
                subtitle=f"{period}: supplies and output VAT by document; input VAT and the "
                "amount payable at the end",
                columns=SALES_COLUMNS,
                rows=rows,
                filename=f"vat-{year}-{month:02d}",
                user=request.user,
                totals=False,
            )
        return Response(
            {
                "year": year,
                "month": month,
                "supplies": {k: _m(v) for k, v in data["supplies"].items()},
                "output_vat": _m(data["output_vat"]),
                "ledger_output_vat": _m(data["ledger_output_vat"]),
                "input_vat": _m(data["input_vat"]),
                "payable": _m(data["payable"]),
                "sales": [
                    {**r, **{k: _m(r[k]) for k in [*CATEGORIES, "vat"]}} for r in data["sales"]
                ],
                "purchases": [{**r, "vat": _m(r["vat"])} for r in data["purchases"]],
            }
        )


class VatPurchasesExportView(_Tax):
    def get(self, request):
        year, month = _month(request)
        data = tax_reports.vat_return(year, month)
        return exports.response(
            _fmt(request) or "xlsx",
            title="Input VAT",
            subtitle=f"{data['start']:%B %Y}: VAT claimed in the books, by document",
            columns=PURCHASE_COLUMNS,
            rows=data["purchases"],
            filename=f"input-vat-{year}-{month:02d}",
            user=request.user,
        )


SSCL_COLUMNS = [
    exports.Column("date", "Date", "date"),
    exports.Column("document", "Document", width=1.3),
    exports.Column("customer", "Customer", width=2),
    exports.Column("component", "Levy"),
    exports.Column("rate", "Rate %"),
    exports.Column("base", "Base", "money"),
    exports.Column("sscl", "SSCL", "money"),
]


class SsclView(_Tax):
    def get(self, request):
        year, month = _month(request)
        data = tax_reports.sscl(year, month)
        fmt = _fmt(request)
        if fmt:
            return exports.response(
                fmt,
                title="SSCL",
                subtitle=f"{data['start']:%B %Y}: levy charged on invoices, less credit notes",
                columns=SSCL_COLUMNS,
                rows=[{**r, "rate": f"{r['rate'].normalize():f}"} for r in data["rows"]],
                filename=f"sscl-{year}-{month:02d}",
                user=request.user,
            )
        return Response(
            {
                "year": year,
                "month": month,
                "total": _m(data["total"]),
                "rows": [
                    {
                        **r,
                        "rate": f"{r['rate'].normalize():f}",
                        "base": _m(r["base"]),
                        "sscl": _m(r["sscl"]),
                    }
                    for r in data["rows"]
                ],
            }
        )


WHT_COLUMNS = [
    exports.Column("date", "Date", "date"),
    exports.Column("certificate", "Certificate"),
    exports.Column("supplier", "Supplier", width=2),
    exports.Column("tin", "TIN"),
    exports.Column("rate", "Rate"),
    exports.Column("gross", "Gross", "money"),
    exports.Column("wht", "WHT", "money"),
    exports.Column("paid", "Paid", "money"),
]


class WhtView(_Tax):
    def get(self, request):
        year, month = _month(request)
        data = tax_reports.wht(year, month)
        fmt = _fmt(request)
        if fmt:
            return exports.response(
                fmt,
                title="Withholding tax",
                subtitle=f"{data['start']:%B %Y}: tax kept from supplier payments",
                columns=WHT_COLUMNS,
                rows=data["rows"],
                filename=f"wht-{year}-{month:02d}",
                user=request.user,
            )
        return Response(
            {
                "year": year,
                "month": month,
                "total": _m(data["total"]),
                "rows": [
                    {**r, **{k: _m(r[k]) for k in ("gross", "wht", "paid")}} for r in data["rows"]
                ],
            }
        )
