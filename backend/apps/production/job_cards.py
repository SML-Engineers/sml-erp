"""Job cards and operation entry (backlog P3-12; spec 7.2, 7.4).

- **Job cards:** one printed card per operation of a released job, with a QR code holding
  "<job number>/<operation>", e.g. "JO26110001/20". The card travels with the parts.
- **Operation entry** in a machining section's shift report (the same report as moulding,
  P3-08): the supervisor scans the card and enters the machine (of the section), operator,
  start and end, pieces completed, rejected (by reason) and sent for rework, and whether the
  time includes the setup.
- **Checks:** the job is released and of the section's division; the operation is the
  job's and done here (a subcontract operation comes back through P3-13); times fall in the
  shift and never overlap on a machine (database too); **completed + rejected never exceed
  what the previous operation released** (its completed pieces, or for a subcontract
  operation the good pieces back from the supplier, P3-13; the job's quantity for the first
  operation). Pieces sent for rework stay at the operation until they are completed
  or rejected.
- **Worked out:** minutes per piece (the entry's time less the machine's downtime in it,
  over completed + rejected) against the routing's standard; per operation: received,
  completed, rejected, in hand, and **available for the next operation**.
- The report is submitted and approved, sent back or corrected as moulding reports (P3-09);
  approved entries feed the job's costs (P3-16).
"""

from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

from django.db.models import Sum
from django.utils import timezone
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from apps.core.models import Company
from apps.inventory.labels import _fit, _qr
from apps.payroll.models import Employee

from .models import (
    JobCardEntry,
    JobCardReject,
    JobOperation,
    JobOrder,
    ShiftReport,
    SubcontractDispatch,
)

ZERO = Decimal("0")


class JobCardError(Exception):
    pass


def _n(value) -> str:
    if value is None:
        return ""
    value = Decimal(value)
    return f"{value.normalize():f}" if value else "0"


def card_code(job: JobOrder, operation: JobOperation) -> str:
    return f"{job.number}/{operation.seq}"


# --- Flow through the operations -----------------------------------------------------------------


def _totals(job: JobOrder, *, but: ShiftReport | None = None) -> dict[int, dict[str, Decimal]]:
    """Per operation id: completed, rejected and rework in all reports (but one)."""
    rows = JobCardEntry.objects.filter(job=job)
    if but is not None:
        rows = rows.exclude(report=but)
    out: dict[int, dict[str, Decimal]] = defaultdict(
        lambda: {"completed": ZERO, "rejected": ZERO, "rework": ZERO}
    )
    for r in rows.values("operation_id").annotate(
        c=Sum("completed"), x=Sum("rejected"), w=Sum("rework")
    ):
        out[r["operation_id"]] = {"completed": r["c"], "rejected": r["x"], "rework": r["w"]}
    return out


def _sent_back(job: JobOrder) -> dict[int, dict[str, Decimal]]:
    """Per subcontract operation id: sent out, good back and rejected back (P3-13)."""
    out: dict[int, dict[str, Decimal]] = {}
    for d in SubcontractDispatch.objects.filter(job=job).prefetch_related("returns"):
        t = out.setdefault(d.operation_id, {"sent": ZERO, "good": ZERO, "rejected": ZERO})
        t["sent"] += d.quantity
        for r in d.returns.all():
            t["good"] += r.good
            t["rejected"] += r.rejected
    return out


