"""Approving shift reports, and corrections (backlog P3-09; spec 7.4 controls).

**Approval.** A submitted moulding shift report waits for the Production Manager (approval
engine "shift_report"; never the person who submitted it). Returning it needs a reason; the
supervisor corrects it and submits again. Final approval, in one transaction:

1. **Backflush:** the materials of each run's production order (its copied BOM) leave the
   division's main store on one stock issue to the section, at their lot cost (weighted
   average): resin and masterbatch for everything moulded (good and rejected: shots ×
   cavities, or the shots for a family mould's BOM), without the BOM's reject allowance as
   the actual rejects are counted; packing and bought parts for the good pieces only. The
   run's material batch is used for its material. Customer-supplied material and services
   are not taken from stock. Dr Raw materials used, Cr inventory.
2. **Regrind** made goes into the main store (lot "RG" + the report) at its credit value
   (P3-05: 100% of the material's cost unless the Accountant set one).
3. **Good pieces** go into the main store (lot = the production order's number), valued at
   the material they used less their share of the regrind credit (labour and overhead are
   added by order costing, P3-16). A family mould's other parts are counted too (shots × their
   cavities), sharing the run's value by their weight. Dr finished goods inventory and Dr
   the regrind's inventory, Cr Raw materials used.
4. Each **mould's shot count** goes up by its shots; the Production Manager is told when a
   mould approaches or reaches its preventive maintenance (P3-10).

The supervisor's own material issue and return lines are kept as a record next to the
backflush (the consumption report compares them, P3-20).

**Corrections.** After the entry time (shift + grace period) a supervisor of the section
asks for a correction of a draft or an approved report, with a reason; the report as it
stood is kept with the request. The Production Manager, the Director, or a person the Admin
gives "approve_production_corrections" (the Director confirming) approves it, never the
person who asked (engine "shift_correction"). Approving reopens a draft for one more grace
period; for an approved report it reverses everything approval posted (journals, stock and
shot counts) and returns the report to the supervisor, to correct and submit again.
"""

from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.inventory import issues
from apps.inventory import items as item_master
from apps.inventory.models import Item, StockMovement
from apps.inventory.stock import StockError, _store

from . import costs, maintenance, rates, shift_reports
from .models import (
    BomLine,
    Mould,
    ProductionReceipt,
    ShiftCorrection,
    ShiftReport,
)
from .shift_reports import ShiftReportError

DOC = "shift_report"
FIX = "shift_correction"
St = ShiftReport.Status
T = BomLine.Type
ZERO = Decimal("0")
CENT = Decimal("0.01")
QTY = Decimal("0.001")
K = StockMovement.Kind
MOULDED = (T.RAW, T.MASTERBATCH)  # used for every piece moulded, good or rejected
FOR_GOOD = (T.PACKING, T.BOUGHT, T.SUB_ASSEMBLY)  # used for good pieces only


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


# --- Sending for approval ------------------------------------------------------------------------


def send(user: User, report: ShiftReport) -> None:
    """Called when the supervisor submits: the report waits for the Production Manager."""
    try:
        approvals.submit(
            user,
            DOC,
            report.pk,
            created_by=user,
            division=report.section.division,
            title=f"Work shift report {report.section.code} {report.day} {report.shift.name}",
            link=f"/shift-report?report={report.pk}",
        )
    except ApprovalError as error:
        raise ShiftReportError(str(error)) from None


def can_decide(user: User, report: ShiftReport) -> bool:
    state = approvals.state_of(DOC, report.pk)
    return (
        report.status == St.SUBMITTED and state is not None and not approvals.why_not(user, state)
    )


# --- Working out the backflush -------------------------------------------------------------------


def _factor(run) -> tuple[Decimal, Decimal]:
    """BOM base quantities for what the run moulded, and the share of it that is good."""
    order = run.order
    made = run.shots * run.cavities
    family = order.bom.outputs.count() > 1
    moulded = Decimal(run.shots if family else made) / order.bom.base_quantity
    good = run.good_quantity / made if made else ZERO
    return moulded, good


