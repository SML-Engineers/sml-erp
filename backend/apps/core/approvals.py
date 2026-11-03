"""The shared approval engine (spec 3, backlog P0-17).

One engine serves vouchers, quotations, purchase orders, shift reports and corrections. A
document module calls `submit()` when its creator sends it for approval, then `approve()`,
`send_back()` (Return) or `reject()` as approvers act, and keeps its own status in step with
the result. Every action writes one row to the insert-only approval log.

The route comes from the approval matrix: for each level, the role whose rule matches the
document (amount range, division, sub-type). It is copied onto the document when submitted,
so a later matrix change never alters a document already on its way.

Segregation of duties (rule 5), also enforced by the database: nobody approves a document
they created or submitted, and nobody approves the same document at two levels. Return and
Reject need a reason. Vouchers always pass the Accountant and then the Director (rule 6).
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .access import division_scope, effective_access
from .audit import _ip, audit_context
from .models import (
    ApprovalLog,
    ApprovalReminder,
    ApprovalRule,
    ApprovalState,
    Division,
    Notification,
    Role,
    User,
    UserRole,
)

SUBMIT_LEVEL = 1


@dataclass(frozen=True)
class DocumentType:
    name: str
    # The fewest approval levels a route may have, and the role that must approve last.
    min_approvals: int = 1
    final_role: str = ""
    subtype_label: str = ""
    # A special action that also lets its holder approve at the final role's level: held by
    # that role by default and granted to chosen people one by one (a sensitive grant the
    # Director confirms), e.g. credit notes (owner, 3 Nov 2026).
    approver_action: str = ""


# Document types come with the software; each module registers its own when it is built.
DOCUMENT_TYPES = {
    "voucher": DocumentType(
        "Payment voucher", min_approvals=2, final_role="director", subtype_label="Voucher type"
    ),
    # The Accountant requests, the Director approves (spec 4.2, P1-06).
    "voucher_cancellation": DocumentType(
        "Voucher cancellation", min_approvals=1, final_role="director", subtype_label="Voucher type"
    ),
    # Every quotation is approved by the Director before it is printed or sent (owner, 31 Oct
    # 2026; P15-06).
    "quotation": DocumentType("Quotation", min_approvals=1, final_role="director"),
    # Recorded by the Cashier; the Accountant's approval is enough (owner, 31 Oct 2026; P15-09),
    # or that of a person the Admin gives "approve_customer_receipts" to and the Director
    # confirms (owner, 3 Nov 2026).
    "customer_advance": DocumentType(
        "Customer advance",
        min_approvals=1,
        final_role="accountant",
        approver_action="approve_customer_receipts",
    ),
    # A repeat order entered without a quotation: the Director approves its prices (P15-10).
    "sales_order": DocumentType("Sales order", min_approvals=1, final_role="director"),
    # Every purchase order is approved by the Director before it is sent (owner, 31 Oct 2026;
    # P16-04).
    "purchase_order": DocumentType("Purchase order", min_approvals=1, final_role="director"),
    # Goods above what the PO still expects are accepted only with the Director (owner, 31 Oct
    # 2026; P16-06); so is reversing a confirmed goods receiving note.
    "goods_receipt": DocumentType("GRN with excess", min_approvals=1, final_role="director"),
    "goods_receipt_reversal": DocumentType("GRN reversal", min_approvals=1, final_role="director"),
    # Accepting material that fails a check: the Director approves every deviation until the
    # Production Manager role is switched on (owner, 1 Nov 2026; P16-08).
    "quality_deviation": DocumentType(
        "Accept under deviation", min_approvals=1, final_role="director"
    ),  # A supplier invoice that does not match its PO and GRN exactly: no tolerance, the
    # Director approves the exception (owner, 31 Oct 2026; P16-10).
    "invoice_exception": DocumentType(
        "Supplier invoice exception", min_approvals=1, final_role="director"
    ),  # Sending back goods QC had accepted: their value leaves stock and the supplier owes it
    # back (P16-12); the Director approves.
    "supplier_return": DocumentType(
        "Return of accepted goods", min_approvals=1, final_role="director"
    ),
    # A journal the Accountant types in is posted only once approved; the Director approves
    # every one until the owner decides otherwise (backlog P2-01, Phase 2 question 3).
    "manual_journal": DocumentType("Manual journal", min_approvals=1, final_role="director"),
    # The stores counted at go-live, with their cost: the Director approves before the stock
    # and its value go in (owner, 2 Nov 2026; P16-15).
    "opening_stock": DocumentType("Opening stock", min_approvals=1, final_role="director"),
    # A credit note against an issued tax invoice: the Director approves, or a person the
    # Admin gives the "approve_credit_notes" action to and the Director confirms (owner, 3 Nov
    # 2026; P2-06).
    "credit_note": DocumentType(
        "Credit note",
        min_approvals=1,
        final_role="director",
        approver_action="approve_credit_notes",
    ),
    # Money received for issued tax invoices: recorded by the Cashier, approved by the
    # Accountant or a person given "approve_customer_receipts", as for advances (P2-07; owner,
    # 3 Nov 2026).
    # Cancelling a supplier payment (a spoiled cheque, a failed transfer): the Director
    # approves every one (P2-11).
    "payment_cancellation": DocumentType(
        "Payment cancellation", min_approvals=1, final_role="director"
    ),
    "customer_receipt": DocumentType(
        "Customer receipt",
        min_approvals=1,
        final_role="accountant",
        approver_action="approve_customer_receipts",
    ),
}


class ApprovalError(Exception):
    pass


def _doc_type(document_type: str) -> DocumentType:
    if document_type not in DOCUMENT_TYPES:
        raise ApprovalError(f"Unknown document type {document_type!r}.")
    return DOCUMENT_TYPES[document_type]


def _amount(value) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, float):
        raise ApprovalError("Amounts must be exact decimals, not floating point.")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise ApprovalError("The amount is not a number.") from None
    if not amount.is_finite() or amount != amount.quantize(Decimal("0.01")):
        raise ApprovalError("Amounts are to the cent.")
    return amount


# --- The matrix -------------------------------------------------------------------------


def _matches(rule: ApprovalRule, amount, division, subtype) -> bool:
    if rule.division_id is not None and (division is None or rule.division_id != division.pk):
        return False
    if rule.subtype and rule.subtype != subtype:
        return False
    if rule.min_amount is not None and (amount is None or amount < rule.min_amount):
        return False
    if rule.max_amount is not None and (amount is None or amount > rule.max_amount):
        return False
    return True


def _specificity(rule: ApprovalRule) -> int:
    return sum(
        (
            rule.division_id is not None,
            bool(rule.subtype),
            rule.min_amount is not None or rule.max_amount is not None,
        )
    )


def route_for(document_type: str, *, amount=None, division=None, subtype="") -> list[dict]:
    """The approval levels a document goes through, with the role at each level. Where more
    than one rule fits a level, the most specific one wins; two equally specific rules with
    different roles are a matrix error, and the document cannot be submitted until fixed."""
    kind = _doc_type(document_type)
    amount = _amount(amount)
    rules = ApprovalRule.objects.filter(document_type=document_type, is_active=True)
    by_level: dict[int, list[ApprovalRule]] = {}
    for rule in rules.select_related("role"):
        if _matches(rule, amount, division, subtype or ""):
            by_level.setdefault(rule.level, []).append(rule)
    route = []
    for level in sorted(by_level):
        candidates = sorted(by_level[level], key=_specificity, reverse=True)
        best = candidates[0]
        tied = [c for c in candidates if _specificity(c) == _specificity(best)]
        if len({c.role_id for c in tied}) > 1:
            raise ApprovalError(
                f"The approval matrix has two equally specific rules at level {level} for "
                f"{kind.name.lower()}s with different roles. Ask the Admin to correct it."
            )
        route.append({"level": level, "role": best.role.code, "role_name": best.role.name})
    if len(route) < kind.min_approvals:
        raise ApprovalError(
            f"A {kind.name.lower()} needs at least {kind.min_approvals} approval levels; the "
            "approval matrix gives fewer. Ask the Admin to correct it."
        )
    if kind.final_role and route[-1]["role"] != kind.final_role:
        raise ApprovalError(
            f"The last approval of a {kind.name.lower()} must be the "
            f"{_role_name(kind.final_role)}; the approval matrix says otherwise."
        )
    return route


def _role_name(code: str) -> str:
    role = Role.objects.filter(code=code).first()
    return role.name if role else code


def _check_matrix_change(document_type: str) -> None:
    """After a change, every document of the type must still have a valid route, whatever
    its amount, division and sub-type: the always-applying rules alone must be enough."""
    kind = _doc_type(document_type)
    unconditional = ApprovalRule.objects.filter(
        document_type=document_type,
        is_active=True,
        division__isnull=True,
        subtype="",
        min_amount__isnull=True,
        max_amount__isnull=True,
    ).select_related("role")
    levels = {}
    for rule in unconditional:
        levels.setdefault(rule.level, set()).add(rule.role.code)
    if any(len(roles) > 1 for roles in levels.values()):
        raise ApprovalError("Each level can have only one rule that always applies.")
    if len(levels) < kind.min_approvals:
        raise ApprovalError(
            f"A {kind.name.lower()} needs at least {kind.min_approvals} levels that always "
            "apply, whatever the amount, division or type."
        )
    if kind.final_role:
        top = max(
            ApprovalRule.objects.filter(document_type=document_type, is_active=True).values_list(
                "level", flat=True
            )
        )
        finals = ApprovalRule.objects.filter(document_type=document_type, is_active=True, level=top)
        if top not in levels or any(r.role.code != kind.final_role for r in finals):
            raise ApprovalError(
                f"The last level of a {kind.name.lower()} must always be the "
                f"{_role_name(kind.final_role)}."
            )


def _settings_manager(user: User) -> None:
    from .access import has_access

    if not has_access(user, "settings", "manage"):
        raise ApprovalError("Only the Admin can change the approval matrix.")


def add_rule(
    user: User,
    *,
    document_type: str,
    level: int,
    role: Role,
    min_amount=None,
    max_amount=None,
    division: Division | None = None,
    subtype: str = "",
    reason: str = "",
) -> ApprovalRule:
    _settings_manager(user)
    _doc_type(document_type)
    if not 2 <= int(level) <= 9:
        raise ApprovalError("Approval levels go from 2 (the first approver) to 9.")
    if not role.is_active:
        raise ApprovalError(f"The role {role.name} is not in use.")
    low, high = _amount(min_amount), _amount(max_amount)
    if low is not None and high is not None and low > high:
        raise ApprovalError("The lowest amount is above the highest amount.")
    with audit_context("approval_rule_added", reason), transaction.atomic():
        rule = ApprovalRule.objects.create(
            document_type=document_type,
            level=int(level),
            role=role,
            min_amount=low,
            max_amount=high,
            division=division,
            subtype=(subtype or "").strip(),
            created_by=user,
        )
        _check_matrix_change(document_type)
        return rule


def switch_off_rule(user: User, rule: ApprovalRule, reason: str) -> ApprovalRule:
    _settings_manager(user)
    if not (reason or "").strip():
        raise ApprovalError("Give a reason for switching off the rule.")
    with audit_context("approval_rule_switched_off", reason), transaction.atomic():
        rule = ApprovalRule.objects.select_for_update().get(pk=rule.pk)
        if not rule.is_active:
            raise ApprovalError("The rule is already switched off.")
        rule.is_active = False
        rule.save()
        _check_matrix_change(rule.document_type)
        return rule


# --- Acting on documents ----------------------------------------------------------------


def holds_role(user: User, role_code: str) -> bool:
    return (
        user.is_active
        and UserRole.objects.filter(user=user, role__code=role_code, role__is_active=True).exists()
    )


def _stands_in(user: User, document_type: str, step: dict) -> bool:
    """Holds the document type's approver action, which counts as the final role."""
    doc = DOCUMENT_TYPES.get(document_type)
    if doc is None or not doc.approver_action or step["role"] != doc.final_role:
        return False
    return user.is_active and effective_access(user).can(doc.approver_action)


