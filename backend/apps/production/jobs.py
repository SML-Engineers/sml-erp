"""Machining job orders and their material (backlog P3-11; spec 7.2, 7.7, 7.1B).

- A **job order** makes a part for a sales order line (part, drawing number and revision,
  quantity, due date), or is an **internal job**: mould making, a mould repair (of a mould
  in the register), tools and fixtures, or other work. Numbered from the number series
  ("JO"). The Production Planner (production planning, Enter) makes, releases, completes and
  closes jobs. The jobs and production orders of a sales line never add up to more than its
  quantity.
- When a job is made, the **approved routing and BOM** of its part are copied to it; while
  it is a draft the Planner may change its operations and materials for this job (or enter
  them, for a job without a routing). On release they are fixed (database).
- **Material issue:** the stores person issues material to a released job from a main store
  of its division, by lot (oldest first unless a lot is chosen), posted as any issue
  (P2-18). Each material may be issued up to its quantity per piece × the job's quantity,
  less what came back. **More** (or a material not on the job) needs a request with a
  reason, approved by the Production Manager (approval engine, "job_excess"); the approved
  quantity is then added to what may be issued.
- **Returns:** material not used comes back against its issue, into the same store and lot,
  at the cost it went out at, and is credited to the job (so it may be issued again).
- Statuses Draft → Released → Completed → Closed, or Cancelled (with a reason) before
  completion. Jobs are never deleted and only move forward (database).
"""

from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, QuerySet, Sum
from django.utils import timezone

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.inventory import issues
from apps.inventory.models import Item, StockIssue, StockIssueLine, StockMovement, Store
from apps.inventory.stock import StockError
from apps.masters.models import Supplier
from apps.sales.models import SalesOrderLine

from . import job_cards, orders, routings, subcontract
from .models import (
    Bom,
    BomLine,
    JobExcess,
    JobIssue,
    JobMaterial,
    JobOperation,
    JobOrder,
    Mould,
)
from .routings import RoutingError

DOC = "job_order"
EXCESS = "job_excess"
St = JobOrder.Status
P = JobOrder.Purpose
T = BomLine.Type
ZERO = Decimal("0")
QTY = Decimal("0.001")
PER = Decimal("0.000001")
OPEN = (St.DRAFT, St.RELEASED)
MAX_LINES = 100


class JobError(Exception):
    pass


def can_plan(user: User) -> bool:
    return effective_access(user).has("production_planning", "enter")


def can_issue(user: User) -> bool:
    return issues.can_issue(user)


def _check(user: User) -> None:
    if not can_plan(user):
        raise JobError("Only the Production Planner makes and changes job orders.")


def visible(user: User) -> QuerySet[JobOrder]:
    return JobOrder.objects.filter(division__in=division_scope(user)).select_related(
        "item", "division", "mould", "sales_line__order__customer", "created_by", "routing", "bom"
    )


def _fresh(job: JobOrder) -> JobOrder:
    return JobOrder.objects.select_for_update().get(pk=job.pk)


# --- Values --------------------------------------------------------------------------------------


def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def _decimal(value, label: str, places: int, *, blank_ok: bool = False) -> Decimal | None:
    text = _text(value).replace(",", "")
    if not text and blank_ok:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise JobError(f"Give the {label}.") from None
    if not number.is_finite() or number <= 0 or number >= Decimal("1e12"):
        raise JobError(f"The {label} is more than 0.")
    if number != number.quantize(Decimal(1).scaleb(-places)):
        raise JobError(f"The {label} has at most {places} decimal places.")
    return number


