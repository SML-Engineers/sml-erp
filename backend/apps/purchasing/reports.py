"""Purchasing and stores reports and traceability (backlog P16-13, spec 5A.7, 6A.7).

- Open purchase orders and overdue deliveries.
- Goods received not invoiced (GRNI): accepted goods waiting for the supplier's invoice, at
  the PO price, next to the GRNI account's balance in the ledger.
- Supplier invoices held for discrepancies.
- Exceptions approved by the Director: GRN excesses, QC deviations, invoice differences,
  returns of accepted goods and advance payments.
- Receipts and rejections by supplier, with late deliveries and the rejection rate.
- The trail of any PO: its GRNs, QC, invoices, debit notes, advances, vouchers and
  payments, both ways.

Each report gives the same rows to the screen, Excel and PDF (apps.core.exports). A user
sees only their divisions (Purchasing: View).
"""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from apps.accounting.models import Account, JournalLine
from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.exports import Column
from apps.core.models import ApprovalLog, ApprovalState, User
from apps.inventory import inspections
from apps.inventory.models import (
    GoodsReceipt,
    GoodsReceiptLine,
    IncomingInspection,
    StockMovement,
    Store,
)
from apps.inventory.stock import unit_cost

from . import advances, invoices, orders, returns
from .models import PurchaseOrder, SupplierInvoice, SupplierReturn

ZERO = Decimal("0.00")
CENT = Decimal("0.01")
PO = PurchaseOrder.Status
OPEN = (PO.APPROVED, PO.PARTLY_RECEIVED)


def _money(value) -> str:
    return f"{(value or ZERO):.2f}"


def _qty(value) -> str:
    return f"{(value or Decimal('0')).normalize():f}"


def _division(rows: QuerySet, division: str, field: str = "division") -> QuerySet:
    return rows.filter(**{f"{field}__code": division.upper()}) if division else rows


def _grns(user: User) -> QuerySet[GoodsReceipt]:
    if not effective_access(user).has("purchasing", "view"):
        return GoodsReceipt.objects.none()
    return GoodsReceipt.objects.filter(division__in=division_scope(user))


# --- Open POs and overdue deliveries -------------------------------------------------------

OPEN_COLUMNS = [
    Column("label", "PO", width=1.2),
    Column("po_date", "Date", "date"),
    Column("division", "Division", width=0.6),
    Column("supplier", "Supplier", width=2),
    Column("delivery_date", "Delivery due", "date"),
    Column("days_late", "Days late", "number", width=0.6),
    Column("status", "Status", width=1),
    Column("received_pct", "Received %", "number", width=0.7),
    Column("total_lkr", "Value (LKR)", "money"),
    Column("outstanding_lkr", "Still to come (LKR)", "money"),
]


def open_orders(user: User, *, division: str = "", overdue_only: bool = False) -> list[dict]:
    today = timezone.localdate()
    rows = []
    found = _division(orders.visible(user).filter(status__in=OPEN), division)
    for order in found.select_related("supplier", "division").prefetch_related("lines"):
        lines = list(order.lines.all())
        ordered = sum((line.quantity for line in lines), Decimal("0"))
        received = sum((min(line.received_quantity, line.quantity) for line in lines), Decimal("0"))
        outstanding = sum(
            (
                max(line.quantity - line.received_quantity, Decimal("0"))
                * line.unit_price
                * order.exchange_rate
                for line in lines
            ),
            Decimal("0"),
        ).quantize(CENT, ROUND_HALF_UP)
        late = (today - order.delivery_date).days if order.delivery_date else 0
        if overdue_only and late <= 0:
            continue
        rows.append(
            {
                "id": order.id,
                "label": order.label,
                "po_date": order.po_date,
                "division": order.division.code,
                "supplier": order.supplier.name,
                "delivery_date": order.delivery_date,
                "days_late": late if late > 0 else None,
                "overdue": late > 0,
                "status": order.get_status_display(),
                "received_pct": int(received * 100 / ordered) if ordered else 0,
                "total_lkr": _money(order.total_lkr),
                "outstanding_lkr": _money(outstanding),
            }
        )
    rows.sort(key=lambda r: (not r["overdue"], r["delivery_date"] or date.max, r["label"]))
    return rows


# --- Goods received not invoiced -----------------------------------------------------------