def may_act_at(user: User, document_type: str, step: dict) -> bool:
    return holds_role(user, step["role"]) or _stands_in(user, document_type, step)


def _log(state: ApprovalState, user: User, level: int, action: str, reason: str = ""):
    return ApprovalLog.objects.create(
        document_type=state.document_type,
        document_id=state.document_id,
        round=state.round,
        level=level,
        action=action,
        reason=reason,
        user=user,
        ip_address=_ip(),
    )


def submit(
    user: User,
    document_type: str,
    document_id: int,
    *,
    created_by: User,
    amount=None,
    division: Division | None = None,
    subtype: str = "",
    comment: str = "",
    title: str = "",
    link: str = "",
) -> ApprovalState:
    """Send a new or returned document for approval; approval (re)starts at the first level.
    Only its creator submits it (spec 4.2: the Clerk corrects and resubmits)."""
    _doc_type(document_type)
    if user.pk != created_by.pk:
        raise ApprovalError("Only the person who created the document can submit it.")
    route = route_for(document_type, amount=amount, division=division, subtype=subtype)
    with audit_context("document_submitted"), transaction.atomic():
        state = (
            ApprovalState.objects.select_for_update()
            .filter(document_type=document_type, document_id=document_id)
            .first()
        )
        if state is None:
            state = ApprovalState(
                document_type=document_type, document_id=document_id, created_by=created_by
            )
        elif state.status != ApprovalState.Status.RETURNED:
            raise ApprovalError(f"The document is {state.get_status_display().lower()}.")
        else:
            state.round += 1
        state.status = ApprovalState.Status.IN_PROGRESS
        state.current_level = route[0]["level"]
        state.route = route
        state.amount = _amount(amount)
        state.division = division
        state.subtype = subtype or ""
        state.title = (title or "").strip()[:200]
        state.link = (link or "").strip()[:200]
        state.save()
        _log(state, user, SUBMIT_LEVEL, ApprovalLog.Action.SUBMIT, (comment or "").strip())
        _tell_approvers(state)
        return state