def _date(value, label: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(_text(value))
    except ValueError:
        raise JobError(f"Give the {label}, e.g. 2026-12-01.") from None


def _n(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value.normalize():f}" if value else "0"


def _item(code, *, finished: bool) -> Item:
    code = _text(code).upper()
    item = Item.objects.filter(code=code).first()
    if item is None:
        raise JobError(f"There is no item {code or '(blank)'}.")
    if not item.is_active:
        raise JobError(f"{item.code} is not active.")
    if finished and item.category != Item.Category.FINISHED:
        raise JobError(f"{item.code} is not a finished part.")
    return item


def _sales_line(user: User, value) -> SalesOrderLine:
    try:
        pk = int(_text(value))
    except ValueError:
        raise JobError("Choose the sales order line.") from None
    line = (
        SalesOrderLine.objects.select_related("order", "order__division")
        .filter(pk=pk, order__division__in=division_scope(user))
        .first()
    )
    if line is None:
        raise JobError("Choose the sales order line.")
    if line.order.status not in orders.SALES_OPEN:
        raise JobError(f"Sales order {line.order.number} is not open.")
    if line.is_tooling:
        raise JobError("A tooling line is made as a mould making job (internal).")
    return line


def _division(user: User, value) -> Division:
    code = _text(value).upper()
    division = division_scope(user).filter(code=code).first() if code else None
    if division is None:
        raise JobError("Choose the division that does the work.")
    return division


def in_force_bom(item: Item) -> Bom | None:
    """The item's approved BOM for machining (a moulding BOM is for production orders)."""
    return (
        Bom.objects.filter(item=item, status=Bom.Status.APPROVED)
        .exclude(kind=Bom.Kind.MOULDING)
        .first()
    )


def _fields(user: User, values: dict, current: JobOrder | None) -> dict:
    def get(key, default=""):
        if key in values:
            return values[key]
        return getattr(current, key) if current is not None else default

    purpose = _text(get("purpose", P.SALES)).lower()
    if purpose not in P.values:
        raise JobError("Say what the job is for: a sales order, a mould, tools or other work.")
    line = mould = None
    item_value = values.get("item", current.item.code if current and current.item_id else "")
    if purpose == P.SALES:
        line = _sales_line(user, values.get("sales_line", current.sales_line_id if current else ""))
        division = line.order.division
        item = _item(item_value, finished=True)
    else:
        division = _division(user, values.get("division", current.division.code if current else ""))
        item = _item(item_value, finished=False) if _text(item_value) else None
        mould_code = _text(
            values.get("mould", current.mould.code if current and current.mould_id else "")
        ).upper()
        if mould_code:
            mould = Mould.objects.filter(code=mould_code).first()
            if mould is None:
                raise JobError(f"There is no mould {mould_code}.")
            if mould.status == Mould.Status.RETIRED:
                raise JobError(f"Mould {mould.code} is retired.")
        if purpose == P.MOULD_REPAIR and mould is None:
            raise JobError("Choose the mould to repair.")
    if current is not None and division.pk != current.division_id:
        raise JobError("A job keeps its division: cancel it and make a new one.")
    quantity = _decimal(get("quantity"), "quantity", 3)
    if line is not None:
        left = line.quantity - orders.planned_for(line, but_job=current)
        if quantity > left:
            raise JobError(
                f"Sales order {line.order.number} line {line.line_no} has {_n(max(left, ZERO))} "
                f"{line.unit} left to make."
            )
    description = _text(values.get("description", current.description if current else ""))[:200]
    if not description:
        description = (line.description if line else (item.name if item else ""))[:200]
    if not description:
        raise JobError("Describe the job, e.g. New mould for the 38 mm cap.")
    drawing_no = _text(values.get("drawing_no", current.drawing_no if current else ""))[:50]
    if not drawing_no and line is not None:
        drawing_no = line.drawing_no
    return {
        "purpose": purpose,
        "sales_line": line,
        "division": division,
        "item": item,
        "mould": mould,
        "description": description,
        "drawing_no": drawing_no,
        "drawing_revision": _text(get("drawing_revision"))[:20],
        "quantity": quantity,
        "due_date": _date(get("due_date"), "due date"),
        "notes": str(values.get("notes", current.notes if current else ""))[:2000],
    }


# --- Operations and materials --------------------------------------------------------------------


def _operations(user: User, rows) -> list[dict]:
    if not rows:
        return []
    if len(rows) > MAX_LINES:
        raise JobError(f"A job has at most {MAX_LINES} operations.")
    try:
        return routings._operations(user, rows)
    except RoutingError as error:
        raise JobError(str(error)) from None


def _materials(rows) -> list[dict]:
    if len(rows or []) > MAX_LINES:
        raise JobError(f"A job has at most {MAX_LINES} materials.")
    out, seqs = [], set()
    for n, row in enumerate(rows or [], start=1):
        where = f"Material {n}"
        try:
            seq = int(_text(row.get("seq")) or n * 10)
        except ValueError:
            raise JobError(f"{where}: the line number is a whole number.") from None
        if not 1 <= seq <= 9999 or seq in seqs:
            raise JobError(f"{where}: the line numbers are 1 to 9999, each once.")
        seqs.add(seq)
        where = f"Material {seq}"
        line_type = _text(row.get("line_type") or T.RAW).lower()
        if line_type not in T.values:
            raise JobError(f"{where}: choose the type.")
        component = supplier = None
        if line_type == T.SUBCONTRACT:
            code = _text(row.get("supplier")).upper()
            supplier = Supplier.objects.filter(code=code).first() if code else None
            if supplier is None:
                raise JobError(f"{where}: give the supplier.")
        else:
            code = _text(row.get("component")).upper()
            component = Item.objects.filter(code=code, is_active=True).first() if code else None
            if component is None:
                raise JobError(f"{where}: there is no active item {code or '(blank)'}.")
        try:
            op = _text(row.get("operation_seq"))
            operation_seq = int(op) if op else None
        except ValueError:
            raise JobError(f"{where}: the operation is its number, e.g. 20.") from None
        cost = row.get("unit_cost")
        out.append(
            {
                "seq": seq,
                "line_type": line_type,
                "component": component,
                "supplier": supplier,
                "description": _text(row.get("description"))[:150],
                "per_piece": _decimal(row.get("per_piece"), f"quantity per piece ({where})", 6),
                "unit": (_text(row.get("unit")) or (component.unit if component else "pcs"))[:10],
                "operation_seq": operation_seq,
                "customer_supplied": str(row.get("customer_supplied", "")).lower()
                in ("true", "1", "yes", "on"),
                "unit_cost": _decimal(cost, f"cost ({where})", 2, blank_ok=True),
                "stock_size": _text(row.get("stock_size"))[:50],
                "notes": _text(row.get("notes"))[:300],
            }
        )
    return sorted(out, key=lambda m: m["seq"])


def _copy(job: JobOrder) -> None:
    """Copy the approved routing and BOM of the job's part (replacing what the job had)."""
    job.operations.all().delete()
    job.materials.all().delete()
    routing = routings.in_force(job.item) if job.item_id else None
    bom = in_force_bom(job.item) if job.item_id else None
    job.routing, job.bom = routing, bom
    job.save(update_fields=["routing", "bom"])
    if routing is not None:
        JobOperation.objects.bulk_create(
            JobOperation(
                job=job,
                seq=o.seq,
                name=o.name,
                section=o.section,
                machine=o.machine,
                setup_min=o.setup_min,
                run_min=o.run_min,
                subcontract=o.subcontract,
                supplier=o.supplier,
                subcontract_cost=o.subcontract_cost,
                notes=o.notes,
            )
            for o in routing.operations.all()
        )
    if bom is not None:
        JobMaterial.objects.bulk_create(
            JobMaterial(
                job=job,
                seq=x.seq,
                line_type=x.line_type,
                component=x.component,
                description=x.description,
                supplier=x.supplier,
                per_piece=max(
                    (x.quantity * (1 + x.scrap_pct / 100) / bom.base_quantity).quantize(
                        PER, ROUND_HALF_UP
                    ),
                    PER,
                ),
                unit=x.unit,
                operation_seq=x.operation_seq,
                customer_supplied=x.customer_supplied,
                unit_cost=x.unit_cost,
                stock_size=x.stock_size,
                notes=x.notes,
            )
            for x in bom.lines.all()
        )


def _save_lines(user: User, job: JobOrder, values: dict) -> None:
    if "operations" in values:
        rows = _operations(user, values["operations"])
        job.operations.all().delete()
        JobOperation.objects.bulk_create(JobOperation(job=job, **o) for o in rows)
    if "materials" in values:
        rows = _materials(values["materials"])
        job.materials.all().delete()
        JobMaterial.objects.bulk_create(JobMaterial(job=job, **m) for m in rows)


# --- Making and changing -------------------------------------------------------------------------


def create(user: User, values: dict) -> JobOrder:
    _check(user)
    fields = _fields(user, values, None)
    with audit_context("job_order_created"), transaction.atomic():
        try:
            number = allocate(DOC, division=fields["division"], on_date=timezone.localdate())
        except NumberSeriesError as error:
            raise JobError(str(error)) from None
        job = JobOrder.objects.create(number=number, created_by=user, **fields)
        _copy(job)
        _save_lines(user, job, values)
        return job


def update(user: User, job: JobOrder, values: dict) -> JobOrder:
    _check(user)
    with audit_context("job_order_changed", job.number), transaction.atomic():
        job = _fresh(job)
        if job.status != St.DRAFT:
            raise JobError(f"{job.number} is {job.get_status_display().lower()}.")
        before = job.item_id
        fields = _fields(user, values, job)
        for key, value in fields.items():
            setattr(job, key, value)
        job.save()
        if job.item_id != before or values.get("copy_again"):
            _copy(job)
        _save_lines(user, job, values)
        return job


def release(user: User, job: JobOrder) -> JobOrder:
    _check(user)
    with audit_context("job_order_released", job.number), transaction.atomic():
        job = _fresh(job)
        if job.status != St.DRAFT:
            raise JobError(f"Only a draft is released; {job.number} is {job.status}.")
        if not job.operations.exists():
            raise JobError(f"{job.number} has no operations: give at least one.")
        if job.sales_line_id and job.sales_line.order.status not in orders.SALES_OPEN:
            raise JobError(f"Sales order {job.sales_line.order.number} is not open.")
        job.status, job.released_by, job.released_at = St.RELEASED, user, timezone.now()
        job.save()
        return job


def _move(user: User, job: JobOrder, event: str, to: str, before: tuple, **more) -> JobOrder:
    _check(user)
    with audit_context(event, job.number), transaction.atomic():
        job = _fresh(job)
        if job.status not in before:
            raise JobError(
                f"{job.number} is {job.get_status_display().lower()}: it cannot be "
                f"{JobOrder.Status(to).label.lower()}."
            )
        job.status = to
        for key, value in more.items():
            setattr(job, key, value)
        job.save()
        return job


def complete(user: User, job: JobOrder) -> JobOrder:
    return _move(
        user, job, "job_order_completed", St.COMPLETED, (St.RELEASED,), completed_at=timezone.now()
    )


def close(user: User, job: JobOrder) -> JobOrder:
    if JobExcess.objects.filter(job=job, status=JobExcess.Status.AWAITING).exists():
        raise JobError(f"{job.number} has a request to issue more waiting for approval.")
    return _move(
        user, job, "job_order_closed", St.CLOSED, (St.COMPLETED,), closed_at=timezone.now()
    )


def cancel(user: User, job: JobOrder, reason: str) -> JobOrder:
    reason = _text(reason)[:300]
    if not reason:
        raise JobError("Give the reason for cancelling.")
    if net_issued(job):
        raise JobError(f"{job.number} has material issued: return it to stores first.")
    return _move(user, job, "job_order_cancelled", St.CANCELLED, OPEN, end_reason=reason)


# --- Material ------------------------------------------------------------------------------------


def net_issued(job: JobOrder) -> dict[int, Decimal]:
    """Per item: issued to the job less returned."""
    rows = (
        StockIssueLine.objects.filter(issue__job_link__job=job)
        .values("item_id", "issue__kind")
        .annotate(total=Sum("quantity"))
    )
    out: dict[int, Decimal] = {}
    for r in rows:
        sign = 1 if r["issue__kind"] == StockIssue.Kind.ISSUE else -1
        out[r["item_id"]] = out.get(r["item_id"], ZERO) + sign * r["total"]
    return {k: v for k, v in out.items() if v}


def allowed(job: JobOrder) -> dict[int, Decimal]:
    """Per item: what the job may use (per piece × quantity) plus approved requests for more."""
    out: dict[int, Decimal] = {}
    for m in job.materials.filter(component__isnull=False):
        need = (m.per_piece * job.quantity).quantize(QTY, ROUND_CEILING)
        out[m.component_id] = out.get(m.component_id, ZERO) + need
    for x in job.excess.filter(status=JobExcess.Status.APPROVED):
        out[x.component_id] = out.get(x.component_id, ZERO) + x.quantity
    return out


def _store(user: User, job: JobOrder, value) -> Store:
    try:
        store = Store.objects.select_related("division").get(pk=int(_text(value)))
    except (ValueError, Store.DoesNotExist):
        raise JobError("Choose the store.") from None
    if store.division_id != job.division_id:
        raise JobError(f"Issue from a store of division {job.division.code}.")
    try:
        return issues.main_store(user, store)
    except StockError as error:
        raise JobError(str(error)) from None


def issue(user: User, job: JobOrder, values: dict) -> StockIssue:
    """Issue material to a released job, within what it may use."""
    if not can_issue(user):
        raise JobError("Only the stores person issues material.")
    rows = values.get("lines") or []
    if not rows:
        raise JobError("Add at least one item.")
    if len(rows) > MAX_LINES:
        raise JobError(f"An issue has at most {MAX_LINES} lines.")
    with transaction.atomic():
        job = _fresh(job)
        if job.status != St.RELEASED:
            raise JobError(f"Material is issued to a released job; {job.number} is {job.status}.")
        store = _store(user, job, values.get("store"))
        day = _date(values.get("issue_date") or timezone.localdate(), "date")
        lines, wanted = [], {}
        for n, row in enumerate(rows, start=1):
            item = Item.objects.filter(code=_text(row.get("item")).upper()).first()
            if item is None:
                raise JobError(f"Line {n}: choose the item.")
            quantity = _decimal(row.get("quantity"), f"quantity on line {n}", 3)
            wanted[item.pk] = wanted.get(item.pk, ZERO) + quantity
            lines.append(
                issues.IssueLine(item=item, quantity=quantity, lot_no=_text(row.get("lot_no")))
            )
        may, done = allowed(job), net_issued(job)
        for pk, quantity in wanted.items():
            left = may.get(pk, ZERO) - done.get(pk, ZERO)
            if quantity > left:
                item = Item.objects.get(pk=pk)
                raise JobError(
                    f"{item.code}: {_n(quantity)} {item.unit} is {_n(quantity - max(left, ZERO))} "
                    f"more than {job.number} may still use ({_n(max(left, ZERO))}). Ask the "
                    "Production Manager to approve the extra, with the reason."
                )
        try:
            document = issues.issue_for(
                user,
                store=store,
                issue_date=day,
                lines=lines,
                purpose=f"Job {job.number}: {job.description}"[:300],
            )
        except StockError as error:
            raise JobError(str(error)) from None
        with audit_context("job_material_issued", job.number):
            JobIssue.objects.create(job=job, stock_issue=document)
        return document


def give_back(user: User, job: JobOrder, values: dict) -> StockIssue:
    """Material not used comes back against its issue and is credited to the job."""
    if not can_issue(user):
        raise JobError("Only the stores person takes material back.")
    with transaction.atomic():
        job = _fresh(job)
        if job.status not in (St.RELEASED, St.COMPLETED):
            raise JobError(f"{job.number} is {job.get_status_display().lower()}.")
        link = (
            JobIssue.objects.filter(
                job=job, stock_issue_id=values.get("issue"), stock_issue__kind=StockIssue.Kind.ISSUE
            )
            .select_related("stock_issue")
            .first()
        )
        if link is None:
            raise JobError(f"Choose an issue of {job.number}.")
        original = link.stock_issue
        pairs = []
        for row in values.get("lines") or []:
            line = original.lines.filter(pk=row.get("line")).select_related("item").first()
            if line is None:
                raise JobError(f"That line is not on issue {original.number}.")
            if _text(row.get("quantity")):
                pairs.append((line, row.get("quantity")))
        try:
            document = issues.give_back(
                user,
                original,
                return_date=_date(values.get("return_date") or timezone.localdate(), "date"),
                lines=pairs,
            )
        except StockError as error:
            raise JobError(str(error)) from None
        with audit_context("job_material_returned", job.number):
            JobIssue.objects.create(job=job, stock_issue=document)
        return document


# --- More than the job allows --------------------------------------------------------------------


def ask_more(user: User, job: JobOrder, values: dict) -> JobExcess:
    """Ask the Production Manager to allow more of a material than the job may use."""
    if not (can_issue(user) or can_plan(user)):
        raise JobError("The stores person or the Planner asks to issue more.")
    item = Item.objects.filter(code=_text(values.get("item")).upper()).first()
    if item is None or not item.is_stock:
        raise JobError("Choose the stock item.")
    quantity = _decimal(values.get("quantity"), "extra quantity", 3)
    reason = _text(values.get("reason"))[:300]
    if not reason:
        raise JobError("Give the reason for needing more, e.g. two pieces scrapped at setup.")
    with audit_context("job_excess_asked", job.number), transaction.atomic():
        job = _fresh(job)
        if job.status != St.RELEASED:
            raise JobError(f"{job.number} is {job.get_status_display().lower()}.")
        if job.excess.filter(component=item, status=JobExcess.Status.AWAITING).exists():
            raise JobError(f"A request for more {item.code} is already waiting.")
        excess = JobExcess.objects.create(
            job=job, component=item, quantity=quantity, reason=reason, created_by=user
        )
        try:
            approvals.submit(
                user,
                EXCESS,
                excess.pk,
                created_by=user,
                title=f"{job.number}: {_n(quantity)} {item.unit} more {item.code} ({reason})"[:200],
                link=f"/job-orders?job={job.pk}",
                division=job.division,
            )
        except ApprovalError as error:
            raise JobError(str(error)) from None
        return excess


def decide_more(user: User, excess: JobExcess, action: str, reason: str = "") -> JobExcess:
    reason = _text(reason)
    with audit_context("job_excess_decided", reason), transaction.atomic():
        excess = JobExcess.objects.select_for_update().get(pk=excess.pk)
        if excess.status != JobExcess.Status.AWAITING:
            raise JobError("This request is not waiting for approval.")
        try:
            if action == "approve":
                state = approvals.approve(user, EXCESS, excess.pk, reason)
                if state.status != state.Status.APPROVED:
                    return excess
                excess.status = JobExcess.Status.APPROVED
            elif action == "reject":
                approvals.reject(user, EXCESS, excess.pk, reason)
                excess.status = JobExcess.Status.REJECTED
            else:
                raise JobError("Approve or reject.")
        except ApprovalError as error:
            raise JobError(str(error)) from None
        excess.decided_at = timezone.now()
        excess.save(update_fields=["status", "decided_at"])
        return excess


# --- Reading -------------------------------------------------------------------------------------


def row(job: JobOrder) -> dict:
    return {
        "id": job.pk,
        "number": job.number,
        "purpose": job.purpose,
        "purpose_label": job.get_purpose_display(),
        "item": job.item.code if job.item_id else "",
        "description": job.description,
        "quantity": _n(job.quantity),
        "unit": job.item.unit if job.item_id else "pcs",
        "division": job.division.code,
        "sales_order": job.sales_line.order.number if job.sales_line_id else "",
        "customer": job.sales_line.order.customer.name if job.sales_line_id else "",
        "mould": job.mould.code if job.mould_id else "",
        "due_date": job.due_date,
        "status": job.status,
        "status_label": job.get_status_display(),
    }


def _materials_now(job: JobOrder) -> list[dict]:
    may, done = allowed(job), net_issued(job)
    stock = dict(
        StockMovement.objects.filter(
            item_id__in=set(may) | set(done),
            store__kind=Store.Kind.MAIN,
            store__division_id=job.division_id,
        )
        .values("item_id")
        .annotate(total=Sum("quantity"))
        .values_list("item_id", "total")
    )
    out, seen = [], set()
    for m in job.materials.select_related("component", "supplier"):
        row_ = {
            "seq": m.seq,
            "line_type": m.line_type,
            "component": m.component.code if m.component_id else "",
            "name": m.component.name if m.component_id else m.description,
            "supplier": m.supplier.code if m.supplier_id else "",
            "description": m.description,
            "per_piece": _n(m.per_piece),
            "unit": m.unit,
            "operation_seq": m.operation_seq,
            "customer_supplied": m.customer_supplied,
            "unit_cost": _n(m.unit_cost),
            "stock_size": m.stock_size,
            "notes": m.notes,
        }
        if m.component_id and m.component_id not in seen:
            seen.add(m.component_id)
            pk = m.component_id
            row_ |= {
                "allowed": _n(may.get(pk, ZERO)),
                "issued": _n(done.get(pk, ZERO)),
                "left": _n(may.get(pk, ZERO) - done.get(pk, ZERO)),
                "on_hand": _n(stock.get(pk) or ZERO),
            }
        out.append(row_)
    # Material issued under an approved request but not on the job.
    for pk in (set(may) | set(done)) - seen:
        item = Item.objects.get(pk=pk)
        out.append(
            {
                "seq": None,
                "line_type": "",
                "component": item.code,
                "name": item.name,
                "unit": item.unit,
                "extra": True,
                "allowed": _n(may.get(pk, ZERO)),
                "issued": _n(done.get(pk, ZERO)),
                "left": _n(may.get(pk, ZERO) - done.get(pk, ZERO)),
                "on_hand": _n(stock.get(pk) or ZERO),
            }
        )
    return out


def _issues(job: JobOrder) -> list[dict]:
    out = []
    links = job.issues.select_related("stock_issue__store").prefetch_related(
        "stock_issue__lines__item", "stock_issue__lines__returns"
    )
    for link in links:
        d = link.stock_issue
        out.append(
            {
                "id": d.pk,
                "number": d.number,
                "kind": d.kind,
                "date": d.issue_date,
                "store": d.store.code,
                "value": str(d.total_value),
                "lines": [
                    {
                        "id": x.pk,
                        "item": x.item.code,
                        "lot_no": x.lot_no,
                        "quantity": _n(x.quantity),
                        "unit": x.item.unit,
                        "value": str(x.value),
                        "returnable": _n(x.quantity - issues.returned_already(x))
                        if d.kind == StockIssue.Kind.ISSUE
                        else "",
                    }
                    for x in d.lines.all()
                ],
            }
        )
    return out


def _excess(job: JobOrder, user: User) -> list[dict]:
    out = []
    for x in job.excess.select_related("component", "created_by"):
        state = approvals.state_of(EXCESS, x.pk) if x.status == JobExcess.Status.AWAITING else None
        out.append(
            {
                "id": x.pk,
                "item": x.component.code,
                "quantity": _n(x.quantity),
                "unit": x.component.unit,
                "reason": x.reason,
                "status": x.status,
                "by": x.created_by.full_name,
                "at": x.created_at,
                "can_decide": state is not None and approvals.why_not(user, state) is None,
            }
        )
    return out


def payload(job: JobOrder, user: User) -> dict:
    planner = can_plan(user)
    stores = can_issue(user)
    return row(job) | {
        "sales_line": orders._sales(job.sales_line),
        "item_name": job.item.name if job.item_id else "",
        "drawing_no": job.drawing_no,
        "drawing_revision": job.drawing_revision,
        "notes": job.notes,
        "end_reason": job.end_reason,
        "routing": (
            {"id": job.routing.pk, "revision": job.routing.revision} if job.routing_id else None
        ),
        "bom": {"id": job.bom.pk, "revision": job.bom.revision} if job.bom_id else None,
        "operations": [
            {
                "seq": o.seq,
                "name": o.name,
                "section": o.section.code if o.section_id else "",
                "machine": o.machine.code if o.machine_id else "",
                "setup_min": _n(o.setup_min),
                "run_min": _n(o.run_min),
                "subcontract": o.subcontract,
                "supplier": o.supplier.code if o.supplier_id else "",
                "subcontract_cost": _n(o.subcontract_cost),
                "notes": o.notes,
            }
            for o in job.operations.select_related("section", "machine", "supplier")
        ],
        "materials": _materials_now(job),
        # P3-12: what each operation received, completed, rejected and passed on.
        "progress": job_cards.progress(job) if job.status != St.DRAFT else [],
        "can_print_cards": job.status in (St.RELEASED, St.COMPLETED),
        # P3-13: parts sent out to suppliers and back, and the bills coded to the job.
        "subcontract": subcontract.rows(job),
        "bills": subcontract.bills(job),
        "can_subcontract": subcontract.can_move(user) and job.status == St.RELEASED,
        "suppliers": [
            {"seq": o.seq, "supplier": o.supplier.code if o.supplier_id else ""}
            for o in job.operations.filter(subcontract=True).select_related("supplier")
        ],
        "issues": _issues(job),
        "excess": _excess(job, user),
        "stores": [
            {"id": s.pk, "code": s.code, "name": s.name}
            for s in Store.objects.filter(
                division=job.division, kind=Store.Kind.MAIN, is_active=True
            )
        ]
        if stores
        else [],
        "created_by": job.created_by.full_name,
        "released_by": job.released_by.full_name if job.released_by_id else "",
        "released_at": job.released_at,
        "can_edit": planner and job.status == St.DRAFT,
        "can_release": planner and job.status == St.DRAFT,
        "can_complete": planner and job.status == St.RELEASED,
        "can_close": planner and job.status == St.COMPLETED,
        "can_cancel": planner and job.status in OPEN,
        "can_issue": stores and job.status == St.RELEASED,
        "can_return": stores and job.status in (St.RELEASED, St.COMPLETED),
        "can_ask_more": (stores or planner) and job.status == St.RELEASED,
    }


def lots_for(user: User, job: JobOrder, store_id, code: str) -> list[dict]:
    store = _store(user, job, store_id)
    item = Item.objects.filter(code=_text(code).upper()).first()
    if item is None:
        raise JobError("Choose the item.")
    return [{"lot_no": lot, "quantity": _n(q)} for lot, q in issues.lots(item, store)]


def search(user: User, q: str = "", status: str = "", purpose: str = "") -> QuerySet:
    found = visible(user)
    if q:
        found = found.filter(
            Q(number__icontains=q)
            | Q(item__code__icontains=q)
            | Q(description__icontains=q)
            | Q(sales_line__order__number__icontains=q)
            | Q(mould__code__icontains=q)
        )
    if status == "open":
        found = found.filter(status__in=OPEN)
    elif status:
        found = found.filter(status=status)
    if purpose:
        found = found.filter(purpose=purpose)
    return found


def waiting(user: User) -> list[dict]:
    """Requests to issue more that the user may decide."""
    out = []
    for x in JobExcess.objects.filter(
        status=JobExcess.Status.AWAITING, job__division__in=division_scope(user)
    ).select_related("job", "component", "created_by"):
        state = approvals.state_of(EXCESS, x.pk)
        if state is not None and approvals.why_not(user, state) is None:
            out.append(
                {
                    "id": x.pk,
                    "job": x.job.number,
                    "job_id": x.job_id,
                    "item": x.component.code,
                    "quantity": _n(x.quantity),
                    "unit": x.component.unit,
                    "reason": x.reason,
                    "by": x.created_by.full_name,
                }
            )
    return out