GRNI_COLUMNS = [
    Column("grn", "GRN", width=1.2),
    Column("receipt_date", "Received", "date"),
    Column("division", "Division", width=0.6),
    Column("supplier", "Supplier", width=1.8),
    Column("po", "PO", width=1.2),
    Column("item", "Item", width=1.8),
    Column("quantity", "Not invoiced", "number", width=0.8),
    Column("unit", "Unit", width=0.5),
    Column("unit_cost", "PO price (LKR)", "money"),
    Column("value", "Value (LKR)", "money"),
]


def grni(user: User, *, division: str = "", supplier: str = "") -> list[dict]:
    lines = GoodsReceiptLine.objects.filter(
        receipt__in=_division(_grns(user), division),
        receipt__status=GoodsReceipt.Status.CONFIRMED,
        item__is_stock=True,
        inspection__status=IncomingInspection.Status.DECIDED,
    ).select_related(
        "receipt__supplier", "receipt__division", "receipt__purchase_order", "item", "po_line"
    )
    if supplier:
        lines = lines.filter(receipt__supplier_id=supplier)
    rows = []
    for line in lines.order_by("receipt__receipt_date", "receipt__number", "line_no"):
        left = invoices.accepted(line) - invoices.invoiced(line)
        if left <= 0:
            continue
        cost = unit_cost(line)
        rows.append(
            {
                "grn_id": line.receipt_id,
                "grn": line.receipt.number,
                "receipt_date": line.receipt.receipt_date,
                "division": line.receipt.division.code,
                "supplier": line.receipt.supplier.name,
                "po": line.receipt.purchase_order.label,
                "item": f"{line.item.code} {line.item.name}",
                "quantity": _qty(left),
                "unit": line.item.unit,
                "unit_cost": _money(cost.quantize(CENT, ROUND_HALF_UP)),
                "value": _money((left * cost).quantize(CENT, ROUND_HALF_UP)),
            }
        )
    return rows


def grni_ledger_balance(division: str = "") -> str:
    """The credit balance of the Goods received not invoiced account, to reconcile."""
    account = Account.objects.filter(system_role="grni").first()
    if account is None:
        return _money(ZERO)
    rows = JournalLine.objects.filter(account=account)
    if division:
        rows = rows.filter(division__code=division.upper())
    totals = rows.aggregate(debit=Sum("debit"), credit=Sum("credit"))
    return _money((totals["credit"] or ZERO) - (totals["debit"] or ZERO))


# --- Invoices held -------------------------------------------------------------------------

HELD_COLUMNS = [
    Column("number", "Our no.", width=1.1),
    Column("invoice_no", "Supplier's no.", width=1.1),
    Column("invoice_date", "Invoice date", "date"),
    Column("supplier", "Supplier", width=1.6),
    Column("division", "Division", width=0.6),
    Column("status", "Status", width=1.2),
    Column("days_held", "Days", "number", width=0.5),
    Column("differences", "Differences", width=3.5),
    Column("total", "Total", "money"),
]


def held_invoices(user: User, *, division: str = "") -> list[dict]:
    today = timezone.localdate()
    found = _division(
        invoices.visible(user).filter(
            status__in=(SupplierInvoice.Status.HELD, SupplierInvoice.Status.EXCEPTION_REQUESTED)
        ),
        division,
    )
    return [
        {
            "id": i.id,
            "number": i.number,
            "invoice_no": i.invoice_no,
            "invoice_date": i.invoice_date,
            "supplier": i.supplier.name,
            "division": i.division.code,
            "status": i.get_status_display(),
            "days_held": (today - timezone.localdate(i.created_at)).days,
            "differences": "\n".join(i.discrepancies),
            "total": _money(i.total_amount),
        }
        for i in found.order_by("invoice_date", "number")
    ]


# --- Exceptions approved --------------------------------------------------------------------

EXCEPTION_COLUMNS = [
    Column("approved_at", "Approved", "datetime"),
    Column("kind", "Exception", width=1.4),
    Column("document", "Document", width=1.3),
    Column("supplier", "Supplier", width=1.6),
    Column("division", "Division", width=0.6),
    Column("reason", "Reason given", width=2.4),
    Column("approved_by", "Approved by", width=1.2),
]