def state_of(document_type: str, document_id: int) -> ApprovalState | None:
    return ApprovalState.objects.filter(
        document_type=document_type, document_id=document_id
    ).first()


def why_not(user: User, state: ApprovalState) -> str | None:
    """Why this user cannot act on the document now, or None if they can."""
    if state.status != ApprovalState.Status.IN_PROGRESS:
        return f"The document is {state.get_status_display().lower()}; nothing is waiting."
    step = next(s for s in state.route if s["level"] == state.current_level)
    if not may_act_at(user, state.document_type, step):
        return f"Level {state.current_level} is approved by the {step['role_name']}."
    if (
        user.pk == state.created_by_id
        or ApprovalLog.objects.filter(
            document_type=state.document_type,
            document_id=state.document_id,
            user=user,
            action=ApprovalLog.Action.SUBMIT,
        ).exists()
    ):
        return "You cannot approve a document you created or submitted."
    other_level = (
        ApprovalLog.objects.filter(
            document_type=state.document_type,
            document_id=state.document_id,
            user=user,
            action=ApprovalLog.Action.APPROVE,
        )
        .exclude(level=state.current_level)
        .exists()
    )
    if other_level:
        return "You have already approved this document at another level."
    if state.division_id and not division_scope(user).filter(pk=state.division_id).exists():
        return "The document belongs to a division you do not work in."
    return None