def flow(job: JobOrder, totals: dict | None = None) -> list[dict]:
    """Per operation in order: received (released by the one before), completed, rejected,
    rework, in hand, at the supplier (subcontract) and available for the next operation."""
    totals = totals if totals is not None else _totals(job)
    away = _sent_back(job)
    blank = {"completed": ZERO, "rejected": ZERO, "rework": ZERO}
    out = []
    received = job.quantity
    ops = list(job.operations.order_by("seq"))
    for n, op in enumerate(ops):
        if op.subcontract:
            # P3-13: good parts back from the supplier go on; rejected ones are lost here.
            a = away.get(op.pk, {"sent": ZERO, "good": ZERO, "rejected": ZERO})
            t = {"completed": a["good"], "rejected": a["rejected"], "rework": ZERO}
            in_hand = received - a["sent"]
            at_supplier = a["sent"] - a["good"] - a["rejected"]
        else:
            t = totals.get(op.pk, blank)
            in_hand = received - t["completed"] - t["rejected"]
            at_supplier = ZERO
        nxt = ops[n + 1] if n + 1 < len(ops) else None
        used_next = ZERO
        if nxt is not None:
            if nxt.subcontract:
                used_next = away.get(nxt.pk, {"sent": ZERO})["sent"]
            else:
                u = totals.get(nxt.pk, blank)
                used_next = u["completed"] + u["rejected"]
        out.append(
            {
                "operation": op,
                "received": received,
                "completed": t["completed"],
                "rejected": t["rejected"],
                "rework": t["rework"],
                "in_hand": in_hand,
                "at_supplier": at_supplier,
                "available": max(t["completed"] - used_next, ZERO) if nxt is not None else ZERO,
                "finished": t["completed"] if nxt is None else ZERO,
            }
        )
        received = t["completed"]
    return out


def progress(job: JobOrder) -> list[dict]:
    return [
        {
            "seq": f["operation"].seq,
            "name": f["operation"].name,
            "subcontract": f["operation"].subcontract,
            "received": _n(f["received"]),
            "completed": _n(f["completed"]),
            "rejected": _n(f["rejected"]),
            "rework": _n(f["rework"]),
            "in_hand": _n(f["in_hand"]),
            "at_supplier": _n(f["at_supplier"]),
            "available": _n(f["available"]),
            "finished": _n(f["finished"]),
            "card": card_code(job, f["operation"]),
        }
        for f in flow(job)
    ]


# --- Entry in a machining shift report -----------------------------------------------------------


def _job(look, value) -> tuple[JobOrder, JobOperation | None]:
    """A job from its number or id, or a scanned card "JO26110001/20" (job and operation)."""
    text = " ".join(str(value or "").split()).upper()
    seq = None
    if "/" in text:
        text, _, rest = text.partition("/")
        seq = rest.strip()
    job = look.jobs.get(text)
    if job is None and text.isdigit():
        job = next((j for j in look.jobs.values() if j.pk == int(text)), None)
    if job is None:
        raise JobCardError(f"{text or 'The job'} is not a released job of this division.")
    op = None
    if seq:
        try:
            op = job.operations.get(seq=int(seq))
        except (ValueError, JobOperation.DoesNotExist):
            raise JobCardError(f"{job.number} has no operation {seq}.") from None
    return job, op


def parse(report: ShiftReport, values: dict, look, helpers) -> list[dict]:
    """The report's operation lines, checked one by one (flow and overlaps are checked
    together afterwards)."""
    at, decimal, rows_of = helpers["at"], helpers["decimal"], helpers["rows"]
    out = []
    for n, r in enumerate(rows_of(values, "operations"), start=1):
        machine = look.machine(r.get("machine"))
        label = f"line {n} ({machine.code})"
        job, op = _job(look, r.get("job"))
        if r.get("operation") not in (None, ""):
            try:
                op = job.operations.get(seq=int(str(r.get("operation")).strip()))
            except (ValueError, JobOperation.DoesNotExist):
                raise JobCardError(f"{job.number} has no operation {r.get('operation')}.") from None
        if op is None:
            raise JobCardError(f"Choose the operation of {job.number} for {label}.")
        if op.subcontract:
            raise JobCardError(
                f"Operation {op.seq} of {job.number} is sent out to a supplier: it is recorded "
                "when the parts come back."
            )
        label = f"line {n} ({job.number}/{op.seq} on {machine.code})"
        started = at(report, r.get("start_time"), f"start time of {label}")
        ended = at(report, r.get("end_time"), f"end time of {label}")
        if ended <= started:
            raise JobCardError(f"The end time of {label} is after its start.")
        number = " ".join(str(r.get("operator") or "").split()).upper()
        operator = None
        if number:
            operator = Employee.objects.filter(
                number=number, division=look.division, leaving_date__isnull=True
            ).first()
            if operator is None:
                raise JobCardError(f"There is no employee {number} for {label}.")
        completed = decimal(r.get("completed") or "0", f"pieces completed on {label}", 3)
        rework = decimal(r.get("rework") or "0", f"pieces for rework on {label}", 3)
        rejects = []
        for x in r.get("rejects") or []:
            code = " ".join(str(x.get("reason") or "").split()).upper()
            if code not in look.rejects:
                raise JobCardError(f"Choose a reject reason for {label}.")
            quantity = decimal(x.get("quantity"), f"rejects on {label}", 3)
            if quantity:
                rejects.append((look.rejects[code], quantity))
        setup = str(r.get("setup", "")).lower() in ("true", "1", "yes", "on")
        rejected = sum((q for _, q in rejects), ZERO)
        if not (completed or rejected or rework or setup):
            raise JobCardError(f"Give the pieces completed, rejected or for rework on {label}.")
        out.append(
            {
                "job": job,
                "operation": op,
                "machine": machine,
                "operator": operator,
                "started_at": started,
                "ended_at": ended,
                "completed": completed,
                "rejected": rejected,
                "rework": rework,
                "setup": setup,
                "notes": " ".join(str(r.get("notes") or "").split())[:200],
                "rejects": rejects,
                "label": label,
            }
        )
    return out