def _needs(report: ShiftReport) -> dict[int, list[tuple]]:
    """Per run: (item, lot, quantity) of the materials it used."""
    out: dict[int, list[tuple]] = {}
    for run in report.runs.select_related("order__bom", "material"):
        moulded, good = _factor(run)
        # The BOM's resin includes the reject allowance; the actual rejects are counted here.
        allowance = 1 + run.order.bom.reject_pct / 100
        rows = []
        for line in run.order.bom_lines.select_related("component"):
            if line.component is None or line.customer_supplied:
                continue
            if line.line_type in MOULDED:
                quantity = line.per_base * moulded / allowance
            elif line.line_type in FOR_GOOD:
                quantity = line.per_base * moulded * good
            else:
                continue
            quantity = quantity.quantize(QTY, ROUND_HALF_UP)
            if quantity <= 0:
                continue
            lot = run.material_lot if run.material_id == line.component_id else ""
            rows.append((line.component, lot, quantity, line.line_type))
        out[run.pk] = rows
    return out


def _outputs(run) -> list[tuple[Item, Decimal, Decimal]]:
    """(item, good quantity, weight share) of what the run made."""
    outputs = list(run.order.bom.outputs.select_related("item"))
    if len(outputs) < 2:
        return [(run.order.item, run.good_quantity, Decimal(1))]
    weights = {o.item_id: o.cavities * (o.part_weight_g or Decimal(1)) for o in outputs}
    total = sum(weights.values(), ZERO) or Decimal(1)
    rows = []
    for o in outputs:
        quantity = (
            run.good_quantity if o.item_id == run.order.item_id else Decimal(run.shots * o.cavities)
        )
        rows.append((o.item, quantity, weights[o.item_id] / total))
    return rows


# --- Deciding ------------------------------------------------------------------------------------


def decide(user: User, report: ShiftReport, action: str, reason: str = "") -> ShiftReport:
    reason = " ".join((reason or "").split())
    with transaction.atomic():
        report = (
            ShiftReport.objects.select_for_update()
            .select_related("section__division", "shift")
            .get(pk=report.pk)
        )
        if report.status != St.SUBMITTED:
            raise ShiftReportError("This report is not waiting for approval.")
        try:
            if action == "approve":
                state = approvals.approve(user, DOC, report.pk, reason)
                if state.status == ApprovalState.Status.APPROVED:
                    _post(user, report)
            elif action == "send_back":
                approvals.send_back(user, DOC, report.pk, reason)
                with audit_context("shift_report_returned", reason):
                    report.status = St.RETURNED
                    report.return_reason = reason[:300]
                    report.save(update_fields=["status", "return_reason"])
            else:
                raise ShiftReportError("Unknown action.")
        except ApprovalError as error:
            raise ShiftReportError(str(error)) from None
        return report


