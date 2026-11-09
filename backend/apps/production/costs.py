"""Order costs (backlog P3-16 part 1; spec 7.7 "Where each cost comes from").

Every job order and moulding production order collects its costs from what has been
approved, each as an `OrderCost` entry naming its source:

- **Material:** a job's issues by lot less returns (P3-11); a production order's backflush
  in each approved shift report, at the good pieces' material value less the regrind
  credit (P3-09).
- **Labour:** job card hours (less the machine's downtime in them) × the section's labour
  rate; for moulding, run hours × the people on the machine (manpower, at least 1) × it.
- **Machine time and overhead:** the same hours × the machine's (or section's) overhead
  rate per machine hour.
- **Setup and mould change:** a job card that includes the setup, up to the routing's setup
  minutes, at labour + overhead; for moulding, setup and mould change downtime, charged to
  the order run next on that machine.
- **Mould amortisation:** shots × the mould's rate per shot (company moulds).
- **Subcontract and direct expenses:** supplier bills coded to the order (approved or paid
  voucher lines not paying an invoice, posted supplier invoice lines of non-stock items);
  subcontract when the supplier was sent the job's parts.

Rates are those in force on the day (P3-05; rule 11); a section with no labour rate yet is
shown as not costed. Only approved shift reports count. **Entries are never changed**
(database): `sync` works out what each source should cost now and adds an adjusting entry
for any difference, e.g. when a shift report is corrected or a voucher cancelled. It runs
when costs are approved (issues, shift report approval and corrections, vouchers, supplier
invoices), and the Accountant can run it for every open order.

Rejects are shown separately: the cost already spent on the rejected pieces, as their share
of the order's cost so far.
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.models import User
from apps.inventory.models import StockIssue, StockIssueLine
from apps.purchasing.models import SupplierInvoice, SupplierInvoiceLine
from apps.vouchers.models import Voucher, VoucherLine

from . import rates
from .models import (
    DowntimeEntry,
    JobCardEntry,
    JobOrder,
    MouldingRun,
    OrderCost,
    ProductionOrder,
    ProductionReceipt,
    RejectEntry,
    ShiftReport,
)

E = OrderCost.Element
ZERO = Decimal("0")
CENT = Decimal("0.01")
HOUR = Decimal("3600")
APPROVED = ShiftReport.Status.APPROVED
PAID = (Voucher.Status.DIRECTOR_APPROVED, Voucher.Status.PARTLY_PAID, Voucher.Status.PAID)
SETUP_REASONS = ("SETUP", "MOULD-CHANGE")


def can_see(user: User) -> bool:
    access = effective_access(user)
    return access.has("job_profitability", "view") or access.has("accounting", "view")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def _hours(start, end) -> Decimal:
    return Decimal(str(max((end - start).total_seconds(), 0))) / HOUR


def _overlap_hours(start, end, stops) -> Decimal:
    total = ZERO
    for s, e in stops:
        total += _hours(max(s, start), min(e, end)) if min(e, end) > max(s, start) else ZERO
    return total


class _Want:
    """What each source of an order should cost now: {source: entry fields}."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.not_costed: set[str] = set()

    def add(self, source, element, day, amount, description, quantity=ZERO, unit="", rate=None):
        amount = _money(amount)
        if not amount:
            return
        self.rows[source] = {
            "element": element,
            "day": day,
            "amount": amount,
            "description": description[:200],
            "quantity": Decimal(quantity).quantize(Decimal("0.001"), ROUND_HALF_UP),
            "unit": unit,
            "rate": rate,
        }


# --- What each order should cost -----------------------------------------------------------------


def _bills(want: _Want, lines, invoice_lines, subcontractors: set[int]) -> None:
    for line in lines:
        v = line.voucher
        element = E.SUBCONTRACT if v.payee_id in subcontractors else E.DIRECT
        want.add(
            f"voucher_line:{line.pk}",
            element,
            v.voucher_date,
            line.amount,
            f"{v.number} line {line.line_no}: {(v.payee.name if v.payee_id else '')} "
            f"{line.description}".strip(),
        )
    for line in invoice_lines:
        i = line.invoice
        amount = line.amount * (i.exchange_rate or 1)
        element = E.SUBCONTRACT if i.supplier_id in subcontractors else E.DIRECT
        want.add(
            f"invoice_line:{line.pk}",
            element,
            i.invoice_date,
            amount,
            f"{i.number} line {line.line_no}: {i.supplier.name} {line.item.code}",
        )