def _acting(user: User, document_type: str, document_id: int) -> ApprovalState:
    state = (
        ApprovalState.objects.select_for_update()
        .filter(document_type=document_type, document_id=document_id)
        .first()
    )
    if state is None:
        raise ApprovalError("The document has not been submitted.")
    refusal = why_not(user, state)
    if refusal:
        raise ApprovalError(refusal)
    return state


def approve(user: User, document_type: str, document_id: int, comment: str = ""):
    """Approve at the waiting level; the last level approves the document."""
    with audit_context("document_approved", comment), transaction.atomic():
        state = _acting(user, document_type, document_id)
        level = state.current_level
        _log(state, user, level, ApprovalLog.Action.APPROVE, (comment or "").strip())
        later = [s["level"] for s in state.route if s["level"] > level]
        if later:
            state.current_level = later[0]
        else:
            state.status = ApprovalState.Status.APPROVED
            state.current_level = None
        state.save()
        if later:
            _tell_approvers(state)
        else:
            _tell_creator(state, "document_approved", "was approved", comment)
        return state


def _close(user, document_type, document_id, reason, action, status, event):
    reason = (reason or "").strip()
    if not reason:
        verb = "returning" if action == ApprovalLog.Action.RETURN else "rejecting"
        raise ApprovalError(f"Give a reason for {verb} the document.")
    with audit_context(event, reason), transaction.atomic():
        state = _acting(user, document_type, document_id)
        _log(state, user, state.current_level, action, reason)
        state.status = status
        state.current_level = None
        state.save()
        if action == ApprovalLog.Action.RETURN:
            _tell_creator(state, "document_returned", "was returned to you", reason)
        else:
            _tell_creator(state, "document_rejected", "was rejected", reason)
        return state