def _post(user: User, report: ShiftReport) -> None:
    division = report.section.division
    try:
        store = _store(division, "main")
    except StockError as error:
        raise ShiftReportError(str(error)) from None
    needs = _needs(report)
    runs = {r.pk: r for r in report.runs.select_related("order__item", "order__bom", "mould")}
    with audit_context("shift_report_approved", f"{report.section.code} {report.day}"):
        # 1. Backflush, one issue for the whole shift.
        grouped: dict[tuple, Decimal] = defaultdict(lambda: ZERO)
        for rows in needs.values():
            for item, lot, quantity, _ in rows:
                grouped[(item.pk, lot)] += quantity
        items = {item.pk: item for rows in needs.values() for item, *_ in rows}
        document = None
        unit_value: dict[int, Decimal] = {}
        if grouped:
            try:
                document = issues.issue_for(
                    user,
                    store=store,
                    issue_date=report.day,
                    section=report.section,
                    purpose=f"Backflush, shift report {report.section.code} {report.day} "
                    f"{report.shift.name}",
                    lines=[
                        issues.IssueLine(item=items[pk], quantity=q, lot_no=lot)
                        for (pk, lot), q in grouped.items()
                    ],
                )
            except StockError as error:
                raise ShiftReportError(f"Backflush: {error}") from None
            totals = document.lines.values("item").annotate(q=Sum("quantity"), v=Sum("value"))
            unit_value = {t["item"]: t["v"] / t["q"] for t in totals if t["q"]}
        # Each run's material value, and its value in resin and masterbatch.
        value = {}
        moulded_value = {}
        for pk, rows in needs.items():
            value[pk] = sum((q * unit_value.get(i.pk, ZERO) for i, _, q, _ in rows), ZERO)
            moulded_value[pk] = sum(
                (q * unit_value.get(i.pk, ZERO) for i, _, q, kind in rows if kind in MOULDED),
                ZERO,
            )
        # 2. Regrind at its credit value, shared by the runs' resin value.
        regrind = []
        for m in report.materials.filter(kind="regrind").select_related("item"):
            per_kg = rates.regrind_on(m.item, report.day)["per_kg"] or ZERO
            kg = m.quantity / 1000 if m.item.unit == Item.Unit.G else m.quantity
            regrind.append((m.item, m.quantity, _money(per_kg * kg)))
        credit = sum((c for *_, c in regrind), ZERO)
        base = sum(moulded_value.values(), ZERO)
        # 3. Good pieces at their material value less their share of the credit.
        receipts = []
        for pk, run in runs.items():
            share = credit * moulded_value[pk] / base if base else ZERO
            for item, quantity, weight in _outputs(run):
                material = _money(value[pk] * weight)
                less = _money(share * weight)
                receipts.append(
                    ProductionReceipt(
                        report=report,
                        run=run,
                        order=run.order,
                        item=item,
                        quantity=quantity,
                        material_value=material,
                        regrind_credit=less,
                        value=max(material - less, ZERO),
                    )
                )
        for item, quantity, value_in in regrind:
            receipts.append(
                ProductionReceipt(
                    report=report,
                    item=item,
                    is_regrind=True,
                    quantity=quantity,
                    material_value=value_in,
                    value=value_in,
                )
            )
        entry = _receipt_entry(user, report, receipts)
        for r in receipts:
            if r.quantity > 0:
                r.movement = StockMovement.objects.create(
                    item=r.item,
                    store=store,
                    division=division,
                    lot_no=f"RG{report.pk:06d}" if r.is_regrind else r.order.number,
                    kind=K.REGRIND if r.is_regrind else K.PRODUCED,
                    movement_date=report.day,
                    quantity=r.quantity,
                    value=r.value,
                    journal_entry=entry if r.value else None,
                    created_by=user,
                )
                item_master.mark_used(r.item)
            r.save()
        # 4. Mould shot counts.
        shots = defaultdict(int)
        for run in runs.values():
            shots[run.mould_id] += run.shots
        now = timezone.now()
        for mould_id, count in shots.items():
            Mould.objects.filter(pk=mould_id).update(shot_count=F("shot_count") + count)
            Mould.objects.filter(pk=mould_id, first_used_at__isnull=True).update(first_used_at=now)
        maintenance.after_shots(shots)  # P3-10: tell the Production Manager when due
        report.status = St.APPROVED
        report.approved_by = user
        report.approved_at = now
        report.return_reason = ""
        report.stock_issue = document
        report.receipt_entry = entry
        report.save()
        costs.for_report(report)  # P3-16: the orders' costs


def _receipt_entry(user, report, receipts):
    lines = []
    division = report.section.division
    total = ZERO
    try:
        for r in receipts:
            if not r.value:
                continue
            text = (
                f"Regrind {r.item.code} {r.quantity:,.3f} {r.item.unit}"
                if r.is_regrind
                else f"{r.order.number} {r.item.code} × {r.quantity:,.3f}"
            )
            lines.append(
                journal.Line(
                    account=issues.inventory_account(r.item),
                    debit=r.value,
                    division=division,
                    description=text,
                )
            )
            total += r.value
    except StockError as error:
        raise ShiftReportError(str(error)) from None
    if not total:
        return None
    lines.append(
        journal.Line(
            account=issues.system_account("materials_used", "Raw materials used"),
            credit=total,
            division=division,
            description="Production and regrind into stock",
        )
    )
    try:
        return journal.post(
            user,
            entry_date=report.day,
            narration=f"Production into stock, shift report {report.section.code} {report.day} "
            f"{report.shift.name}",
            lines=lines,
            source_type="shift_report",
            source_id=str(report.pk),
        )
    except AccountingError as error:
        raise ShiftReportError(str(error)) from None