def check_flow(report: ShiftReport, rows: list[dict]) -> None:
    """Completed + rejected at an operation never exceed what it received."""
    for job in {r["job"].pk: r["job"] for r in rows}.values():
        totals = _totals(job, but=report)
        for r in rows:
            if r["job"].pk == job.pk:
                t = totals[r["operation"].pk]
                t["completed"] += r["completed"]
                t["rejected"] += r["rejected"]
                t["rework"] += r["rework"]
        steps = flow(job, totals)
        for n, f in enumerate(steps):
            op = f["operation"]
            if op.subcontract:
                continue
            done = f["completed"] + f["rejected"]
            if done > f["received"]:
                before = (
                    f"what operation {steps[n - 1]['operation'].seq} released"
                    if n
                    else "the job's quantity"
                )
                raise JobCardError(
                    f"{job.number} operation {op.seq}: {_n(done)} completed and rejected is more "
                    f"than {before} ({_n(f['received'])})."
                )


def minutes_per_piece(row: dict, downtime: list[dict]) -> Decimal | None:
    pieces = row["completed"] + row["rejected"]
    if not pieces:
        return None
    seconds = (row["ended_at"] - row["started_at"]).total_seconds()
    for d in downtime:
        if d["machine"].pk == row["machine"].pk:
            overlap = min(d["ended_at"], row["ended_at"]) - max(d["started_at"], row["started_at"])
            seconds -= max(overlap.total_seconds(), 0)
    return (Decimal(str(max(seconds, 0))) / 60 / pieces).quantize(Decimal("0.001"), ROUND_HALF_UP)


def store(report: ShiftReport, rows: list[dict], downtime: list[dict]) -> None:
    report.job_entries.all().delete()
    for r in rows:
        rejects = r.pop("rejects")
        r.pop("label")
        entry = JobCardEntry.objects.create(
            report=report, minutes_per_piece=minutes_per_piece(r, downtime), **r
        )
        JobCardReject.objects.bulk_create(
            JobCardReject(entry=entry, reason=reason, quantity=q) for reason, q in rejects
        )


def _clock(moment: datetime) -> str:
    return f"{timezone.localtime(moment):%H:%M}"


def read(report: ShiftReport) -> list[dict]:
    out = []
    for e in report.job_entries.select_related(
        "job__item", "operation", "machine", "operator"
    ).prefetch_related("rejects__reason"):
        out.append(
            {
                "job": e.job.number,
                "job_id": e.job_id,
                "description": e.job.description,
                "operation": e.operation.seq,
                "operation_name": e.operation.name,
                "machine": e.machine.code,
                "operator": e.operator.number if e.operator_id else "",
                "start_time": _clock(e.started_at),
                "end_time": _clock(e.ended_at),
                "completed": _n(e.completed),
                "rejected": _n(e.rejected),
                "rework": _n(e.rework),
                "setup": e.setup,
                "notes": e.notes,
                "rejects": [
                    {"reason": x.reason.code, "quantity": _n(x.quantity)} for x in e.rejects.all()
                ],
                "minutes_per_piece": _n(e.minutes_per_piece),
                "standard_minutes": _n(e.operation.run_min),
                "standard_setup": _n(e.operation.setup_min),
            }
        )
    return out