def _voucher_lines(**order):
    return VoucherLine.objects.filter(
        voucher__status__in=PAID, supplier_invoice__isnull=True, **order
    ).select_related("voucher__payee")


def _invoice_lines(**order):
    return SupplierInvoiceLine.objects.filter(
        invoice__status=SupplierInvoice.Status.POSTED, item__is_stock=False, **order
    ).select_related("invoice__supplier", "item")


def _rates(section, machine, day) -> tuple[Decimal, Decimal, bool]:
    labour = rates.labour_on(section, day)
    return labour or ZERO, rates.overhead_on(section, machine, day), labour is None


def want_job(job: JobOrder) -> _Want:
    want = _Want()
    for line in (
        StockIssueLine.objects.filter(issue__job_link__job=job)
        .select_related("issue", "item")
        .order_by("id")
    ):
        sign = 1 if line.issue.kind == StockIssue.Kind.ISSUE else -1
        what = "issued" if sign > 0 else "returned"
        want.add(
            f"issue_line:{line.pk}",
            E.MATERIAL,
            line.issue.issue_date,
            sign * line.value,
            f"{line.issue.number} {line.item.code} {what}"
            + (f", lot {line.lot_no}" if line.lot_no else ""),
            sign * line.quantity,
            line.item.unit,
            line.unit_cost,
        )
    for e in JobCardEntry.objects.filter(job=job, report__status=APPROVED).select_related(
        "report", "machine__section", "operation"
    ):
        stops = [
            (d.started_at, d.ended_at)
            for d in DowntimeEntry.objects.filter(report=e.report, machine=e.machine)
        ]
        worked = _hours(e.started_at, e.ended_at) - _overlap_hours(e.started_at, e.ended_at, stops)
        worked = max(worked, ZERO)
        setup = min(e.operation.setup_min / 60, worked) if e.setup else ZERO
        run = worked - setup
        day = e.report.day
        labour, overhead, missing = _rates(e.machine.section, e.machine, day)
        if missing:
            want.not_costed.add(e.machine.section.code)
        where = f"{job.number} op {e.operation.seq} on {e.machine.code}, {day}"
        want.add(f"job_entry:{e.pk}:labour", E.LABOUR, day, run * labour, where, run, "h", labour)
        want.add(
            f"job_entry:{e.pk}:overhead", E.OVERHEAD, day, run * overhead, where, run, "h", overhead
        )
        want.add(
            f"job_entry:{e.pk}:setup",
            E.SETUP,
            day,
            setup * (labour + overhead),
            f"Setup, {where}",
            setup,
            "h",
            labour + overhead,
        )
    subcontractors = set(job.dispatches.values_list("supplier_id", flat=True))
    _bills(want, _voucher_lines(job=job), _invoice_lines(job=job), subcontractors)
    return want


def _people(report: ShiftReport, machine) -> int:
    on_machine = report.manpower.filter(machine=machine).aggregate(p=Sum("people"))["p"]
    return max(on_machine or 1, 1)


