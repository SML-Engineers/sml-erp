"""Incoming inspection and QC acceptance (backlog P16-08, spec 6A.3, 6A.4).

- Inspection plans, per item or per category, list the checks: measured (with a minimum
  and/or maximum) or pass/fail, some of them critical, and how many packages to sample. The
  QC Inspector sets them up.
- Every confirmed GRN line of an item that needs inspection waits in the QC queue. The QC
  Inspector starts an inspection (the checks are copied from the plan, rule 11), enters the
  results, attaches certificates, and decides:
  - Accept: all of it, or all but some packages (owner, 1 Nov 2026: decisions per package),
    or, for an item not received by package, a smaller accepted quantity.
  - Reject the whole line, with a reason.
  - Accept under deviation, with a reason, when a check failed: the Production Manager
    approves, and the Director when a critical check failed (owner, 8 Nov 2026; approval
    subtype "critical" or "standard").
  A failed critical check cannot simply be accepted.
- The QC Inspector is never the person who received or confirmed the GRN, and never changes
  received quantities. A decided inspection never changes (database guard).
- Items that need no inspection are accepted automatically when the GRN is confirmed.
- Accepted quantities become available stock and rejected ones go to the Rejected store with
  the stock movements of P16-09.
"""

import hashlib
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import F, QuerySet
from django.utils import timezone

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalState, User

from . import stock
from .models import (
    GoodsReceipt,
    GoodsReceiptLine,
    IncomingInspection,
    InspectionAttachment,
    InspectionParameter,
    InspectionPlan,
    InspectionResult,
    Item,
    RejectedPackage,
)
from .packages import PackageError, number
from .receipts import FILE_TYPES, MAX_FILE_BYTES

DOC = "quality_deviation"
St = IncomingInspection.Status
D = IncomingInspection.Decision
Kind = InspectionParameter.Kind
MAX_PARAMETERS = 50
MAX_ATTACHMENTS = 20


class InspectionError(Exception):
    pass


@dataclass
class ResultInput:
    position: int
    value: object = None
    passed: bool | None = None
    notes: str = ""


@dataclass
class ParameterInput:
    name: str
    kind: str
    minimum: object = None
    maximum: object = None
    unit: str = ""
    critical: bool = False


# --- Who may do what -----------------------------------------------------------------------


def can_inspect(user: User) -> bool:
    return effective_access(user).has("quality", "approve") and approvals.holds_role(
        user, "qc_inspector"
    )


def can_view(user: User) -> bool:
    return effective_access(user).has("quality", "view")


def visible(user: User) -> QuerySet[IncomingInspection]:
    if not can_view(user):
        return IncomingInspection.objects.none()
    return IncomingInspection.objects.filter(
        line__receipt__division__in=division_scope(user)
    ).select_related("line__receipt__supplier", "line__item", "inspector")


def queue(user: User) -> QuerySet[GoodsReceiptLine]:
    """Confirmed GRN lines waiting for QC."""
    if not can_view(user):
        return GoodsReceiptLine.objects.none()
    return (
        GoodsReceiptLine.objects.filter(
            receipt__status=GoodsReceipt.Status.CONFIRMED,
            receipt__division__in=division_scope(user),
            item__inspection_required=True,
            received_quantity__gt=F("damaged_quantity"),
        )
        .exclude(inspection__status__in=(St.DECIDED, St.DEVIATION_REQUESTED))
        .select_related("receipt__supplier", "item")
        .order_by("receipt__confirmed_at", "line_no")
    )


def _not_receiver(user: User, line: GoodsReceiptLine) -> None:
    grn = line.receipt
    if user.pk in (grn.created_by_id, grn.confirmed_by_id):
        raise InspectionError(
            "The person who received the goods cannot also inspect them (segregation of duties)."
        )


def can_edit(user: User, inspection: IncomingInspection) -> bool:
    return (
        inspection.status == St.DRAFT
        and can_inspect(user)
        and user.pk
        not in (inspection.line.receipt.created_by_id, inspection.line.receipt.confirmed_by_id)
    )


def can_approve(user: User, inspection: IncomingInspection) -> bool:
    if inspection.status != St.DEVIATION_REQUESTED:
        return False
    state = approvals.state_of(DOC, inspection.pk)
    return state is not None and approvals.why_not(user, state) is None