def send_back(user: User, document_type: str, document_id: int, reason: str):
    """Return the document to its creator to correct and resubmit (reason required)."""
    return _close(
        user,
        document_type,
        document_id,
        reason,
        ApprovalLog.Action.RETURN,
        ApprovalState.Status.RETURNED,
        "document_returned",
    )


def reject(user: User, document_type: str, document_id: int, reason: str):
    """Reject the document for good (reason required)."""
    return _close(
        user,
        document_type,
        document_id,
        reason,
        ApprovalLog.Action.REJECT,
        ApprovalState.Status.REJECTED,
        "document_rejected",
    )


def send_down(user: User, document_type: str, document_id: int, reason: str):
    """A later approver changed the document (e.g. the Director changed a voucher's amount):
    it goes back to the first approval level, which approves it again before it comes up
    the route once more. The reason says what changed."""
    reason = (reason or "").strip()
    if not reason:
        raise ApprovalError("Say what was changed.")
    with audit_context("document_sent_down", reason), transaction.atomic():
        state = _acting(user, document_type, document_id)
        first = state.route[0]["level"]
        if state.current_level == first:
            raise ApprovalError("The document is already at its first approval level.")
        _log(state, user, state.current_level, ApprovalLog.Action.SEND_DOWN, reason)
        state.current_level = first
        state.save()
        _tell_approvers(state)
        return state


def withdraw(user: User, document_type: str, document_id: int, reason: str):
    """Take the document out of approval for good, e.g. a voucher deleted. The document's
    module decides who may do this; the engine records it with the reason."""
    reason = (reason or "").strip()
    if not reason:
        raise ApprovalError("Give a reason for withdrawing the document.")
    with audit_context("document_withdrawn", reason), transaction.atomic():
        state = (
            ApprovalState.objects.select_for_update()
            .filter(document_type=document_type, document_id=document_id)
            .first()
        )
        if state is None or state.status == ApprovalState.Status.WITHDRAWN:
            return state
        _log(state, user, state.current_level or SUBMIT_LEVEL, ApprovalLog.Action.WITHDRAW, reason)
        state.status = ApprovalState.Status.WITHDRAWN
        state.current_level = None
        state.save()
        return state


# --- Notifications (P0-18) ------------------------------------------------------------


def _title(state: ApprovalState) -> str:
    return state.title or f"{_doc_type(state.document_type).name} {state.document_id}"


def approvers(state: ApprovalState) -> list[User]:
    """The people who could act at the waiting level now."""
    if state.status != ApprovalState.Status.IN_PROGRESS:
        return []
    step = next(s for s in state.route if s["level"] == state.current_level)
    people = User.objects.filter(is_active=True).filter(
        Q(role_assignments__role__code=step["role"], role_assignments__role__is_active=True)
        | Q(pk__in=_action_holders(state.document_type))
    )
    return [person for person in people.distinct() if why_not(person, state) is None]


def _action_holders(document_type: str):
    """Users who may hold the document type's approver action (through a role or a grant);
    why_not() then checks it is in force."""
    doc = DOCUMENT_TYPES.get(document_type)
    if doc is None or not doc.approver_action:
        return User.objects.none().values("pk")
    return User.objects.filter(
        Q(
            role_assignments__role__actions__action=doc.approver_action,
            role_assignments__role__is_active=True,
        )
        | Q(access_overrides__action=doc.approver_action, access_overrides__effect="grant")
    ).values("pk")


def _tell_approvers(state: ApprovalState) -> None:
    from .notifications import notify

    notify(
        approvers(state),
        "approval_waiting",
        title=f"{_title(state)} is waiting for your approval (level {state.current_level})",
        link=state.link,
        document_type=state.document_type,
        document_id=state.document_id,
    )


