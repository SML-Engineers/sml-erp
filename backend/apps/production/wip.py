"""Order costs in the ledger (backlog P3-16 part 2; spec 7.7 "Accounting").

Each batch of order cost entries (`costs.sync`) is posted as one journal:

- **Jobs that make a stock part** (for a sales order, or internal with a part; not mould
  making or repair, which P3-15 transfers): Dr **Work in progress** in the job's division
  until the job is completed. On completion its finished parts are received into the main
  store (lot = the job's number) at the job's Work in progress: Dr the part's inventory
  account (Finished goods), Cr Work in progress. A cost arriving later goes to the part's
  stock value if any is left, else to cost of sales. A job cancelled with costs on it, or
  completed with nothing finished, sends its Work in progress to cost of sales.
- **Moulding production orders** put their parts into stock every approved shift (P3-09) at
  their material value; their other costs (labour, machine time, overhead, setup and mould
  change, mould wear, bills) are added to the part's stock value as they are approved, or
  charged to cost of sales once none of it is left in stock.
- **The credit** goes back where the cost was first recorded: material to the account its
  issue was charged to (Raw materials used), a bill to the account the Accountant coded it
  to, and labour, machine time, overhead and mould wear to **Production costs absorbed into
  orders** (5090), against the salaries and expenses already in the books.
- Jobs without a stock part (tools, other internal work, moulds) keep their costs where they
  were booked: their entries are not posted.

The **month-end WIP report** sets the open jobs' Work in progress (from their entries) beside
the Work in progress account per division, shows any difference, and lists machine time
charged to no order (downtime other than setups charged to orders) at its overhead rate.
"""

import calendar
import logging
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account, JournalLine
from apps.accounting.services import AccountingError
from apps.core.models import Division, User
from apps.inventory import issues
from apps.inventory.models import StockIssueLine, StockMovement, Store
from apps.purchasing.models import SupplierInvoiceLine
from apps.vouchers.models import VoucherLine

from . import rates
from .models import (
    DowntimeEntry,
    JobCompletion,
    JobOrder,
    OrderCost,
    ProductionOrder,
    ShiftReport,
)

log = logging.getLogger(__name__)
L = OrderCost.Ledger
E = OrderCost.Element
ZERO = Decimal("0")
CENT = Decimal("0.01")
MOULD_JOBS = (JobOrder.Purpose.NEW_MOULD, JobOrder.Purpose.MOULD_REPAIR)


class WipError(Exception):
    pass


def _system(role: str, name: str) -> Account:
    account = Account.objects.filter(system_role=role, is_active=True).first()
    if account is None:
        raise WipError(f"The chart of accounts has no active {name} account.")
    return account


def in_ledger(order) -> bool:
    if isinstance(order, ProductionOrder):
        return True
    return bool(order.item_id) and order.purpose not in MOULD_JOBS


def _absorbed() -> Account:
    return _system("production_absorbed", "Production costs absorbed into orders")


def contra(order, entry: OrderCost) -> tuple[Account | None, Division]:
    """Where the cost was first booked, to credit it there: (account, division)."""
    kind, _, rest = entry.source.partition(":")
    pk = rest.split(":")[0]
    if kind == "issue_line":
        line = StockIssueLine.objects.select_related("item", "issue").filter(pk=pk).first()
        if line is not None:
            return issues.expense_account(line.item), line.issue.division
    if kind == "voucher_line":
        line = VoucherLine.objects.select_related("account").filter(pk=pk).first()
        if line is not None and line.account_id:
            return line.account, line.division or order.division
    if kind == "invoice_line":
        line = SupplierInvoiceLine.objects.select_related("item", "invoice").filter(pk=pk).first()
        if line is not None:
            return issues.expense_account(line.item), line.invoice.division
    if kind == "receipt":
        return None, order.division  # a moulding order's material: in its parts already
    return _absorbed(), order.division


def _on_hand(order) -> Decimal:
    return issues.main_totals(order.item)[0] if order.item_id else ZERO


def _target(order, entry: OrderCost) -> str:
    if not in_ledger(order):
        return L.NONE
    if isinstance(order, ProductionOrder):
        if entry.source.startswith("receipt:"):
            return L.NONE
        return L.FINISHED if _on_hand(order) > 0 else L.SOLD
    if not hasattr(order, "completion"):
        return L.WIP
    return L.FINISHED if _on_hand(order) > 0 else L.SOLD


def _debit_account(order, ledger: str) -> Account:
    if ledger == L.WIP:
        return _system("work_in_progress", "Work in progress")
    if ledger == L.FINISHED:
        try:
            return issues.inventory_account(order.item)
        except Exception:  # noqa: BLE001 - a part without its own account: the general one
            return _system("finished_goods", "Finished goods")
    return _system("finished_goods_sold", "Cost of finished goods sold")


def _main_store(order) -> Store | None:
    return Store.objects.filter(
        division=order.division, kind=Store.Kind.MAIN, is_active=True
    ).first()