# --- Plans ---------------------------------------------------------------------------------


def plan_for(item: Item) -> InspectionPlan | None:
    return (
        InspectionPlan.objects.filter(item=item, is_active=True).first()
        or InspectionPlan.objects.filter(
            item__isnull=True, category=item.category, is_active=True
        ).first()
    )


def _limit(value, what: str) -> Decimal | None:
    """A typed limit or result, which may be negative; None when left empty."""
    if value is None or str(value).strip() == "":
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise InspectionError(f"The {what} is not a number.") from None
    if not result.is_finite() or abs(result) >= Decimal(10) ** 12:
        raise InspectionError(f"The {what} is not a usable number.")
    if result != result.quantize(Decimal("0.0001")):
        raise InspectionError(f"The {what} can have at most 4 decimal places.")
    return result


def _plan_values(plan: InspectionPlan, values: dict) -> None:
    if "name" in values:
        plan.name = (values["name"] or "").strip()[:100]
    if not plan.name:
        raise InspectionError("Give the plan a name.")
    if "item" in values or "category" in values:
        item = values.get("item")
        category = (values.get("category") or "").strip()
        if bool(item) == bool(category):
            raise InspectionError("A plan is for one item or for one category of items.")
        if category and category not in Item.Category.values:
            raise InspectionError("Choose the category.")
        plan.item = item or None
        plan.category = "" if item else category
    if plan.item_id is None and not plan.category:
        raise InspectionError("A plan is for one item or for one category of items.")
    if "sampling" in values:
        if values["sampling"] not in InspectionPlan.Sampling.values:
            raise InspectionError("Choose how packages are sampled.")
        plan.sampling = values["sampling"]
    if "sample_value" in values or "sampling" in values:
        raw = values.get("sample_value", plan.sample_value)
        if plan.sampling == InspectionPlan.Sampling.ALL:
            plan.sample_value = None
        else:
            try:
                value = number(raw, "sample size", 2, positive=True)
            except PackageError as error:
                raise InspectionError(str(error)) from None
            if value is None:
                raise InspectionError("Give the number or percentage of packages to sample.")
            if plan.sampling == InspectionPlan.Sampling.FIXED and value != value.to_integral():
                raise InspectionError("The number of packages to sample is a whole number.")
            if plan.sampling == InspectionPlan.Sampling.PERCENT and value > 100:
                raise InspectionError("The percentage to sample is at most 100.")
            plan.sample_value = value
    if "notes" in values:
        plan.notes = (values["notes"] or "").strip()


def _parameters(given: list[ParameterInput]) -> list[InspectionParameter]:
    if len(given) > MAX_PARAMETERS:
        raise InspectionError(f"A plan can have at most {MAX_PARAMETERS} checks.")
    rows = []
    for n, p in enumerate(given, start=1):
        where = f"Check {n}: "
        name = (p.name or "").strip()[:100]
        if not name:
            raise InspectionError(where + "give it a name.")
        if p.kind not in Kind.values:
            raise InspectionError(where + "choose measured or pass/fail.")
        try:
            low = _limit(p.minimum, "minimum")
            high = _limit(p.maximum, "maximum")
        except InspectionError as error:
            raise InspectionError(where + str(error)) from None
        if p.kind == Kind.NUMBER:
            if low is None and high is None:
                raise InspectionError(where + "give the minimum, the maximum or both.")
            if low is not None and high is not None and low > high:
                raise InspectionError(where + "the minimum is more than the maximum.")
        else:
            low = high = None
        rows.append(
            InspectionParameter(
                position=n,
                name=name,
                kind=p.kind,
                minimum=low,
                maximum=high,
                unit=(p.unit or "").strip()[:20] if p.kind == Kind.NUMBER else "",
                critical=bool(p.critical),
            )
        )
    return rows


def _active_clash(plan: InspectionPlan) -> None:
    if not plan.is_active:
        return
    others = InspectionPlan.objects.filter(is_active=True).exclude(pk=plan.pk)
    if plan.item_id and others.filter(item=plan.item).exists():
        raise InspectionError(f"Item {plan.item.code} already has an active plan.")
    if plan.category and others.filter(item__isnull=True, category=plan.category).exists():
        raise InspectionError(
            f"The category {plan.get_category_display().lower()} already has an active plan."
        )