def want_order(order: ProductionOrder) -> _Want:
    want = _Want()
    for r in ProductionReceipt.objects.filter(
        order=order, undone=False, is_regrind=False, report__status=APPROVED
    ).select_related("report__section", "item"):
        want.add(
            f"receipt:{r.pk}",
            E.MATERIAL,
            r.report.day,
            r.value,
            f"Material for {r.quantity:,.0f} good {r.item.code}, shift report "
            f"{r.report.section.code} {r.report.day}",
            r.quantity,
            r.item.unit,
        )
    runs = MouldingRun.objects.filter(order=order, report__status=APPROVED).select_related(
        "report__shift", "report__section", "machine__section", "mould"
    )
    for run in runs:
        stops = [
            (d.started_at, d.ended_at)
            for d in DowntimeEntry.objects.filter(report=run.report, machine=run.machine)
        ]
        hours = max(
            _hours(run.started_at, run.ended_at)
            - _overlap_hours(run.started_at, run.ended_at, stops),
            ZERO,
        )
        day = run.report.day
        labour, overhead, missing = _rates(run.machine.section, run.machine, day)
        if missing:
            want.not_costed.add(run.machine.section.code)
        people = _people(run.report, run.machine)
        where = f"{run.machine.code} {day} {run.report.shift.code}"
        want.add(
            f"run:{run.pk}:labour",
            E.LABOUR,
            day,
            hours * people * labour,
            f"{people} on {where}",
            hours * people,
            "h",
            labour,
        )
        want.add(
            f"run:{run.pk}:overhead", E.OVERHEAD, day, hours * overhead, where, hours, "h", overhead
        )
        per_shot = rates.mould_on(run.mould, day)
        want.add(
            f"run:{run.pk}:mould",
            E.MOULD,
            day,
            run.shots * per_shot,
            f"Mould {run.mould.code}, {run.shots:,} shots",
            run.shots,
            "shots",
            per_shot,
        )
    # Setup and mould changes: charged to the order run next on the machine in the report.
    for d in (
        DowntimeEntry.objects.filter(
            reason__code__in=SETUP_REASONS, report__status=APPROVED, report__runs__order=order
        )
        .distinct()
        .select_related("report", "machine__section", "reason")
    ):
        if _setup_order(d) != order.pk:
            continue
        day = d.report.day
        labour, overhead, _ = _rates(d.machine.section, d.machine, day)
        hours = _hours(d.started_at, d.ended_at)
        people = _people(d.report, d.machine)
        rate = labour * people + overhead
        want.add(
            f"downtime:{d.pk}:setup",
            E.SETUP,
            day,
            hours * rate,
            f"{d.reason.name}, {d.machine.code} {day}",
            hours,
            "h",
            rate,
        )
    subcontractors: set[int] = set()
    _bills(
        want,
        _voucher_lines(production_order=order),
        _invoice_lines(production_order=order),
        subcontractors,
    )
    return want


def _setup_order(d: DowntimeEntry) -> int | None:
    """The production order a setup or mould change belongs to: the run on the machine that
    starts at or after it ends (else the one it falls in)."""
    runs = list(
        MouldingRun.objects.filter(report=d.report, machine=d.machine).order_by("started_at")
    )
    after = [r for r in runs if r.started_at >= d.started_at]
    found = after[0] if after else (runs[-1] if runs else None)
    return found.order_id if found else None


# --- Bringing the entries up to date -------------------------------------------------------------


def _entries(order) -> dict[str, dict]:
    """What the entries add up to now, per source."""
    rows = OrderCost.objects.filter(**_key(order)).values("source").annotate(total=Sum("amount"))
    return {r["source"]: r["total"] for r in rows}


def _key(order) -> dict:
    return {"job": order} if isinstance(order, JobOrder) else {"production_order": order}


def sync(order) -> int:
    """Add the entries and adjustments that bring the order's costs up to date; how many."""
    want = want_job(order) if isinstance(order, JobOrder) else want_order(order)
    with transaction.atomic():
        type(order).objects.select_for_update().filter(pk=order.pk).first()
        have = _entries(order)
        made = []
        today = timezone.localdate()
        for source, row in want.rows.items():
            gap = row["amount"] - have.get(source, ZERO)
            if not gap:
                continue
            fields = dict(row)
            earlier = source in have
            if earlier:
                before = (
                    OrderCost.objects.filter(**_key(order), source=source).aggregate(
                        q=Sum("quantity")
                    )["q"]
                    or ZERO
                )
                fields |= {
                    "amount": gap,
                    "quantity": row["quantity"] - before,
                    "day": today,
                    "description": f"Change: {row['description']}"[:200],
                }
            made.append(
                OrderCost(
                    **_key(order), division=order.division, source=source, adjusts=earlier, **fields
                )
            )
        for source, total in have.items():
            if source not in want.rows and total:
                last = OrderCost.objects.filter(**_key(order), source=source).last()
                made.append(
                    OrderCost(
                        **_key(order),
                        division=order.division,
                        source=source,
                        adjusts=True,
                        element=last.element,
                        day=today,
                        amount=-total,
                        quantity=-sum(
                            OrderCost.objects.filter(**_key(order), source=source).values_list(
                                "quantity", flat=True
                            ),
                            ZERO,
                        ),
                        unit=last.unit,
                        rate=last.rate,
                        description=f"Taken back: {last.description.removeprefix('Change: ')}"[
                            :200
                        ],
                    )
                )
        OrderCost.objects.bulk_create(made)
        return len(made)


