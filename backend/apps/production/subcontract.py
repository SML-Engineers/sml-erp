"""Subcontract operations (backlog P3-13; spec 7.2, 7.7).

- **Sent out:** parts of a released job leave for the supplier of a subcontract operation
  (e.g. hard chrome plating), on a numbered note ("SC", printed for the gate and the
  supplier). Never more than the operation has received from the one before, less what is
  already out or back.
- **Received back:** the parts are counted when they return against their note: good, and
  rejected with the reason. Never more than is still out (service and database). Good parts
  go on to the next operation; rejected ones are lost at this operation.
- The Production Planner or the stores person sends and receives. Notes and receipts are
  never changed or deleted (database).
- **The supplier's bill** reaches the job when the Accountant codes the voucher line or the
  supplier invoice line to the job's number (`links.order_for`); the job shows them.
"""

from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from apps.core.audit import audit_context
from apps.core.models import Company, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.inventory.labels import _fit, _qr
from apps.masters.models import Supplier

from . import job_cards
from .models import JobOperation, JobOrder, SubcontractDispatch, SubcontractReturn

ZERO = Decimal("0")
QTY = Decimal("0.001")


class SubcontractError(Exception):
    pass


def can_move(user: User) -> bool:
    from . import jobs

    return jobs.can_plan(user) or jobs.can_issue(user)


def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def _quantity(value, label: str, *, zero_ok=False) -> Decimal:
    text = _text(value).replace(",", "")
    if not text and zero_ok:
        return ZERO
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise SubcontractError(f"Give the {label}.") from None
    if not number.is_finite() or number < 0 or (number == 0 and not zero_ok):
        raise SubcontractError(f"The {label} is more than 0.")
    if number >= Decimal("1e12") or number != number.quantize(QTY):
        raise SubcontractError(f"The {label} has at most 3 decimal places.")
    return number


def _date(value, label: str, *, blank_ok=False) -> date | None:
    if isinstance(value, date):
        return value
    text = _text(value)
    if not text:
        if blank_ok:
            return None
        return timezone.localdate()
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise SubcontractError(f"Give the {label}, e.g. 2026-11-20.") from None


def _n(value) -> str:
    return job_cards._n(value)


def sent(operation: JobOperation) -> Decimal:
    return operation.dispatches.aggregate(q=Sum("quantity"))["q"] or ZERO


def out(dispatch: SubcontractDispatch) -> Decimal:
    """Still at the supplier."""
    back = dispatch.returns.aggregate(g=Sum("good"), r=Sum("rejected"))
    return dispatch.quantity - (back["g"] or ZERO) - (back["r"] or ZERO)


def send_out(user: User, job: JobOrder, values: dict) -> SubcontractDispatch:
    if not can_move(user):
        raise SubcontractError("The Production Planner or the stores person sends parts out.")
    with transaction.atomic():
        job = JobOrder.objects.select_for_update().get(pk=job.pk)
        if job.status != JobOrder.Status.RELEASED:
            raise SubcontractError(
                f"Parts are sent out for a released job; {job.number} is {job.status}."
            )
        try:
            op = job.operations.select_related("supplier").get(
                seq=int(_text(values.get("operation")))
            )
        except (ValueError, JobOperation.DoesNotExist):
            raise SubcontractError(f"Choose a subcontract operation of {job.number}.") from None
        if not op.subcontract:
            raise SubcontractError(f"Operation {op.seq} of {job.number} is done in the workshop.")
        supplier = op.supplier
        code = _text(values.get("supplier")).upper()
        if code:
            supplier = Supplier.objects.filter(code=code).first()
            if supplier is None:
                raise SubcontractError(f"There is no supplier {code}.")
        if supplier is None or not supplier.is_active:
            raise SubcontractError("Choose an active supplier.")
        quantity = _quantity(values.get("quantity"), "quantity sent")
        step = next(f for f in job_cards.flow(job) if f["operation"].pk == op.pk)
        free = step["received"] - sent(op)
        if quantity > free:
            raise SubcontractError(
                f"{job.number} operation {op.seq} has {_n(max(free, ZERO))} pieces ready to send "
                f"(released by the operation before, less what was sent)."
            )
        sent_on = _date(values.get("sent_on"), "date sent")
        if sent_on > timezone.localdate():
            raise SubcontractError("The date sent is not in the future.")
        expected = _date(values.get("expected_on"), "date expected back", blank_ok=True)
        if expected is not None and expected < sent_on:
            raise SubcontractError("The parts are expected back on or after the day they go.")
        try:
            number = allocate("subcontract_dispatch", division=job.division, on_date=sent_on)
        except NumberSeriesError as error:
            raise SubcontractError(str(error)) from None
        with audit_context("subcontract_sent", job.number):
            return SubcontractDispatch.objects.create(
                number=number,
                job=job,
                operation=op,
                supplier=supplier,
                quantity=quantity,
                sent_on=sent_on,
                expected_on=expected,
                notes=_text(values.get("notes"))[:300],
                created_by=user,
            )