def save_plan(
    user: User, plan: InspectionPlan | None, values: dict, parameters: list[ParameterInput]
) -> InspectionPlan:
    if not can_inspect(user):
        raise InspectionError("Only the QC Inspector sets up inspection plans.")
    event = "inspection_plan_changed" if plan else "inspection_plan_created"
    with audit_context(event), transaction.atomic():
        if plan is None:
            plan = InspectionPlan(created_by=user)
        else:
            plan = InspectionPlan.objects.select_for_update().get(pk=plan.pk)
        _plan_values(plan, values)
        if "is_active" in values:
            plan.is_active = bool(values["is_active"])
        _active_clash(plan)
        rows = _parameters(parameters)
        plan.updated_at = timezone.now()
        plan.save()
        plan.parameters.all().delete()
        for row in rows:
            row.plan = plan
            row.save()
        return plan


# --- Inspecting ----------------------------------------------------------------------------


def _sample_size(plan: InspectionPlan | None, line: GoodsReceiptLine) -> int:
    count = line.packages.count() or 1
    if plan is None or plan.sampling == InspectionPlan.Sampling.ALL:
        return count
    if plan.sampling == InspectionPlan.Sampling.FIXED:
        return min(count, int(plan.sample_value))
    return max(1, min(count, math.ceil(count * plan.sample_value / 100)))


def good_quantity(line: GoodsReceiptLine) -> Decimal:
    return line.received_quantity - line.damaged_quantity


def start(user: User, line: GoodsReceiptLine) -> IncomingInspection:
    if not can_inspect(user):
        raise InspectionError("Only the QC Inspector inspects received goods.")
    with audit_context("inspection_started"), transaction.atomic():
        line = queue(user).select_for_update(of=("self",)).filter(pk=line.pk).first()
        if line is None:
            raise InspectionError("This GRN line is not waiting for QC.")
        _not_receiver(user, line)
        existing = IncomingInspection.objects.filter(line=line).first()
        if existing is not None:
            return existing
        plan = plan_for(line.item)
        inspection = IncomingInspection.objects.create(
            line=line,
            plan=plan,
            sample_size=_sample_size(plan, line),
            accepted_quantity=good_quantity(line),
            inspector=user,
        )
        for p in plan.parameters.all() if plan else []:
            InspectionResult.objects.create(
                inspection=inspection,
                position=p.position,
                name=p.name,
                kind=p.kind,
                minimum=p.minimum,
                maximum=p.maximum,
                unit=p.unit,
                critical=p.critical,
            )
        return inspection


def _within(result: InspectionResult) -> bool | None:
    if result.kind == Kind.PASS_FAIL:
        return result.passed
    if result.value is None:
        return None
    if result.minimum is not None and result.value < result.minimum:
        return False
    return not (result.maximum is not None and result.value > result.maximum)


def save(
    user: User,
    inspection: IncomingInspection,
    *,
    results: list[ResultInput],
    accepted_quantity=None,
    rejected_packages: list[int] | None = None,
    notes: str | None = None,
) -> IncomingInspection:
    with audit_context("inspection_changed"), transaction.atomic():
        inspection = IncomingInspection.objects.select_for_update().get(pk=inspection.pk)
        line = inspection.line
        if not can_edit(user, inspection):
            raise InspectionError("Only the QC Inspector changes an inspection in progress.")
        by_position = {r.position: r for r in inspection.results.all()}
        for given in results:
            result = by_position.get(given.position)
            if result is None:
                raise InspectionError("Enter results only for the plan's checks.")
            if result.kind == Kind.NUMBER:
                result.value = _limit(given.value, f"result of {result.name}")
            else:
                result.passed = given.passed
            result.notes = (given.notes or "").strip()[:300]
            result.within_limits = _within(result)
            result.save()
        good = good_quantity(line)
        packages = {p.package_no: p for p in line.packages.all()}
        if packages:
            chosen = sorted(set(rejected_packages or []))
            rows = []
            for package_no in chosen:
                package = packages.get(package_no)
                if package is None:
                    raise InspectionError(f"There is no package {package_no} on this line.")
                if package.damaged:
                    raise InspectionError(
                        f"Package {package.lot_no} was received damaged: it is already set aside."
                    )
                rows.append(package)
            inspection.rejected_packages.all().delete()
            for package in rows:
                RejectedPackage.objects.create(inspection=inspection, package=package)
            rejected = sum((p.quantity or 0 for p in rows), Decimal("0"))
            inspection.rejected_quantity = rejected
            inspection.accepted_quantity = good - rejected
        elif accepted_quantity is not None:
            try:
                accepted = number(accepted_quantity, "accepted quantity")
            except PackageError as error:
                raise InspectionError(str(error)) from None
            if accepted is None or accepted > good:
                raise InspectionError(
                    "The accepted quantity is between 0 and the good quantity received "
                    f"({good.normalize():f})."
                )
            inspection.accepted_quantity = accepted
            inspection.rejected_quantity = good - accepted
        if notes is not None:
            inspection.notes = notes.strip()[:5000]
        inspection.inspector = user
        inspection.save()
        return inspection