# --- Corrections ---------------------------------------------------------------------------------


def can_ask(user: User, report: ShiftReport) -> bool:
    if not shift_reports.can_enter(user):
        return False
    if not shift_reports.sections(user).filter(pk=report.section_id).exists():
        return False
    if report.corrections.filter(status=ShiftCorrection.Status.AWAITING).exists():
        return False
    if report.status == St.APPROVED:
        return True
    return report.status == St.DRAFT and not shift_reports.is_open(report)


def ask(user: User, report: ShiftReport, reason: str) -> ShiftCorrection:
    reason = " ".join((reason or "").split())[:300]
    if not reason:
        raise ShiftReportError("Say what needs correcting.")
    report = ShiftReport.objects.select_related("section", "shift").get(pk=report.pk)
    if not can_ask(user, report):
        raise ShiftReportError(
            "A supervisor of the section asks for a correction of a draft whose entry time is "
            "over or of an approved report, one at a time."
        )
    original = shift_reports.payload(report, user)
    original.pop("options", None)
    original.pop("editable", None)
    with audit_context("shift_correction_asked", reason), transaction.atomic():
        fix = ShiftCorrection.objects.create(
            report=report,
            reason=reason,
            original=_plain(original),
            requested_by=user,
        )
        try:
            approvals.submit(
                user,
                FIX,
                fix.pk,
                created_by=user,
                division=report.section.division,
                title=f"Correction: work shift report {report.section.code} {report.day}",
                link=f"/shift-report?report={report.pk}",
                comment=reason,
            )
        except ApprovalError as error:
            raise ShiftReportError(str(error)) from None
        return fix


