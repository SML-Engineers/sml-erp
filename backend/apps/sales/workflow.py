"""Approval, revisions and status of quotations (backlog P15-06, spec 5.1, 3).

Draft → Awaiting approval → Approved → Sent → Accepted, or Lost (with a reason), or Expired
(a daily job, once the validity date has passed).

- Every quotation is approved by the Director before it is printed or sent, by email or
  otherwise (owner, 31 Oct 2026), through the shared approval engine ("quotation"). The
  Director may return it to its creator with a reason; it is then a draft again.
- The division's confirmed quotation limits are shown to the Director as warnings, with
  lines not costed and prices below cost: they never block approval.
- Segregation of duties (rule 5): nobody approves a quotation they made (the engine and the
  database refuse it).
- Once out of draft a quotation never changes (database guard); a change is a revision: the
  same number with Rev 1, Rev 2, …, and the earlier one is marked "Replaced by a revision".
- Win and loss reasons are kept for the sales reports.
"""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core import approvals
from apps.core.access import effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.masters.limits import DEFAULT_MIN_MARGIN, in_force
from apps.masters.services import MastersError

from . import costing, services
from .models import (
    OutcomeReason,
    Quotation,
    QuotationCosting,
    QuotationCostingExtra,
    QuotationCostingOperation,
    QuotationFile,
    QuotationImage,
)
from .services import BreakInput, LineInput, SalesError, can_enter

DOC = "quotation"
CENT = Decimal("0.01")
S = Quotation.Status
FINAL = (S.APPROVED, S.SENT, S.ACCEPTED)  # may be printed as final or emailed (P15-07)
OPEN_FOR_OUTCOME = (S.APPROVED, S.SENT, S.EXPIRED)
REVISABLE = (S.APPROVED, S.SENT, S.EXPIRED, S.LOST)


def is_final(quotation: Quotation) -> bool:
    """Approved by the Director: may be printed without the NOT APPROVED mark, and emailed."""
    return quotation.status in FINAL


def _manages(user: User) -> bool:
    return effective_access(user).has("sales", "approve")


def _owner_or_manager(user: User, quotation: Quotation) -> bool:
    if not services.visible(user).filter(pk=quotation.pk).exists():
        return False
    return quotation.created_by_id == user.pk or _manages(user)


def can_submit(user: User, quotation: Quotation) -> bool:
    return services.can_edit(user, quotation)


def can_approve(user: User, quotation: Quotation) -> bool:
    state = approvals.state_of(DOC, quotation.pk)
    return (
        quotation.status == S.AWAITING_APPROVAL
        and state is not None
        and approvals.why_not(user, state) is None
    )


def can_mark_sent(user: User, quotation: Quotation) -> bool:
    return quotation.status == S.APPROVED and _owner_or_manager(user, quotation)


def can_record_outcome(user: User, quotation: Quotation) -> bool:
    return quotation.status in OPEN_FOR_OUTCOME and _owner_or_manager(user, quotation)


def can_revise(user: User, quotation: Quotation) -> bool:
    return quotation.status in REVISABLE and quotation.created_by_id == user.pk and can_enter(user)


# --- What the Director is warned about --------------------------------------------------


def review(quotation: Quotation) -> dict:
    """The quotation's overall margin (from its costing, at each line's quantity), its value
    in LKR before tax, and the warnings shown to the Director."""
    warnings = []
    cost_total = tooling_total = revenue = Decimal("0")
    lines = quotation.lines.prefetch_related("breaks").select_related("costing")
    for line in lines:
        line_costing = getattr(line, "costing", None)
        if line_costing is None:
            if not line.is_tooling:
                warnings.append(f"Line {line.line_no} has no costing.")
            continue
        rows = costing.results(line_costing, line, quotation.exchange_rate)
        first = rows[0]
        cost_total += first["cost"] * line.quantity
        tooling_total += first["tooling"] * line.quantity
        revenue += first["quoted_price_lkr"] * line.quantity
        for row in rows:
            if row["below_cost"]:
                warnings.append(
                    f"Line {line.line_no}: the price for {row['quantity'].normalize():f} is "
                    "below cost."
                )
    margin = None
    if cost_total > 0:
        margin = ((revenue - tooling_total - cost_total) / cost_total * 100).quantize(
            CENT, ROUND_HALF_UP
        )
    value_lkr = (quotation.subtotal * quotation.exchange_rate).quantize(CENT, ROUND_HALF_UP)
    # With no confirmed limits the defaults apply: 1% minimum margin, no maximum value.
    limit = in_force(quotation.division, quotation.quote_date)
    minimum = limit.min_margin_pct if limit else DEFAULT_MIN_MARGIN
    maximum = limit.director_above_lkr if limit else None
    if margin is not None and margin < minimum:
        warnings.append(f"Margin {margin}% is below the minimum of {minimum}%.")
    if maximum is not None and value_lkr > maximum:
        warnings.append(f"Value LKR {value_lkr:,} is above the limit of LKR {maximum:,}.")
    if quotation.valid_until < timezone.localdate() and quotation.status in (
        S.DRAFT,
        S.AWAITING_APPROVAL,
    ):
        warnings.append("The validity date has passed.")
    return {
        "margin_pct": margin,
        "value_lkr": value_lkr,
        "min_margin_pct": minimum,
        "limit_lkr": maximum,
        "warnings": warnings,
    }