def _all_entered(inspection: IncomingInspection) -> list[InspectionResult]:
    results = list(inspection.results.all())
    blank = [r.name for r in results if r.within_limits is None]
    if blank:
        raise InspectionError("Enter every check's result first: " + ", ".join(blank) + ".")
    return results


def decide(user: User, inspection: IncomingInspection, decision: str, reason: str = ""):
    reason = (reason or "").strip()
    with audit_context(f"inspection_{decision}", reason), transaction.atomic():
        inspection = IncomingInspection.objects.select_for_update().get(pk=inspection.pk)
        if not can_edit(user, inspection):
            raise InspectionError("Only the QC Inspector decides on an inspection in progress.")
        good = good_quantity(inspection.line)
        if decision == D.REJECTED:
            if not reason:
                raise InspectionError("Give a reason for rejecting the goods.")
            inspection.rejected_packages.all().delete()
            inspection.accepted_quantity = Decimal("0")
            inspection.rejected_quantity = good
        elif decision in (D.ACCEPTED, D.DEVIATION):
            results = _all_entered(inspection)
            if inspection.accepted_quantity == 0:
                raise InspectionError("Nothing is accepted: reject the goods instead.")
            failed = [r for r in results if r.within_limits is False]
            if decision == D.ACCEPTED and any(r.critical for r in failed):
                names = ", ".join(r.name for r in failed if r.critical)
                raise InspectionError(
                    f"A critical check failed ({names}): reject the goods or ask the Director "
                    "to accept them under deviation."
                )
            if decision == D.DEVIATION:
                if not failed:
                    raise InspectionError("No check failed: accept the goods instead.")
                if not reason:
                    raise InspectionError("Give the reason for accepting under deviation.")
                line = inspection.line
                subtype = "critical" if any(r.critical for r in failed) else "standard"
                try:
                    if subtype == "critical":
                        route = approvals.route_for(
                            DOC, division=line.receipt.division, subtype=subtype
                        )
                        if route[-1]["role"] != "director":
                            raise InspectionError(
                                "A deviation on a failed critical check is approved by the "
                                "Director: ask the Admin to correct the approval matrix."
                            )
                    approvals.submit(
                        user,
                        DOC,
                        inspection.pk,
                        created_by=user,
                        amount=None,
                        division=line.receipt.division,
                        subtype=subtype,
                        comment=reason,
                        title=(
                            f"Accept {line.item.code} of {line.receipt.number} under deviation: "
                            + ", ".join(r.name for r in failed)
                        )[:200],
                        link=f"/inspections/{inspection.pk}",
                    )
                except ApprovalError as error:
                    raise InspectionError(str(error)) from None
                inspection.status = St.DEVIATION_REQUESTED
                inspection.reason = reason[:5000]
                inspection.inspector = user
                inspection.save()
                return inspection
        else:
            raise InspectionError("Choose accept, reject or accept under deviation.")
        inspection.reason = reason[:5000]
        inspection.inspector = user
        inspection.save()
        inspection.status = St.DECIDED
        inspection.decision = decision
        inspection.decided_at = timezone.now()
        inspection.save(update_fields=["status", "decision", "decided_at"])
        _to_stock(user, inspection)
        return inspection