def options(look) -> list[dict]:
    """The released jobs of the division with their operations done in the workshop, and
    what each operation has in hand."""
    out = []
    for job in look.jobs.values():
        ops = []
        for f in flow(job):
            op = f["operation"]
            if op.subcontract:
                continue
            ops.append(
                {
                    "seq": op.seq,
                    "name": op.name,
                    "section": op.section.code if op.section_id else "",
                    "machine": op.machine.code if op.machine_id else "",
                    "in_hand": _n(f["in_hand"]),
                    "run_min": _n(op.run_min),
                }
            )
        out.append(
            {
                "id": job.pk,
                "number": job.number,
                "item": job.item.code if job.item_id else "",
                "description": job.description,
                "operations": ops,
            }
        )
    return out


def summary(report: ShiftReport) -> dict:
    rows = list(report.job_entries.all())
    return {
        "completed": _n(sum((e.completed for e in rows), ZERO)),
        "rejected": _n(sum((e.rejected for e in rows), ZERO)),
        "rework": _n(sum((e.rework for e in rows), ZERO)),
        "minutes": sum(int((e.ended_at - e.started_at).total_seconds() // 60) for e in rows),
    }


# --- The printed cards ---------------------------------------------------------------------------


def render(job: JobOrder) -> bytes:
    """One A5 card per operation, with the QR code the supervisor scans."""
    company = Company.objects.filter(pk=1).first()
    name = (company.name if company else "").upper()
    width, height = A5
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A5, pageCompression=1)
    pdf.setTitle(f"Job cards {job.number}")
    ops = list(job.operations.select_related("section", "machine", "supplier").order_by("seq"))
    for n, op in enumerate(ops, start=1):
        top = height - 12 * mm
        pdf.setFont("Helvetica", 8)
        pdf.drawString(12 * mm, top, _fit(name, 60))
        pdf.drawRightString(width - 12 * mm, top, f"Card {n} of {len(ops)}")
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(12 * mm, top - 10 * mm, f"{job.number}  Op {op.seq}")
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(12 * mm, top - 18 * mm, _fit(op.name, 48))
        renderPDF.draw(_qr(card_code(job, op)), pdf, width - 54 * mm, top - 60 * mm)
        pdf.setFont("Helvetica", 9)
        lines = [
            f"Part: {job.item.code if job.item_id else ''} {job.description}",
            f"Drawing: {job.drawing_no or '-'}  Rev {job.drawing_revision or '-'}",
            f"Quantity: {_n(job.quantity)}   Due: {job.due_date:%d %b %Y}",
            (
                f"Sent out to: {op.supplier.name}"
                if op.subcontract and op.supplier_id
                else f"Section: {op.section.code if op.section_id else ''}  "
                f"Machine: {op.machine.code if op.machine_id else 'any'}"
            ),
            f"Standard: setup {_n(op.setup_min)} min, {_n(op.run_min)} min a piece",
        ]
        if job.sales_line_id:
            lines.append(f"Sales order: {job.sales_line.order.number}")
        if op.notes:
            lines.append(f"Notes: {op.notes}")
        y = top - 28 * mm
        for text in lines:
            pdf.drawString(12 * mm, y, _fit(text, 52))
            y -= 5.5 * mm
        nxt = ops[n] if n < len(ops) else None
        pdf.drawString(
            12 * mm,
            y - 2 * mm,
            f"Next: {f'Op {nxt.seq} {nxt.name}' if nxt else 'Final inspection'}",
        )
        # Boxes for the operator's notes on the floor.
        y = 70 * mm
        pdf.setFont("Helvetica-Bold", 9)
        for label in ("Date / shift", "Operator", "Completed", "Rejected", "For rework"):
            pdf.rect(12 * mm, y - 2 * mm, width - 24 * mm, 9 * mm)
            pdf.drawString(14 * mm, y + 1 * mm, label)
            y -= 11 * mm
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