def post_pending(order, user: User | None = None) -> None:
    """Post the order's entries not yet in the ledger, as one journal."""
    pending = list(OrderCost.objects.filter(**_key(order), ledger="").order_by("id"))
    if not pending:
        return
    user = user or order.created_by
    lines, moves, updates = [], [], []
    for entry in pending:
        ledger = _target(order, entry)
        account, division = (None, order.division)
        if ledger != L.NONE:
            account, division = contra(order, entry)
            if account is None:
                ledger = L.NONE
        updates.append((entry, ledger, account, division))
        if ledger == L.NONE or not entry.amount:
            continue
        debit = _debit_account(order, ledger)
        text = f"{_number(order)} {entry.get_element_display()}: {entry.description}"[:200]
        amount = abs(entry.amount)
        dr, cr = (debit, account) if entry.amount > 0 else (account, debit)
        dr_div, cr_div = (
            (order.division, division) if entry.amount > 0 else (division, order.division)
        )
        lines += [
            journal.Line(account=dr, debit=amount, division=dr_div, description=text),
            journal.Line(account=cr, credit=amount, division=cr_div, description=text),
        ]
        if ledger == L.FINISHED:
            moves.append(entry)
    entry_made = None
    if lines:
        try:
            entry_made = journal.post(
                user,
                entry_date=timezone.localdate(),
                narration=f"Order costs: {_number(order)}",
                lines=lines,
                source_type="order_cost",
                source_id=_number(order),
                max_lines=max(len(lines), 2),
            )
        except AccountingError as error:
            raise WipError(str(error)) from None
    store = _main_store(order) if moves else None
    for entry in moves:
        if store is None:
            break
        StockMovement.objects.create(
            item=order.item,
            store=store,
            division=order.division,
            lot_no=_number(order),
            kind=StockMovement.Kind.COSTED,
            movement_date=timezone.localdate(),
            quantity=0,
            value=entry.amount,
            journal_entry=entry_made,
            created_by=user,
        )
    for entry, ledger, account, division in updates:
        OrderCost.objects.filter(pk=entry.pk).update(
            ledger=ledger,
            credit_account=account,
            credit_division=division if ledger != L.NONE else None,
            journal_entry=entry_made if ledger != L.NONE and entry.amount else None,
        )


def _key(order) -> dict:
    return {"job": order} if isinstance(order, JobOrder) else {"production_order": order}


def _number(order) -> str:
    return order.number


# --- Jobs: completion and cancellation -----------------------------------------------------------


def wip_of(job: JobOrder) -> Decimal:
    """The job's Work in progress: entries posted there, less what its completion moved."""
    put = OrderCost.objects.filter(job=job, ledger=L.WIP).aggregate(t=Sum("amount"))["t"] or ZERO
    done = job.completion.value if hasattr(job, "completion") else ZERO
    return put - done


def finish(user: User, job: JobOrder, finished: Decimal) -> JobCompletion | None:
    """Move a completed (or cancelled) job's Work in progress out: its finished parts into the
    main store at that value, or, with nothing finished, to cost of sales."""
    from . import costs

    if not in_ledger(job) or hasattr(job, "completion"):
        return None
    costs.sync(job)  # everything approved so far, into Work in progress
    value = max(wip_of(job), ZERO)
    store = _main_store(job)
    if finished > 0 and store is None:
        raise WipError(f"Division {job.division.code} has no main store for the finished parts.")
    entry = movement = None
    if value:
        debit = _debit_account(job, L.FINISHED) if finished > 0 else _debit_account(job, L.SOLD)
        text = (
            f"{job.number}: {finished:,.3f} {job.item.code} finished"
            if finished > 0
            else f"{job.number}: nothing finished"
        )
        try:
            entry = journal.post(
                user,
                entry_date=timezone.localdate(),
                narration=f"Job {'completed' if finished > 0 else 'closed'}: {job.number}",
                lines=[
                    journal.Line(
                        account=debit, debit=value, division=job.division, description=text
                    ),
                    journal.Line(
                        account=_system("work_in_progress", "Work in progress"),
                        credit=value,
                        division=job.division,
                        description=text,
                    ),
                ],
                source_type="job_completion",
                source_id=job.number,
            )
        except AccountingError as error:
            raise WipError(str(error)) from None
    if finished > 0:
        movement = StockMovement.objects.create(
            item=job.item,
            store=store,
            division=job.division,
            lot_no=job.number,
            kind=StockMovement.Kind.PRODUCED,
            movement_date=timezone.localdate(),
            quantity=finished,
            value=value,
            journal_entry=entry,
            created_by=user,
        )
    return JobCompletion.objects.create(
        job=job, quantity=max(finished, ZERO), value=value, movement=movement, journal_entry=entry
    )


# --- The month-end WIP report --------------------------------------------------------------------


def _month(value) -> tuple[date, date]:
    try:
        year, month = (int(x) for x in str(value).split("-")[:2])
        start = date(year, month, 1)
    except (TypeError, ValueError):
        today = timezone.localdate()
        start = today.replace(day=1)
    return start, start.replace(day=calendar.monthrange(start.year, start.month)[1])


