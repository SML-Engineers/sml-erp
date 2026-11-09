"""Inspection on jobs (backlog P3-14; spec 7.2, 6A.4).

- The QC Inspector inspects a released job after one of its operations: **first article**,
  **in process** or **final** (after the last operation). The checks come from the part's
  inspection plan (Phase 1.6: measured with a minimum and/or maximum, or pass/fail, some
  critical), copied when the inspection starts, and the inspector may add more; each check
  is entered for every piece checked (1 to 50).
- **Finish:** with every result entered, an inspection with all checks within limits
  passes; one with any check out **holds the job**: no work is entered on it, nothing is
  sent out and it is not completed until the Production Manager decides. The Production
  Managers of the division are told.
- **The Production Manager decides** (never the inspector), with a reason:
  - **rework** a number of pieces: they go back to the operation (no longer completed there);
  - **scrap** a number of pieces: they are rejected at the operation;
  - **accept under deviation**: the pieces go on as they are. When a critical check failed
    the Director approves it (approval engine "job_deviation"; owner, 8 Nov 2026, as for
    materials); a rejected request puts the job back on hold.
- Decided and passed inspections never change, results change only while inspecting
  (database).
"""

from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User
from apps.core.notifications import notify
from apps.inventory import inspections as incoming
from apps.inventory.inspections import InspectionError, ParameterInput

from . import job_cards
from .models import JobInspection, JobInspectionResult, JobOperation, JobOrder

DOC = "job_deviation"
St = JobInspection.Status
D = JobInspection.Decision
HOLDING = (St.ON_HOLD, St.DEVIATION_REQUESTED)
ZERO = Decimal("0")
QTY = Decimal("0.001")


class JobInspectionError(Exception):
    pass


def can_inspect(user: User) -> bool:
    return incoming.can_inspect(user)


def can_decide(user: User) -> bool:
    return effective_access(user).has("production_approvals", "approve")


def check_not_held(job: JobOrder) -> None:
    if job_cards.held(job):
        raise JobInspectionError(
            f"{job.number} is on hold after a failed inspection: the Production Manager decides "
            "first."
        )