def _plain(value):
    """JSON-ready copy of a payload (dates and times as text)."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def can_decide_fix(user: User, fix: ShiftCorrection) -> bool:
    state = approvals.state_of(FIX, fix.pk)
    return (
        fix.status == ShiftCorrection.Status.AWAITING
        and state is not None
        and not approvals.why_not(user, state)
    )


def decide_fix(user: User, fix: ShiftCorrection, action: str, reason: str = "") -> ShiftCorrection:
    reason = " ".join((reason or "").split())
    with transaction.atomic():
        fix = ShiftCorrection.objects.select_for_update().get(pk=fix.pk)
        if fix.status != ShiftCorrection.Status.AWAITING:
            raise ShiftReportError("This correction is not waiting for approval.")
        try:
            if action == "approve":
                state = approvals.approve(user, FIX, fix.pk, reason)
                if state.status != ApprovalState.Status.APPROVED:
                    return fix
                _apply(user, fix)
                fix.status = ShiftCorrection.Status.APPROVED
            elif action == "reject":
                approvals.reject(user, FIX, fix.pk, reason)
                fix.status = ShiftCorrection.Status.REJECTED
            else:
                raise ShiftReportError("Unknown action.")
        except ApprovalError as error:
            raise ShiftReportError(str(error)) from None
        fix.decided_at = timezone.now()
        fix.save(update_fields=["status", "decided_at"])
        return fix


def _apply(user: User, fix: ShiftCorrection) -> None:
    report = (
        ShiftReport.objects.select_for_update()
        .select_related("section__division", "shift")
        .get(pk=fix.report_id)
    )
    with audit_context("shift_correction_applied", fix.reason):
        if report.status == St.DRAFT:
            grace = shift_reports.setting_on(report.day).grace_hours
            report.reopened_until = timezone.now() + timedelta(hours=float(grace))
            report.save(update_fields=["reopened_until"])
            return
        if report.status != St.APPROVED:
            raise ShiftReportError("The report is no longer approved or a draft.")
        _undo(user, report, fix.reason)
        costs.for_report(report)
        try:
            approvals.reopen(user, DOC, report.pk, f"Correction approved: {fix.reason}")
        except ApprovalError as error:
            raise ShiftReportError(str(error)) from None
        report.status = St.RETURNED
        report.return_reason = f"Correction: {fix.reason}"[:300]
        report.save(update_fields=["status", "return_reason"])


def _undo(user: User, report: ShiftReport, reason: str) -> None:
    """Reverse everything approval posted: journals, stock and mould shot counts."""
    entries = {}
    try:
        issued = report.stock_issue.journal_entry if report.stock_issue_id else None
        for entry in (issued, report.receipt_entry):
            if entry is not None:
                entries[entry.pk] = journal.reverse(
                    user, entry, reason=f"Shift report correction: {reason}"
                )
    except AccountingError as error:
        raise ShiftReportError(str(error)) from None
    taken = (
        list(StockMovement.objects.filter(issue_line__issue=report.stock_issue))
        if report.stock_issue_id
        else []
    )
    put = [
        r.movement
        for r in report.receipts.filter(undone=False, movement__isnull=False).select_related(
            "movement__item", "movement__store"
        )
    ]
    for m in taken + put:
        if m.quantity > 0:
            left = (
                StockMovement.objects.filter(item=m.item, store=m.store, lot_no=m.lot_no).aggregate(
                    q=Sum("quantity")
                )["q"]
                or ZERO
            )
            if left < m.quantity:
                raise ShiftReportError(
                    f"{m.item.code} lot {m.lot_no} has only {left:,.3f} left of the "
                    f"{m.quantity:,.3f} the report put in: it has been used or delivered."
                )
        StockMovement.objects.create(
            item=m.item,
            store=m.store,
            division=m.division,
            lot_no=m.lot_no,
            kind=K.UNDONE,
            movement_date=timezone.localdate(),
            quantity=-m.quantity,
            value=-m.value,
            journal_entry=entries.get(m.journal_entry_id) if m.journal_entry_id else None,
            created_by=user,
        )
    shots = defaultdict(int)
    for run in report.runs.all():
        shots[run.mould_id] += run.shots
    for mould_id, count in shots.items():
        mould = Mould.objects.select_for_update().get(pk=mould_id)
        if mould.shot_count - count < mould.shots_at_last_pm:
            raise ShiftReportError(
                f"Mould {mould.code} has had maintenance since: its shot count cannot go back."
            )
        Mould.objects.filter(pk=mould_id).update(shot_count=F("shot_count") - count)
    report.receipts.filter(undone=False).update(undone=True)


# --- Reading -------------------------------------------------------------------------------------


def approval_fields(report: ShiftReport, user: User) -> dict:
    """What the report page adds for approval and corrections."""
    fixes = list(report.corrections.select_related("requested_by"))
    receipts = report.receipts.select_related("item", "order")
    return {
        "return_reason": report.return_reason,
        "approved_by": report.approved_by.full_name if report.approved_by_id else "",
        "approved_at": report.approved_at,
        "stock_issue": report.stock_issue.number if report.stock_issue_id else "",
        "receipts": [
            {
                "order": r.order.number if r.order_id else "",
                "item": r.item.code,
                "is_regrind": r.is_regrind,
                "quantity": f"{r.quantity.normalize():f}" if r.quantity else "0",
                "material_value": f"{r.material_value:.2f}",
                "regrind_credit": f"{r.regrind_credit:.2f}",
                "value": f"{r.value:.2f}",
                "undone": r.undone,
            }
            for r in receipts
        ],
        "corrections": [
            {
                "id": f.pk,
                "reason": f.reason,
                "status": f.status,
                "status_label": f.get_status_display(),
                "requested_by": f.requested_by.full_name,
                "requested_at": f.requested_at,
                "can_decide": can_decide_fix(user, f),
            }
            for f in fixes
        ],
        "can_decide": can_decide(user, report),
        "can_ask": can_ask(user, report),
        "reopened_until": report.reopened_until,
    }