def receive_back(user: User, job: JobOrder, values: dict) -> SubcontractReturn:
    if not can_move(user):
        raise SubcontractError("The Production Planner or the stores person receives parts back.")
    with transaction.atomic():
        job = JobOrder.objects.select_for_update().get(pk=job.pk)
        if job.status != JobOrder.Status.RELEASED:
            raise SubcontractError(f"{job.number} is {job.get_status_display().lower()}.")
        dispatch = (
            SubcontractDispatch.objects.select_for_update()
            .filter(job=job, pk=values.get("dispatch"))
            .first()
        )
        if dispatch is None:
            raise SubcontractError(f"Choose a note of parts sent out for {job.number}.")
        good = _quantity(values.get("good"), "good pieces", zero_ok=True)
        rejected = _quantity(values.get("rejected"), "rejected pieces", zero_ok=True)
        if not good and not rejected:
            raise SubcontractError("Count the pieces received back: good and rejected.")
        reason = _text(values.get("reason"))[:300]
        if rejected and not reason:
            raise SubcontractError("Give the reason the pieces are rejected.")
        left = out(dispatch)
        if good + rejected > left:
            raise SubcontractError(
                f"{dispatch.number} has {_n(left)} pieces still at the supplier; "
                f"{_n(good + rejected)} counted."
            )
        received_on = _date(values.get("received_on"), "date received")
        if received_on > timezone.localdate() or received_on < dispatch.sent_on:
            raise SubcontractError("The date received is between the day sent and today.")
        with audit_context("subcontract_received", dispatch.number):
            return SubcontractReturn.objects.create(
                dispatch=dispatch,
                received_on=received_on,
                good=good,
                rejected=rejected,
                reason=reason,
                notes=_text(values.get("notes"))[:300],
                created_by=user,
            )


def totals(job: JobOrder) -> dict[int, dict[str, Decimal]]:
    """Per subcontract operation id: sent, good back and rejected back."""
    out_: dict[int, dict[str, Decimal]] = {}
    for d in job.dispatches.prefetch_related("returns"):
        t = out_.setdefault(d.operation_id, {"sent": ZERO, "good": ZERO, "rejected": ZERO})
        t["sent"] += d.quantity
        for r in d.returns.all():
            t["good"] += r.good
            t["rejected"] += r.rejected
    return out_


def rows(job: JobOrder) -> list[dict]:
    out_ = []
    for d in job.dispatches.select_related("operation", "supplier").prefetch_related(
        "returns__created_by"
    ):
        back = list(d.returns.all())
        out_.append(
            {
                "id": d.pk,
                "number": d.number,
                "operation": d.operation.seq,
                "operation_name": d.operation.name,
                "supplier": d.supplier.code,
                "supplier_name": d.supplier.name,
                "quantity": _n(d.quantity),
                "sent_on": d.sent_on,
                "expected_on": d.expected_on,
                "notes": d.notes,
                "out": _n(d.quantity - sum((r.good + r.rejected for r in back), ZERO)),
                "returns": [
                    {
                        "received_on": r.received_on,
                        "good": _n(r.good),
                        "rejected": _n(r.rejected),
                        "reason": r.reason,
                        "by": r.created_by.full_name,
                    }
                    for r in back
                ],
            }
        )
    return out_


def bills(job: JobOrder) -> list[dict]:
    """Supplier bills coded to the job: voucher lines and supplier invoice lines."""
    out_ = []
    for line in job.voucher_lines.select_related("voucher__payee"):
        v = line.voucher
        out_.append(
            {
                "kind": "voucher",
                "number": v.number,
                "line_no": line.line_no,
                "supplier": v.payee.name if v.payee_id else "",
                "description": line.description,
                "amount": str(line.amount),
                "status": v.get_status_display(),
            }
        )
    for line in job.invoice_lines.select_related("invoice__supplier", "item"):
        i = line.invoice
        out_.append(
            {
                "kind": "invoice",
                "number": i.number,
                "line_no": line.line_no,
                "supplier": i.supplier.name,
                "description": f"{line.item.code} {line.item.name}",
                "amount": str(line.amount),
                "status": i.get_status_display(),
            }
        )
    return out_


def render(dispatch: SubcontractDispatch) -> bytes:
    """The note that goes with the parts: for the gate and the supplier."""
    company = Company.objects.filter(pk=1).first()
    job, op = dispatch.job, dispatch.operation
    width, height = A5
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A5, pageCompression=1)
    pdf.setTitle(f"Parts sent out {dispatch.number}")
    top = height - 14 * mm
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(12 * mm, top, _fit((company.name if company else "").upper(), 50))
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(12 * mm, top - 11 * mm, "Parts sent for processing")
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(12 * mm, top - 19 * mm, dispatch.number)
    renderPDF.draw(_qr(dispatch.number), pdf, width - 54 * mm, top - 52 * mm)
    pdf.setFont("Helvetica", 10)
    lines = [
        f"To: {dispatch.supplier.name}",
        f"Date sent: {dispatch.sent_on:%d %b %Y}",
        f"Expected back: {dispatch.expected_on:%d %b %Y}" if dispatch.expected_on else "",
        f"Job: {job.number}",
        f"Part: {job.item.code if job.item_id else ''} {job.description}",
        f"Drawing: {job.drawing_no or '-'}  Rev {job.drawing_revision or '-'}",
        f"Work: Op {op.seq} {op.name}",
        f"Quantity: {_n(dispatch.quantity)} pieces",
        f"Notes: {dispatch.notes}" if dispatch.notes else "",
    ]
    y = top - 30 * mm
    for text in filter(None, lines):
        pdf.drawString(12 * mm, y, _fit(text, 50))
        y -= 6 * mm
    y = 40 * mm
    for label in ("Sent by", "Gate", "Received by the supplier"):
        pdf.line(12 * mm, y, 70 * mm, y)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(12 * mm, y - 4 * mm, label)
        y -= 12 * mm
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