def _text(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def _managers(job: JobOrder) -> list[User]:
    found = []
    for user in User.objects.filter(is_active=True).prefetch_related("divisions"):
        if can_decide(user) and division_scope(user).filter(pk=job.division_id).exists():
            found.append(user)
    return found


# --- Starting and entering -----------------------------------------------------------------------


def start(user: User, job: JobOrder, values: dict) -> JobInspection:
    if not can_inspect(user):
        raise JobInspectionError("Only the QC Inspector inspects jobs.")
    stage = _text(values.get("stage")).lower()
    if stage not in JobInspection.Stage.values:
        raise JobInspectionError("Choose first article, in process or final.")
    try:
        pieces = int(_text(values.get("pieces")) or 1)
    except ValueError:
        raise JobInspectionError("The pieces checked are a whole number.") from None
    if not 1 <= pieces <= 50:
        raise JobInspectionError("Check 1 to 50 pieces.")
    extra = []
    for row in values.get("checks") or []:
        extra.append(
            ParameterInput(
                name=_text(row.get("name")),
                kind=_text(row.get("kind") or "number"),
                minimum=row.get("minimum"),
                maximum=row.get("maximum"),
                unit=_text(row.get("unit")),
                critical=str(row.get("critical", "")).lower() in ("true", "1", "yes", "on"),
            )
        )
    with audit_context("job_inspection_started", job.number), transaction.atomic():
        job = JobOrder.objects.select_for_update().get(pk=job.pk)
        if job.status != JobOrder.Status.RELEASED:
            raise JobInspectionError(f"A released job is inspected; {job.number} is {job.status}.")
        ops = list(job.operations.order_by("seq"))
        if stage == JobInspection.Stage.FINAL:
            op = ops[-1] if ops else None
        else:
            try:
                op = job.operations.get(seq=int(_text(values.get("operation"))))
            except (ValueError, JobOperation.DoesNotExist):
                raise JobInspectionError(
                    f"Choose the operation of {job.number} it follows."
                ) from None
        if op is None:
            raise JobInspectionError(f"{job.number} has no operations.")
        if job.inspections.filter(status=St.DRAFT).exists():
            raise JobInspectionError(f"{job.number} has an inspection being done: finish it first.")
        plan = incoming.plan_for(job.item) if job.item_id else None
        checks = list(plan.parameters.all()) if plan else []
        try:
            checks += incoming._parameters(extra)
        except InspectionError as error:
            raise JobInspectionError(str(error)) from None
        if not checks:
            raise JobInspectionError(
                "There is no inspection plan for this part: add the checks to make."
            )
        inspection = JobInspection.objects.create(
            job=job, operation=op, stage=stage, plan=plan, pieces=pieces, inspector=user
        )
        JobInspectionResult.objects.bulk_create(
            JobInspectionResult(
                inspection=inspection,
                position=n,
                piece=piece,
                name=c.name,
                kind=c.kind,
                minimum=c.minimum,
                maximum=c.maximum,
                unit=c.unit,
                critical=c.critical,
            )
            for n, c in enumerate(checks, start=1)
            for piece in range(1, pieces + 1)
        )
        return inspection


def _limit(value, label: str) -> Decimal | None:
    text = _text(value).replace(",", "")
    if not text:
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise JobInspectionError(f"The {label} is not a number.") from None
    if not number.is_finite() or abs(number) >= Decimal("1e14"):
        raise JobInspectionError(f"The {label} is not a number.")
    return number.quantize(Decimal("0.0001"))


def _within(r: JobInspectionResult) -> bool | None:
    if r.kind == "pass_fail":
        return r.passed
    if r.value is None:
        return None
    if r.minimum is not None and r.value < r.minimum:
        return False
    return not (r.maximum is not None and r.value > r.maximum)


def _editable(user: User, inspection: JobInspection) -> JobInspection:
    inspection = JobInspection.objects.select_for_update().get(pk=inspection.pk)
    if inspection.status != St.DRAFT:
        raise JobInspectionError("This inspection is finished.")
    if inspection.inspector_id != user.pk or not can_inspect(user):
        raise JobInspectionError("Only the QC Inspector who started it enters the results.")
    return inspection


def save(user: User, inspection: JobInspection, values: dict) -> JobInspection:
    """Enter results: [{position, piece, value | passed, notes}], and notes."""
    with audit_context("job_inspection_saved"), transaction.atomic():
        inspection = _editable(user, inspection)
        rows = {(r.position, r.piece): r for r in inspection.results.all()}
        for given in values.get("results") or []:
            try:
                key = (int(given.get("position")), int(given.get("piece") or 1))
            except (TypeError, ValueError):
                raise JobInspectionError("Enter results for the inspection's checks.") from None
            r = rows.get(key)
            if r is None:
                raise JobInspectionError("Enter results for the inspection's checks.")
            if r.kind == "number":
                r.value = _limit(given.get("value"), f"result of {r.name}, piece {r.piece}")
            else:
                passed = given.get("passed")
                r.passed = (
                    None
                    if passed in (None, "")
                    else str(passed).lower() in ("true", "1", "yes", "pass")
                )
            r.notes = _text(given.get("notes"))[:300]
            r.within_limits = _within(r)
            r.save()
        if "notes" in values:
            inspection.notes = str(values.get("notes") or "")[:5000]
            inspection.save(update_fields=["notes"])
        return inspection


def finish(user: User, inspection: JobInspection) -> JobInspection:
    with audit_context("job_inspection_finished"), transaction.atomic():
        inspection = _editable(user, inspection)
        results = list(inspection.results.all())
        missing = [r for r in results if r.within_limits is None]
        if missing:
            raise JobInspectionError(
                f"Enter every result first: {missing[0].name}, piece {missing[0].piece}."
            )
        failed = [r for r in results if not r.within_limits]
        inspection.status = St.ON_HOLD if failed else St.PASSED
        inspection.inspected_at = timezone.now()
        inspection.save()
        if failed:
            job = inspection.job
            names = ", ".join(sorted({r.name for r in failed}))[:200]
            transaction.on_commit(
                lambda: notify(
                    _managers(job),
                    "job_on_hold",
                    title=f"{job.number} is on hold: {inspection.get_stage_display().lower()} "
                    "inspection failed",
                    body=f"{job.description}, after operation {inspection.operation.seq}: "
                    f"{names} out of limits. Decide: rework, scrap or accept under deviation.",
                    link=f"/job-orders?job={job.pk}",
                )
            )
        return inspection


# --- The Production Manager's decision -----------------------------------------------------------


def done_at(inspection: JobInspection) -> Decimal:
    """What the operation the inspection follows has completed (net of earlier decisions)."""
    step = next(
        (f for f in job_cards.flow(inspection.job) if f["operation"].pk == inspection.operation_id),
        None,
    )
    return step["completed"] if step else ZERO


def decide(user: User, inspection: JobInspection, values: dict) -> JobInspection:
    decision = _text(values.get("decision")).lower()
    reason = _text(values.get("reason"))[:300]
    with audit_context("job_inspection_decided", reason), transaction.atomic():
        inspection = JobInspection.objects.select_for_update().get(pk=inspection.pk)
        if inspection.status != St.ON_HOLD:
            raise JobInspectionError("This inspection is not waiting for a decision.")
        if (
            not can_decide(user)
            or not division_scope(user).filter(pk=inspection.job.division_id).exists()
        ):
            raise JobInspectionError("The Production Manager decides on a failed inspection.")
        if user.pk == inspection.inspector_id:
            raise JobInspectionError("The inspector does not decide on their own inspection.")
        if decision not in D.values:
            raise JobInspectionError("Decide: rework, scrap or accept under deviation.")
        if not reason:
            raise JobInspectionError("Give the reason for the decision.")
        quantity = ZERO
        if decision in (D.REWORK, D.SCRAP):
            text = _text(values.get("quantity")).replace(",", "")
            try:
                quantity = Decimal(text)
            except InvalidOperation:
                raise JobInspectionError("Give the number of pieces.") from None
            if not quantity.is_finite() or quantity <= 0 or quantity != quantity.quantize(QTY):
                raise JobInspectionError("The number of pieces is more than 0, at most 3 decimals.")
            done = done_at(inspection)
            if quantity > done:
                raise JobInspectionError(
                    f"Operation {inspection.operation.seq} has {job_cards._n(done)} pieces "
                    "completed to rework or scrap."
                )
        inspection.decision = decision
        inspection.decision_quantity = quantity
        inspection.decision_reason = reason
        inspection.decided_by = user
        inspection.decided_at = timezone.now()
        critical = inspection.results.filter(critical=True, within_limits=False).exists()
        if decision == D.DEVIATION and critical:
            inspection.status = St.DEVIATION_REQUESTED
            inspection.save()
            try:
                approvals.submit(
                    user,
                    DOC,
                    inspection.pk,
                    created_by=user,
                    division=inspection.job.division,
                    title=f"{inspection.job.number}: accept under deviation "
                    "(critical check failed)",
                    link=f"/job-orders?job={inspection.job_id}",
                    comment=reason,
                )
            except ApprovalError as error:
                raise JobInspectionError(str(error)) from None
        else:
            inspection.status = St.DECIDED
            inspection.save()
        return inspection


def director_decides(
    user: User, inspection: JobInspection, action: str, reason: str = ""
) -> JobInspection:
    """The Director approves or rejects a deviation on a failed critical check."""
    reason = _text(reason)
    with audit_context("job_deviation_decided", reason), transaction.atomic():
        inspection = JobInspection.objects.select_for_update().get(pk=inspection.pk)
        if inspection.status != St.DEVIATION_REQUESTED:
            raise JobInspectionError("This deviation is not waiting for approval.")
        try:
            if action == "approve":
                state = approvals.approve(user, DOC, inspection.pk, reason)
                if state.status != ApprovalState.Status.APPROVED:
                    return inspection
                inspection.status = St.DECIDED
            elif action == "reject":
                # Returned (not rejected for good): back on hold for the Production Manager to
                # decide again, perhaps the same deviation with more behind it.
                approvals.send_back(user, DOC, inspection.pk, reason)
                inspection.status = St.ON_HOLD
                inspection.decision = ""
                inspection.decision_reason = f"Director refused the deviation: {reason}"[:300]
                inspection.decided_by = None
                inspection.decided_at = None
            else:
                raise JobInspectionError("Approve or reject.")
        except ApprovalError as error:
            raise JobInspectionError(str(error)) from None
        inspection.save()
        return inspection


# --- Reading -------------------------------------------------------------------------------------


def rows(job: JobOrder, user: User) -> list[dict]:
    out = []
    for i in job.inspections.select_related(
        "operation", "inspector", "decided_by"
    ).prefetch_related("results"):
        state = approvals.state_of(DOC, i.pk) if i.status == St.DEVIATION_REQUESTED else None
        results = list(i.results.all())
        checks = {}
        for r in results:
            c = checks.setdefault(
                r.position,
                {
                    "position": r.position,
                    "name": r.name,
                    "kind": r.kind,
                    "minimum": job_cards._n(r.minimum) if r.minimum is not None else "",
                    "maximum": job_cards._n(r.maximum) if r.maximum is not None else "",
                    "unit": r.unit,
                    "critical": r.critical,
                    "pieces": [],
                },
            )
            c["pieces"].append(
                {
                    "piece": r.piece,
                    "value": job_cards._n(r.value) if r.value is not None else "",
                    "passed": r.passed,
                    "within_limits": r.within_limits,
                    "notes": r.notes,
                }
            )
        out.append(
            {
                "id": i.pk,
                "stage": i.stage,
                "stage_label": i.get_stage_display(),
                "operation": i.operation.seq,
                "operation_name": i.operation.name,
                "pieces": i.pieces,
                "status": i.status,
                "status_label": i.get_status_display(),
                "inspector": i.inspector.full_name,
                "inspected_at": i.inspected_at,
                "notes": i.notes,
                "checks": list(checks.values()),
                "failed": sorted({r.name for r in results if r.within_limits is False}),
                "decision": i.decision,
                "decision_label": i.get_decision_display() if i.decision else "",
                "decision_quantity": job_cards._n(i.decision_quantity),
                "decision_reason": i.decision_reason,
                "decided_by": i.decided_by.full_name if i.decided_by_id else "",
                "can_enter": i.status == St.DRAFT
                and i.inspector_id == user.pk
                and can_inspect(user),
                "can_decide": i.status == St.ON_HOLD
                and can_decide(user)
                and user.pk != i.inspector_id,
                "can_approve": state is not None and approvals.why_not(user, state) is None,
            }
        )
    return out