EXCEPTION_KINDS = {
    "goods_receipt": "GRN excess over the PO",
    "quality_deviation": "Accepted under QC deviation",
    "invoice_exception": "Invoice difference",
    "supplier_return": "Return of accepted goods",
}


def _approved(kind: str, start, end):
    states = ApprovalState.objects.filter(document_type=kind, status=ApprovalState.Status.APPROVED)
    for state in states:
        logs = list(
            ApprovalLog.objects.filter(document_type=kind, document_id=state.document_id)
            .select_related("user")
            .order_by("acted_at", "id")
        )
        approval = next((log for log in reversed(logs) if log.action == "approve"), None)
        asked = next((log for log in reversed(logs) if log.action == "submit"), None)
        if approval is None:
            continue
        day = timezone.localdate(approval.acted_at)
        if (start and day < start) or (end and day > end):
            continue
        yield state.document_id, approval, asked


def exceptions(user: User, *, start=None, end=None, division: str = "") -> list[dict]:
    if not effective_access(user).has("purchasing", "view"):
        return []
    scope = set(division_scope(user).values_list("code", flat=True))
    rows = []

    def add(kind, document_id, approval, asked, label, supplier, division_code, reason=None):
        if division_code not in scope or (division and division_code != division.upper()):
            return
        rows.append(
            {
                "approved_at": approval.acted_at,
                "kind": EXCEPTION_KINDS.get(kind, "Advance payment on a PO"),
                "document": label,
                "supplier": supplier,
                "division": division_code,
                "reason": reason if reason is not None else ((asked.reason if asked else "") or ""),
                "approved_by": approval.user.full_name,
            }
        )

    for doc_id, approval, asked in _approved("goods_receipt", start, end):
        grn = GoodsReceipt.objects.select_related("supplier", "division").filter(pk=doc_id).first()
        if grn:
            add(
                "goods_receipt",
                doc_id,
                approval,
                asked,
                grn.number,
                grn.supplier.name,
                grn.division.code,
            )
    for doc_id, approval, asked in _approved("quality_deviation", start, end):
        found = (
            IncomingInspection.objects.select_related(
                "line__receipt__supplier", "line__receipt__division", "line__item"
            )
            .filter(pk=doc_id)
            .first()
        )
        if found:
            grn = found.line.receipt
            add(
                "quality_deviation",
                doc_id,
                approval,
                asked,
                f"{grn.number} {found.line.item.code}",
                grn.supplier.name,
                grn.division.code,
            )
    for doc_id, approval, asked in _approved("invoice_exception", start, end):
        found = (
            SupplierInvoice.objects.select_related("supplier", "division").filter(pk=doc_id).first()
        )
        if found:
            add(
                "invoice_exception",
                doc_id,
                approval,
                asked,
                f"{found.number} ({found.invoice_no})",
                found.supplier.name,
                found.division.code,
            )
    for doc_id, approval, asked in _approved("supplier_return", start, end):
        found = (
            SupplierReturn.objects.select_related("supplier", "division").filter(pk=doc_id).first()
        )
        if found:
            add(
                "supplier_return",
                doc_id,
                approval,
                asked,
                found.number,
                found.supplier.name,
                found.division.code,
            )
    # Advances: approved with their voucher by the Director.
    from apps.vouchers.models import Voucher, VoucherLine

    advance_lines = (
        VoucherLine.objects.filter(advance_order__isnull=False)
        .exclude(
            voucher__status__in=(
                Voucher.Status.DRAFT,
                Voucher.Status.SUBMITTED,
                Voucher.Status.ACCOUNTANT_APPROVED,
                Voucher.Status.RETURNED,
                Voucher.Status.REJECTED,
                Voucher.Status.DELETED,
            )
        )
        .select_related("voucher__payee", "voucher__division", "advance_order")
    )
    for line in advance_lines:
        approval = (
            ApprovalLog.objects.filter(
                document_type="voucher", document_id=line.voucher_id, action="approve"
            )
            .select_related("user")
            .order_by("-acted_at", "-id")
            .first()
        )
        if approval is None:
            continue
        day = timezone.localdate(approval.acted_at)
        if (start and day < start) or (end and day > end):
            continue
        add(
            "advance",
            line.voucher_id,
            approval,
            None,
            f"{line.voucher.number} on {line.advance_order.label}",
            line.voucher.payee.name if line.voucher.payee else "",
            line.voucher.division.code,
            reason=line.description,
        )
    rows.sort(key=lambda r: r["approved_at"], reverse=True)
    return rows