def approve_deviation(user: User, inspection: IncomingInspection, comment: str = ""):
    with transaction.atomic():
        inspection = IncomingInspection.objects.select_for_update().get(pk=inspection.pk)
        if inspection.status != St.DEVIATION_REQUESTED:
            raise InspectionError("No deviation of this inspection is waiting for the Director.")
        try:
            state = approvals.approve(user, DOC, inspection.pk, comment)
        except ApprovalError as error:
            raise InspectionError(str(error)) from None
        if state.status == ApprovalState.Status.APPROVED:
            with audit_context("inspection_deviation_approved", comment):
                inspection.status = St.DECIDED
                inspection.decision = D.DEVIATION
                inspection.decided_at = timezone.now()
                inspection.save(update_fields=["status", "decision", "decided_at"])
                _to_stock(user, inspection)
        return inspection


def send_back(user: User, inspection: IncomingInspection, reason: str):
    """The Director does not accept the deviation: QC rejects the goods or inspects again."""
    with transaction.atomic():
        inspection = IncomingInspection.objects.select_for_update().get(pk=inspection.pk)
        if inspection.status != St.DEVIATION_REQUESTED:
            raise InspectionError("No deviation of this inspection is waiting for the Director.")
        try:
            approvals.send_back(user, DOC, inspection.pk, reason)
        except ApprovalError as error:
            raise InspectionError(str(error)) from None
        with audit_context("inspection_deviation_returned", reason):
            inspection.status = St.DRAFT
            inspection.save(update_fields=["status"])
        return inspection


def _to_stock(user: User, inspection: IncomingInspection) -> None:
    try:
        stock.decide(user, inspection)
    except stock.StockError as error:
        raise InspectionError(str(error)) from None


def accept_automatically(user: User, line: GoodsReceiptLine) -> None:
    """Called when a GRN is confirmed: an item that needs no inspection is accepted as it is."""
    good = good_quantity(line)
    if line.item.inspection_required or good <= 0:
        return
    inspection = IncomingInspection.objects.create(
        line=line,
        sample_size=0,
        status=St.DECIDED,
        decision=D.ACCEPTED,
        accepted_quantity=good,
        automatic=True,
        notes="No inspection needed for this item.",
        decided_at=timezone.now(),
    )
    _to_stock(user, inspection)


def blocks_reversal(grn: GoodsReceipt) -> bool:
    """QC has started on the GRN: it can no longer simply be reversed."""
    return IncomingInspection.objects.filter(line__receipt=grn, automatic=False).exists()


# --- Certificates and photos ---------------------------------------------------------------


def add_attachment(user: User, inspection: IncomingInspection, uploaded) -> InspectionAttachment:
    with audit_context("inspection_attachment_added"), transaction.atomic():
        inspection = IncomingInspection.objects.select_for_update().get(pk=inspection.pk)
        if not can_inspect(user) or inspection.automatic:
            raise InspectionError("Only the QC Inspector adds certificates to an inspection.")
        if inspection.attachments.count() >= MAX_ATTACHMENTS:
            raise InspectionError(f"An inspection can have at most {MAX_ATTACHMENTS} files.")
        if uploaded.size > MAX_FILE_BYTES:
            raise InspectionError("The file is larger than 20 MB.")
        content = uploaded.read()
        kind = next((k for magic, k in FILE_TYPES.items() if content.startswith(magic)), None)
        if kind is None:
            raise InspectionError("Only JPG, PNG and PDF files can be added.")
        content_type, extension = kind
        digest = hashlib.sha256(content).hexdigest()
        name = (uploaded.name or f"certificate{extension}").replace("/", "_").replace("\\", "_")
        uploaded.seek(0)
        attachment = InspectionAttachment(
            inspection=inspection,
            file_name=name[-200:],
            content_type=content_type,
            size=len(content),
            sha256=digest,
            uploaded_by=user,
        )
        attachment.file.save(f"QC{inspection.pk}-{digest[:12]}{extension}", uploaded, save=False)
        attachment.save()
        return attachment


def remove_attachment(user: User, attachment: InspectionAttachment) -> None:
    with audit_context("inspection_attachment_removed"), transaction.atomic():
        inspection = IncomingInspection.objects.select_for_update().get(pk=attachment.inspection_id)
        if not can_edit(user, inspection):
            raise InspectionError("A file is removed only while the inspection is in progress.")
        attachment.file.delete(save=False)
        attachment.delete()