def report(month=None) -> dict:
    start, end = _month(month)
    wip = Account.objects.filter(system_role="work_in_progress").first()
    divisions = []
    for division in Division.objects.filter(is_active=True).order_by("code"):
        jobs = []
        for job in JobOrder.objects.filter(division=division).exclude(item__isnull=True):
            put = (
                OrderCost.objects.filter(
                    job=job, ledger=L.WIP, journal_entry__entry_date__lte=end
                ).aggregate(t=Sum("amount"))["t"]
                or ZERO
            )
            done = ZERO
            if hasattr(job, "completion") and job.completion.created_at.date() <= end:
                done = job.completion.value
            balance = put - done
            if balance:
                jobs.append(
                    {
                        "id": job.pk,
                        "number": job.number,
                        "description": job.description,
                        "status": job.get_status_display(),
                        "wip": str(balance),
                    }
                )
        orders = sum((Decimal(j["wip"]) for j in jobs), ZERO)
        ledger = ZERO
        if wip is not None:
            row = JournalLine.objects.filter(
                account=wip, division=division, entry__entry_date__lte=end
            ).aggregate(d=Sum("debit"), c=Sum("credit"))
            ledger = (row["d"] or ZERO) - (row["c"] or ZERO)
        if not jobs and not ledger:
            continue
        divisions.append(
            {
                "division": division.code,
                "jobs": jobs,
                "orders": str(orders),
                "ledger": str(ledger),
                "difference": str(ledger - orders),
            }
        )
    return {
        "month": start.strftime("%Y-%m"),
        "month_end": end,
        "divisions": divisions,
        "reconciled": all(Decimal(d["difference"]) == 0 for d in divisions),
        "unabsorbed": unabsorbed(start, end),
        "absorbed": absorbed(start, end),
    }


def absorbed(start: date, end: date) -> list[dict]:
    """Labour, machine time, overhead and mould wear charged to orders in the month."""
    rows = (
        OrderCost.objects.filter(day__gte=start, day__lte=end)
        .exclude(element__in=[E.MATERIAL, E.SUBCONTRACT, E.DIRECT])
        .values("division__code", "element")
        .annotate(t=Sum("amount"))
        .order_by("division__code", "element")
    )
    labels = dict(E.choices)
    return [
        {"division": r["division__code"], "element": labels[r["element"]], "amount": str(r["t"])}
        for r in rows
        if r["t"]
    ]


def unabsorbed(start: date, end: date) -> list[dict]:
    """Machine time charged to no order: downtime in approved shift reports (setups and mould
    changes charged to an order excepted), at the machine's overhead rate."""
    charged = {
        int(s.split(":")[1])
        for s in OrderCost.objects.filter(source__startswith="downtime:")
        .values("source")
        .annotate(t=Sum("amount"))
        .filter(t__gt=0)
        .values_list("source", flat=True)
    }
    out: dict[tuple, dict] = defaultdict(lambda: {"hours": ZERO, "amount": ZERO})
    for d in DowntimeEntry.objects.filter(
        report__status=ShiftReport.Status.APPROVED, report__day__gte=start, report__day__lte=end
    ).select_related("machine__section__division", "reason", "report"):
        if d.pk in charged:
            continue
        hours = Decimal(str((d.ended_at - d.started_at).total_seconds())) / 3600
        rate = rates.overhead_on(d.machine.section, d.machine, d.report.day)
        row = out[(d.machine.section.division.code, d.machine.code, d.reason.name)]
        row["hours"] += hours
        row["amount"] += hours * rate
    return [
        {
            "division": k[0],
            "machine": k[1],
            "reason": k[2],
            "hours": str(v["hours"].quantize(CENT, ROUND_HALF_UP)),
            "amount": str(v["amount"].quantize(CENT, ROUND_HALF_UP)),
        }
        for k, v in sorted(out.items())
    ]


def check(month_start: date) -> tuple[bool, str]:
    """The month-end checklist: open jobs' Work in progress agrees with the account."""
    found = report(month_start.strftime("%Y-%m"))
    if not found["divisions"]:
        return True, "No work in progress."
    if found["reconciled"]:
        total = sum((Decimal(d["ledger"]) for d in found["divisions"]), ZERO)
        return True, f"Work in progress {total:,.2f} agrees with the open jobs."
    off = [
        f"{d['division']} {Decimal(d['difference']):,.2f}"
        for d in found["divisions"]
        if Decimal(d["difference"])
    ]
    return False, "Differs: " + ", ".join(off) + " (Production → WIP report)."


def safe_sync(order) -> None:
    """Sync and post without stopping what triggered it; logged if it fails."""
    from . import costs

    try:
        with transaction.atomic():
            costs.sync(order)
    except Exception:  # noqa: BLE001 - the next sync or the Accountant's refresh catches up
        log.exception("Order costs of %s not brought up to date", order)