# --- Receipts and rejections by supplier ----------------------------------------------------

SUPPLIER_COLUMNS = [
    Column("supplier", "Supplier", width=2),
    Column("grns", "GRNs", "number", width=0.5),
    Column("late", "Late deliveries", "number", width=0.7),
    Column("received_value", "Received (LKR)", "money"),
    Column("accepted_value", "Accepted (LKR)", "money"),
    Column("rejected_value", "Rejected or damaged (LKR)", "money"),
    Column("rejection_rate", "Rejected %", "number", width=0.7),
    Column("returned", "Returns", "number", width=0.6),
]


def by_supplier(user: User, *, start=None, end=None, division: str = "") -> list[dict]:
    grns = _division(_grns(user), division).filter(
        status__in=(GoodsReceipt.Status.CONFIRMED, GoodsReceipt.Status.REVERSAL_REQUESTED)
    )
    if start:
        grns = grns.filter(receipt_date__gte=start)
    if end:
        grns = grns.filter(receipt_date__lte=end)
    totals = defaultdict(
        lambda: {"grns": set(), "late": set(), "received": ZERO, "accepted": ZERO, "rejected": ZERO}
    )
    names = {}
    for line in GoodsReceiptLine.objects.filter(receipt__in=grns).select_related(
        "receipt__supplier", "receipt__purchase_order", "po_line"
    ):
        grn = line.receipt
        names[grn.supplier_id] = grn.supplier.name
        row = totals[grn.supplier_id]
        row["grns"].add(grn.pk)
        due = grn.purchase_order.delivery_date
        if due and grn.receipt_date > due:
            row["late"].add(grn.pk)
        cost = unit_cost(line)
        inspection = IncomingInspection.objects.filter(
            line=line, status=IncomingInspection.Status.DECIDED
        ).first()
        accepted = inspection.accepted_quantity if inspection else Decimal("0")
        rejected = (
            inspection.rejected_quantity if inspection else Decimal("0")
        ) + line.damaged_quantity
        row["received"] += line.received_quantity * cost
        row["accepted"] += accepted * cost
        row["rejected"] += rejected * cost
    returned = defaultdict(int)
    for ret in SupplierReturn.objects.filter(
        receipt__in=grns, status=SupplierReturn.Status.CONFIRMED
    ):
        returned[ret.supplier_id] += 1
    rows = []
    for supplier_id, row in totals.items():
        received = row["received"].quantize(CENT, ROUND_HALF_UP)
        rejected = row["rejected"].quantize(CENT, ROUND_HALF_UP)
        rows.append(
            {
                "supplier_id": supplier_id,
                "supplier": names[supplier_id],
                "grns": len(row["grns"]),
                "late": len(row["late"]),
                "received_value": _money(received),
                "accepted_value": _money(row["accepted"].quantize(CENT, ROUND_HALF_UP)),
                "rejected_value": _money(rejected),
                "rejection_rate": float((rejected * 100 / received).quantize(Decimal("0.1")))
                if received
                else 0,
                "returned": returned[supplier_id],
            }
        )
    rows.sort(key=lambda r: r["supplier"])
    return rows


# --- The trail of a purchase order ----------------------------------------------------------