def sync_later(*orders) -> None:
    """Sync once the current transaction has committed (so a failure never blocks the
    approval that caused it); the next sync catches up anyway."""
    seen = {(type(o).__name__, o.pk): o for o in orders if o is not None}

    def run():
        for order in seen.values():
            sync(type(order).objects.get(pk=order.pk))

    transaction.on_commit(run)


def for_report(report: ShiftReport) -> None:
    sync_later(
        *ProductionOrder.objects.filter(
            Q(moulding_runs__report=report) | Q(receipts__report=report)
        ).distinct(),
        *JobOrder.objects.filter(entries__report=report).distinct(),
    )


def for_voucher(voucher: Voucher) -> None:
    lines = voucher.lines.exclude(job__isnull=True, production_order__isnull=True)
    sync_later(*(line.job or line.production_order for line in lines))


def for_invoice(invoice: SupplierInvoice) -> None:
    lines = invoice.lines.exclude(job__isnull=True, production_order__isnull=True)
    sync_later(*(line.job or line.production_order for line in lines))


def sync_open(user: User | None = None) -> int:
    """Bring every open (or recently finished) order up to date: the Accountant's refresh
    and the month-end run."""
    made = 0
    for job in JobOrder.objects.exclude(
        status__in=[JobOrder.Status.DRAFT, JobOrder.Status.CANCELLED]
    ):
        made += sync(job)
    for order in ProductionOrder.objects.exclude(
        status__in=[ProductionOrder.Status.DRAFT, ProductionOrder.Status.CANCELLED]
    ):
        made += sync(order)
    return made


# --- Reading -------------------------------------------------------------------------------------


def _rejected(order) -> tuple[Decimal, Decimal]:
    """(good, rejected) pieces so far."""
    if isinstance(order, JobOrder):
        from . import job_cards

        steps = job_cards.flow(order)
        rejected = sum((s["rejected"] for s in steps), ZERO)
        good = steps[-1]["completed"] if steps else ZERO
        return good, rejected
    good = (
        order.receipts.filter(undone=False, item=order.item).aggregate(q=Sum("quantity"))["q"]
        or ZERO
    )
    rejected = Decimal(
        RejectEntry.objects.filter(run__order=order, run__report__status=APPROVED).aggregate(
            q=Sum("quantity")
        )["q"]
        or 0
    )
    return good, rejected


def summary(order, user: User) -> dict | None:
    if not can_see(user):
        return None
    entries = list(OrderCost.objects.filter(**_key(order)).order_by("day", "id"))
    by = defaultdict(lambda: ZERO)
    for e in entries:
        by[e.element] += e.amount
    total = sum(by.values(), ZERO)
    good, rejected = _rejected(order)
    made = good + rejected
    want = want_job(order) if isinstance(order, JobOrder) else want_order(order)
    return {
        "elements": [
            {"element": value, "label": label, "amount": str(_money(by[value]))}
            for value, label in E.choices
            if by[value]
        ],
        "total": str(_money(total)),
        "good": f"{good.normalize():f}" if good else "0",
        "rejected": f"{rejected.normalize():f}" if rejected else "0",
        "per_good": str(_money(total / good)) if good else "",
        "on_rejects": str(_money(total * rejected / made)) if made else "0.00",
        "not_costed": sorted(want.not_costed),
        "out_of_date": any(
            want.rows.get(s, {}).get("amount", ZERO) != t for s, t in _entries(order).items()
        )
        or any(s not in _entries(order) for s in want.rows),
        "entries": [
            {
                "id": e.pk,
                "day": e.day,
                "element": e.element,
                "description": e.description,
                "quantity": f"{e.quantity.normalize():f}" if e.quantity else "",
                "unit": e.unit,
                "rate": f"{e.rate.normalize():f}" if e.rate is not None else "",
                "amount": str(e.amount),
                "adjusts": e.adjusts,
            }
            for e in entries[-300:]
        ],
        "can_refresh": effective_access(user).has("accounting", "enter"),
    }