# --- Moving through the statuses --------------------------------------------------------


def _locked(quotation: Quotation) -> Quotation:
    return Quotation.objects.select_for_update().get(pk=quotation.pk)


def _engine(call, *args, **kwargs):
    try:
        return call(*args, **kwargs)
    except ApprovalError as error:
        raise SalesError(str(error)) from None


def submit(user: User, quotation: Quotation, comment: str = "") -> Quotation:
    """The creator sends the draft to the Director (again, after it was returned)."""
    with audit_context("quotation_submitted", comment), transaction.atomic():
        quotation = _locked(quotation)
        if not can_submit(user, quotation):
            raise SalesError("Only the person who made a draft quotation sends it for approval.")
        if quotation.valid_until < timezone.localdate():
            raise SalesError("The validity date has passed. Change it before sending for approval.")
        _engine(
            approvals.submit,
            user,
            DOC,
            quotation.pk,
            created_by=quotation.created_by,
            amount=quotation.total_lkr,
            division=quotation.division,
            comment=comment,
            title=f"Quotation {quotation.label} for {quotation.customer.name}",
            link=f"/quotations/{quotation.pk}",
        )
        quotation.status = S.AWAITING_APPROVAL
        quotation.save(update_fields=["status"])
        return quotation


def approve(user: User, quotation: Quotation, comment: str = "") -> Quotation:
    with transaction.atomic():
        quotation = _locked(quotation)
        if quotation.status != S.AWAITING_APPROVAL:
            raise SalesError("The quotation is not waiting for approval.")
        state = _engine(approvals.approve, user, DOC, quotation.pk, comment)
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("quotation_approved", comment):
                quotation.status = S.APPROVED
                quotation.approved_at = timezone.now()
                quotation.save(update_fields=["status", "approved_at"])
        return quotation


def send_back(user: User, quotation: Quotation, reason: str) -> Quotation:
    """The approver returns the quotation to its creator, who changes it and sends it again."""
    with transaction.atomic():
        quotation = _locked(quotation)
        if quotation.status != S.AWAITING_APPROVAL:
            raise SalesError("The quotation is not waiting for approval.")
        _engine(approvals.send_back, user, DOC, quotation.pk, reason)
        with audit_context("quotation_returned", reason):
            quotation.status = S.DRAFT
            quotation.save(update_fields=["status"])
        return quotation


def mark_sent(user: User, quotation: Quotation, *, when=None) -> Quotation:
    """Record that the approved quotation went to the customer (by hand or post; P15-07 does
    this itself when it emails)."""
    with audit_context("quotation_sent"), transaction.atomic():
        quotation = _locked(quotation)
        if quotation.status != S.APPROVED:
            raise SalesError("Only an approved quotation can be sent to the customer.")
        if not _owner_or_manager(user, quotation):
            raise SalesError("The quotation's creator or the Sales Manager marks it sent.")
        quotation.status = S.SENT
        quotation.sent_at = when or timezone.now()
        quotation.sent_by = user
        quotation.save(update_fields=["status", "sent_at", "sent_by"])
        return quotation


def record_outcome(
    user: User, quotation: Quotation, *, accepted: bool, reason: str = "", note: str = ""
) -> Quotation:
    """Won or lost, and why. A loss needs its reason (and a note when the reason is Other)."""
    reason = (reason or "").strip()
    note = (note or "").strip()[:2000]
    if reason and reason not in OutcomeReason.values:
        raise SalesError("Choose one of the reasons.")
    if not accepted and not reason:
        raise SalesError("Give the reason the quotation was lost.")
    if reason == OutcomeReason.OTHER and not note:
        raise SalesError("Say what the other reason was.")
    event = "quotation_accepted" if accepted else "quotation_lost"
    with audit_context(event, note or reason), transaction.atomic():
        quotation = _locked(quotation)
        if quotation.status not in OPEN_FOR_OUTCOME:
            raise SalesError(
                "Only an approved, sent or expired quotation can be marked won or lost."
            )
        if not _owner_or_manager(user, quotation):
            raise SalesError("The quotation's creator or the Sales Manager records the outcome.")
        quotation.status = S.ACCEPTED if accepted else S.LOST
        quotation.outcome_reason = reason
        quotation.outcome_note = note
        quotation.outcome_at = timezone.now()
        quotation.outcome_by = user
        quotation.save(
            update_fields=["status", "outcome_reason", "outcome_note", "outcome_at", "outcome_by"]
        )
        return quotation