def trail(user: User, order: PurchaseOrder) -> dict:
    """Everything that happened to a PO, from the order to the payment, both ways."""
    from apps.payments.models import SupplierPayment
    from apps.vouchers.models import VoucherLine

    grns = list(order.receipts.select_related("store").order_by("receipt_date", "number"))
    grn_lines = GoodsReceiptLine.objects.filter(receipt__purchase_order=order).select_related(
        "item", "receipt"
    )
    qc = []
    for line in grn_lines:
        found = IncomingInspection.objects.filter(line=line).first()
        if found and not found.automatic:
            qc.append(
                {
                    "id": found.id,
                    "grn": line.receipt.number,
                    "item": line.item.code,
                    "status": found.get_status_display(),
                    "decision": found.get_decision_display() if found.decision else "",
                    "accepted": _qty(found.accepted_quantity),
                    "rejected": _qty(found.rejected_quantity),
                }
            )
    bills = list(
        SupplierInvoice.objects.filter(lines__grn_line__receipt__purchase_order=order)
        .distinct()
        .order_by("invoice_date", "number")
    )
    voucher_lines = VoucherLine.objects.filter(
        Q(supplier_invoice__in=bills) | Q(advance_order=order)
    ).select_related("voucher")
    vouchers = {}
    for line in voucher_lines:
        v = line.voucher
        entry = vouchers.setdefault(
            v.pk,
            {
                "id": v.pk,
                "number": v.number,
                "status": v.get_status_display(),
                "amount": ZERO,
                "advance": False,
                "payments": [
                    {"number": p.number, "date": p.payment_date, "amount": _money(p.amount)}
                    for p in SupplierPayment.objects.filter(voucher=v).order_by(
                        "payment_date", "id"
                    )
                ],
            },
        )
        entry["amount"] += line.amount + line.tax_amount
        entry["advance"] = entry["advance"] or line.advance_order_id is not None
    for entry in vouchers.values():
        entry["amount"] = _money(entry["amount"])
    rets = SupplierReturn.objects.filter(receipt__purchase_order=order).order_by("number")
    return {
        "po": {
            "id": order.id,
            "label": order.label,
            "status": order.get_status_display(),
            "total_lkr": _money(order.total_lkr),
            "parent": None
            if order.parent_id is None
            else {"id": order.parent_id, "label": order.parent.label},
            "revisions": [{"id": r.id, "label": r.label} for r in order.revisions.all()],
        },
        "grns": [
            {
                "id": g.id,
                "number": g.number,
                "date": g.receipt_date,
                "status": g.get_status_display(),
            }
            for g in grns
        ],
        "inspections": qc,
        "invoices": [
            {
                "id": i.id,
                "number": i.number,
                "invoice_no": i.invoice_no,
                "status": i.get_status_display(),
                "total_lkr": _money(
                    i.total_lkr if i.status == SupplierInvoice.Status.POSTED else i.total_amount
                ),
                "unpaid": _money(invoices.unpaid(i)),
                "set_off": _money(advances.set_off_total(i)),
                "debited": _money(returns.debited(i)),
            }
            for i in bills
        ],
        "returns": [
            {
                "id": r.id,
                "number": r.number,
                "kind": r.get_kind_display(),
                "status": r.get_status_display(),
            }
            for r in rets
        ],
        "vouchers": sorted(vouchers.values(), key=lambda v: v["number"]),
    }


def order_of(*, grn: GoodsReceipt | None = None, invoice: SupplierInvoice | None = None):
    """The PO a GRN or an invoice belongs to (an invoice may bill several POs: the first)."""
    if grn is not None:
        return grn.purchase_order
    if invoice is not None:
        return (
            PurchaseOrder.objects.filter(receipts__lines__invoice_lines__invoice=invoice)
            .distinct()
            .order_by("number")
            .first()
        )
    return None


# --- Dashboard ------------------------------------------------------------------------------


def dashboard(user: User, division: str = "") -> dict:
    """Purchasing and stores figures for the home page; each opens the report it comes from."""
    division = (division or "").upper()
    open_rows = open_orders(user, division=division)
    waiting = 0
    for kind in (
        "purchase_order",
        "goods_receipt",
        "goods_receipt_reversal",
        "quality_deviation",
        "invoice_exception",
        "supplier_return",
    ):
        waiting += len(approvals.waiting_for(user, kind))
    grni_rows = grni(user, division=division)
    held = held_invoices(user, division=division)
    movements = StockMovement.objects.filter(
        division__in=division_scope(user), store__kind=Store.Kind.MAIN
    )
    if division:
        movements = movements.filter(division__code=division)
    stock_value = movements.aggregate(total=Sum("value"))["total"] or ZERO
    qc_waiting = inspections.queue(user).count() if inspections.can_view(user) else 0
    return {
        "open_orders": len(open_rows),
        "overdue": sum(1 for r in open_rows if r["overdue"]),
        "waiting_for_me": waiting,
        "qc_waiting": qc_waiting,
        "grni": {
            "count": len(grni_rows),
            "total": _money(sum((Decimal(r["value"]) for r in grni_rows), ZERO)),
        },
        "held_invoices": len(held),
        "stock_value": _money(stock_value),
    }