def _tell_creator(state: ApprovalState, event: str, what: str, reason: str) -> None:
    from .notifications import notify

    notify(
        [state.created_by],
        event,
        title=f"{_title(state)} {what}",
        body=(reason or "").strip(),
        link=state.link,
        document_type=state.document_type,
        document_id=state.document_id,
    )


def history(document_type: str, document_id: int):
    return ApprovalLog.objects.filter(
        document_type=document_type, document_id=document_id
    ).select_related("user")


def waiting_for(user: User, document_type: str | None = None) -> list[ApprovalState]:
    """Documents waiting at a level this user can approve now (their approval queue)."""
    codes = set(
        UserRole.objects.filter(user=user, role__is_active=True).values_list(
            "role__code", flat=True
        )
    )
    states = ApprovalState.objects.filter(status=ApprovalState.Status.IN_PROGRESS)
    if document_type:
        states = states.filter(document_type=document_type)
    states = states.exclude(Q(created_by=user))
    return [
        s
        for s in states
        if any(
            step["level"] == s.current_level
            and (step["role"] in codes or _stands_in(user, s.document_type, step))
            for step in s.route
        )
        and why_not(user, s) is None
    ]


# --- Reminders (P1-09) ----------------------------------------------------------------


def reminder_settings() -> list[dict]:
    """The reminder setting of every document type (the default when none is stored)."""
    stored = {r.document_type: r for r in ApprovalReminder.objects.all()}
    rows = []
    for code, kind in DOCUMENT_TYPES.items():
        row = stored.get(code)
        rows.append(
            {
                "document_type": code,
                "name": kind.name,
                "enabled": row.enabled if row else False,
                "after_days": row.after_days if row else 3,
            }
        )
    return rows


def set_reminder(user: User, document_type: str, *, enabled: bool, after_days, reason=""):
    _settings_manager(user)
    _doc_type(document_type)
    try:
        days = int(after_days)
    except (TypeError, ValueError):
        raise ApprovalError("The number of days must be a whole number.") from None
    if not 1 <= days <= 60:
        raise ApprovalError("Remind after 1 to 60 days.")
    with audit_context("approval_reminder_changed", reason), transaction.atomic():
        row, _ = ApprovalReminder.objects.get_or_create(document_type=document_type)
        row.enabled = bool(enabled)
        row.after_days = days
        row.updated_by = user
        row.save()
    return reminder_settings()


def waiting_since(state: ApprovalState):
    """When the document started waiting at its level: the last action on it."""
    last = (
        ApprovalLog.objects.filter(document_type=state.document_type, document_id=state.document_id)
        .order_by("-acted_at", "-id")
        .first()
    )
    return last.acted_at if last else state.updated_at


def send_reminders(now=None) -> int:
    """Once a day: remind everyone who can act on a document that has waited at least the
    set number of days, until someone acts. Never twice on the same day for the same
    person and document. Returns the number of reminders made."""
    from .notifications import notify

    now = now or timezone.now()
    today = timezone.localtime(now).date()
    made = 0
    for setting in ApprovalReminder.objects.filter(enabled=True):
        if setting.document_type not in DOCUMENT_TYPES:
            continue
        states = ApprovalState.objects.filter(
            document_type=setting.document_type, status=ApprovalState.Status.IN_PROGRESS
        )
        for state in states:
            since = waiting_since(state)
            days = (today - timezone.localtime(since).date()).days
            if days < setting.after_days:
                continue
            already = set(
                Notification.objects.filter(
                    event="approval_reminder",
                    document_type=state.document_type,
                    document_id=state.document_id,
                    created_at__date=today,
                ).values_list("user_id", flat=True)
            )
            people = [p for p in approvers(state) if p.pk not in already]
            if not people:
                continue
            with transaction.atomic():
                made += len(
                    notify(
                        people,
                        "approval_reminder",
                        title=f"Reminder: {_title(state)} has waited {days} days for your "
                        f"approval (level {state.current_level})",
                        link=state.link,
                        document_type=state.document_type,
                        document_id=state.document_id,
                    )
                )
    return made