def revise(user: User, quotation: Quotation) -> Quotation:
    """A new draft with the same number and the next revision, dated today, with the same
    customer, terms, lines, drawings and costing. The earlier one is kept as it was offered,
    marked "Replaced by a revision". Prices, taxes and the exchange rate are worked out again
    for today; the costing keeps the rates it was made with until it is saved again."""
    with audit_context("quotation_revised"), transaction.atomic():
        old = _locked(quotation)
        if not can_revise(user, old):
            if old.created_by_id != user.pk:
                raise SalesError("Only the person who made the quotation revises it.")
            raise SalesError(
                "Only an approved, sent, expired or lost quotation is revised; change a draft "
                "directly."
            )
        today = timezone.localdate()
        latest = Quotation.objects.filter(number=old.number).aggregate(top=Max("revision"))["top"]
        new = Quotation.objects.create(
            number=old.number,
            revision=latest + 1,
            parent=old,
            division=old.division,
            customer=old.customer,
            contact=old.contact if old.contact and old.contact.is_active else None,
            enquiry_ref=old.enquiry_ref,
            quote_date=today,
            valid_until=today + (old.valid_until - old.quote_date),
            currency=old.currency,
            payment_terms=old.payment_terms,
            delivery_lead_time=old.delivery_lead_time,
            incoterm=old.incoterm,
            notes=old.notes,
            discount_pct=old.discount_pct,
            created_by=user,
        )
        old_lines = list(old.lines.prefetch_related("breaks").select_related("tax_code"))
        try:
            new = services.save(
                user,
                new,
                lines=[
                    LineInput(
                        description=line.description,
                        quantity=line.quantity,
                        unit_price=line.unit_price,
                        drawing_no=line.drawing_no,
                        drawing_rev=line.drawing_rev,
                        unit=line.unit,
                        min_order_qty=line.min_order_qty,
                        tax_code=line.tax_code,
                        breaks=[BreakInput(b.quantity, b.unit_price) for b in line.breaks.all()],
                        is_tooling=line.is_tooling,
                    )
                    for line in old_lines
                ],
            )
        except MastersError as error:
            raise SalesError(str(error)) from None
        new_lines = {line.line_no: line for line in new.lines.all()}
        for line in old_lines:
            _copy_costing(line, new_lines[line.line_no])
        for record in old.files.all():
            QuotationFile.objects.create(
                quotation=new,
                line_no=record.line_no,
                file=record.file.name,
                file_name=record.file_name,
                content_type=record.content_type,
                size=record.size,
                sha256=record.sha256,
                uploaded_by=record.uploaded_by,
                uploaded_at=record.uploaded_at,
            )
        for picture in old.images.all():
            QuotationImage.objects.create(
                quotation=new,
                file=picture.file.name,
                file_name=picture.file_name,
                content_type=picture.content_type,
                size=picture.size,
                sha256=picture.sha256,
                uploaded_by=picture.uploaded_by,
                uploaded_at=picture.uploaded_at,
            )
        old.status = S.REVISED
        old.save(update_fields=["status"])
        return new


def _copy_costing(old_line, new_line) -> None:
    source = getattr(old_line, "costing", None)
    if source is None:
        return
    copied = QuotationCosting.objects.get(pk=source.pk)
    operations = list(source.operations.all())
    extras = list(source.extras.all())
    copied.pk = None
    copied.id = None
    copied.line = new_line
    copied.save()
    for op in operations:
        QuotationCostingOperation.objects.create(
            costing=copied,
            seq=op.seq,
            machine=op.machine,
            description=op.description,
            minutes=op.minutes,
            rate=op.rate,
        )
    for extra in extras:
        QuotationCostingExtra.objects.create(
            costing=copied,
            seq=extra.seq,
            description=extra.description,
            amount=extra.amount,
            per_order=extra.per_order,
        )


def expire_due(today: date | None = None) -> int:
    """Daily: approved and sent quotations past their validity date become Expired."""
    today = today or timezone.localdate()
    count = 0
    due = Quotation.objects.filter(status__in=(S.APPROVED, S.SENT), valid_until__lt=today)
    for quotation in due:
        with audit_context("quotation_expired"), transaction.atomic():
            quotation = _locked(quotation)
            if quotation.status in (S.APPROVED, S.SENT):
                quotation.status = S.EXPIRED
                quotation.save(update_fields=["status"])
                count += 1
    return count


def revisions(quotation: Quotation) -> list[Quotation]:
    """Every revision of the quotation's number, oldest first."""
    return list(Quotation.objects.filter(number=quotation.number).order_by("revision"))
