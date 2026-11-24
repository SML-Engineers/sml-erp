"""Access rules (backlog P0-04, spec 1.1 and 1.2).

A user's effective access = their active roles' permissions, plus the Admin's grants, minus
removals (P0-04b), limited to their data scope (divisions).
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from .access_defaults import (
    ACTIONS,
    AREAS,
    CONFLICTING_PAIRS,
    FORBIDDEN_PAIRS,
    IMPLIES,
    LEVELS,
    TWO_FACTOR_ROLES,
)
from .audit import audited, record
from .models import (
    AccessOverride,
    Division,
    Role,
    RoleAction,
    RolePermission,
    RoleRequest,
    User,
    UserRole,
)


@dataclass
class EffectiveAccess:
    areas: dict[str, set[str]] = field(default_factory=dict)  # area -> levels held, expanded
    actions: set[str] = field(default_factory=set)

    def has(self, area: str, level: str = "view") -> bool:
        return level in self.areas.get(area, set())

    def can(self, action: str) -> bool:
        return action in self.actions

    def as_dict(self) -> dict:
        return {
            "areas": {area: sorted(levels) for area, levels in sorted(self.areas.items())},
            "actions": sorted(self.actions),
        }


def _expand(raw: dict[str, set[str]]) -> dict[str, set[str]]:
    return {
        area: set().union(*(IMPLIES.get(level, set()) for level in levels))
        for area, levels in raw.items()
        if levels
    }


def _without(held: set[str], removed: str) -> set[str]:
    """Take away `removed` and anything that includes it, keeping the levels below it.

    Removing Manage leaves Enter and View; removing View leaves nothing in that area.
    """
    kept: set[str] = set()
    for level in held:
        implied = IMPLIES.get(level, set())
        if removed in implied:
            kept |= {lower for lower in implied if removed not in IMPLIES.get(lower, set())}
        else:
            kept.add(level)
    return kept


def role_access(user: User) -> tuple[dict[str, set[str]], set[str]]:
    """Levels (not expanded) and actions from the user's active roles alone."""
    raw: dict[str, set[str]] = {}
    roles = Role.objects.filter(assignments__user=user, is_active=True)
    for area, level in RolePermission.objects.filter(role__in=roles).values_list("area", "level"):
        raw.setdefault(area, set()).add(level)
    actions = set(RoleAction.objects.filter(role__in=roles).values_list("action", flat=True))
    return raw, actions


def active_overrides(user: User):
    """Overrides in force today: not revoked, not past their end date, and confirmed if a
    sensitive grant. Pending sensitive grants have no effect (spec 1.3)."""
    today = timezone.localdate()
    candidates = AccessOverride.objects.filter(user=user, revoked_at__isnull=True).exclude(
        ends_on__lt=today
    )
    return [o for o in candidates if o.status == "active"]


def effective_access(user: User) -> EffectiveAccess:
    """Everything this user may do: roles, plus grants, minus removals (spec 1.2).

    A removal always beats a grant. Removing a level also removes the levels that include it,
    and keeps the ones below it (removing Manage keeps Enter and View; removing View removes
    the whole area). Nothing for anonymous users.
    """
    if not user or not user.is_authenticated or not user.is_active:
        return EffectiveAccess()
    cached = getattr(user, "_effective_access", None)
    if cached is not None:
        return cached
    access = access_once_active(user)
    user._effective_access = access  # cached for the rest of this request
    return access


def access_once_active(user: User) -> EffectiveAccess:
    """What this user's roles and overrides give, whether or not the account is active.

    Only for showing an administrator what an inactive account will have once activated
    (owner, 16 Nov 2026); every permission check uses effective_access, which gives an
    inactive account nothing.
    """
    access = EffectiveAccess()
    raw, actions = role_access(user)
    overrides = active_overrides(user)
    for o in overrides:
        if o.effect == AccessOverride.Effect.GRANT:
            if o.action:
                actions.add(o.action)
            else:
                raw.setdefault(o.area, set()).add(o.level)
    for o in overrides:
        if o.effect == AccessOverride.Effect.REMOVE:
            if o.action:
                actions.discard(o.action)
            else:
                raw[o.area] = _without(raw.get(o.area, set()), o.level)

    access.areas = _expand(raw)
    access.actions = actions
    return access


def has_access(user: User, area: str, level: str = "view") -> bool:
    return effective_access(user).has(area, level)


# --- Data scope -------------------------------------------------------------------------


def sees_all_divisions(user: User) -> bool:
    return bool(user.all_divisions) or has_access(user, "settings", "view")


def division_scope(user: User) -> QuerySet[Division]:
    """The divisions this user may see and work in."""
    if sees_all_divisions(user):
        return Division.objects.all()
    return user.divisions.all()


def filter_by_division(queryset: QuerySet, user: User, field_name: str = "division") -> QuerySet:
    """Limit any queryset of division-owned records to the user's divisions (rule 8).

    Every list, report, export and detail view of division-owned records goes through this.
    """
    if sees_all_divisions(user):
        return queryset
    return queryset.filter(**{f"{field_name}__in": user.divisions.all()})


# --- Role assignment --------------------------------------------------------------------


class AccessError(Exception):
    def __init__(self, message: str, warnings: list[str] | None = None):
        super().__init__(message)
        self.warnings = warnings or []


def conflict_warnings(role_codes: set[str]) -> list[str]:
    names = dict(Role.objects.filter(code__in=role_codes).values_list("code", "name"))
    return [
        f"{names[a]} + {names[b]}: one person {why}."
        for a, b, why in CONFLICTING_PAIRS
        if a in role_codes and b in role_codes
    ]


@audited("roles_changed", reason_arg="reason")
@transaction.atomic
def set_user_roles(actor: User, target: User, roles: list[Role], reason: str = "") -> list[str]:
    """Replace a user's roles. Returns any conflict warnings that were accepted with a reason."""
    if actor.pk == target.pk:
        raise AccessError("You cannot change your own roles; another administrator must do it.")
    inactive = [role.name for role in roles if not role.is_active]
    if inactive:
        raise AccessError(f"Not available yet: {', '.join(inactive)}.")

    codes = {role.code for role in roles}
    names = {role.code: role.name for role in roles}
    for a, b, why in FORBIDDEN_PAIRS:
        if a in codes and b in codes:
            raise AccessError(
                f"{names[a]} + {names[b]} cannot be held by one person: they would {why}."
            )
    warnings = conflict_warnings(codes)
    reason = (reason or "").strip()
    if warnings and not reason:
        raise AccessError(
            "These roles should normally be held by different people. "
            "Give a reason to assign them anyway.",
            warnings,
        )

    # Testing T38: a new role needs a reason, which the Director sees when confirming it.
    already = set(target.role_assignments.values_list("role_id", flat=True)) | set(
        target.role_requests.filter(status=RoleRequest.Status.WAITING).values_list(
            "role_id", flat=True
        )
    )
    if not reason and any(role.pk not in already for role in roles):
        raise AccessError("Give the reason for the new role (the Director sees it).")

    # Removing a role works at once; a role asked for earlier and now unticked is withdrawn.
    target.role_assignments.exclude(role__in=roles).delete()
    target.role_requests.filter(status=RoleRequest.Status.WAITING).exclude(role__in=roles).update(
        status=RoleRequest.Status.WITHDRAWN, decided_at=timezone.now()
    )
    held = set(target.role_assignments.values_list("role_id", flat=True))
    waiting = set(
        target.role_requests.filter(status=RoleRequest.Status.WAITING).values_list(
            "role_id", flat=True
        )
    )
    # A new role waits for the Director (owner, 15 Nov 2026), unless nobody else can confirm
    # it (a new system with no Director yet): then it works at once, in the audit log.
    asked = []
    for role in roles:
        if role.pk in held or role.pk in waiting:
            continue
        if role_confirmers(actor, target):
            asked.append(
                RoleRequest.objects.create(
                    user=target,
                    role=role,
                    requested_by=actor,
                    reason=reason,
                    conflict_warning=" ".join(warnings),
                )
            )
        else:
            _give_role(target, role, actor, reason, " ".join(warnings))
    if asked:
        from . import notifications

        names_asked = ", ".join(r.role.name for r in asked)
        notifications.notify(
            role_confirmers(actor, target),
            "admin_request_waiting",
            title=f"{target.full_name}: {names_asked} waiting for your confirmation",
            body=f"Asked by {actor.full_name}" + (f": {reason}" if reason else ""),
            link="/admin/access-to-confirm",
        )
    target.__dict__.pop("_effective_access", None)
    return warnings


def role_confirmers(actor: User, target: User) -> list[User]:
    """Who may confirm a role: the Director (confirm sensitive grants), not the person who
    asked or the person it is for."""
    return [
        u
        for u in User.objects.filter(is_active=True).exclude(pk__in=(actor.pk, target.pk))
        if effective_access(u).can("confirm_sensitive_grants")
    ]


def _give_role(target: User, role: Role, by: User, reason: str, warning: str) -> UserRole:
    held = UserRole.objects.create(
        user=target, role=role, assigned_by=by, reason=reason, conflict_warning=warning
    )
    if role.code in TWO_FACTOR_ROLES and not target.two_factor_required:
        target.two_factor_required = True
        target.save(update_fields=["two_factor_required"])
    target.__dict__.pop("_effective_access", None)
    return held


@audited("role_confirmed")
@transaction.atomic
def confirm_role(actor: User, request: RoleRequest) -> RoleRequest:
    """The Director confirms a role: only now does it work."""
    request = RoleRequest.objects.select_for_update().get(pk=request.pk)
    if not effective_access(actor).can("confirm_sensitive_grants"):
        raise AccessError("Only the Director can confirm a role.")
    if request.status != RoleRequest.Status.WAITING:
        raise AccessError("This role is not waiting for confirmation.")
    if actor.pk in (request.requested_by_id, request.user_id):
        raise AccessError(
            "Someone other than the person who asked and the person it is for must confirm it."
        )
    if not request.role.is_active:
        raise AccessError(f"{request.role.name} is not available any more.")
    _give_role(
        request.user, request.role, request.requested_by, request.reason, request.conflict_warning
    )
    request.status = RoleRequest.Status.CONFIRMED
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.save(update_fields=["status", "decided_by", "decided_at"])
    _tell_requester(request, "confirmed")
    return request


@audited("role_refused", reason_arg="reason")
@transaction.atomic
def refuse_role(actor: User, request: RoleRequest, reason: str) -> RoleRequest:
    request = RoleRequest.objects.select_for_update().get(pk=request.pk)
    if not effective_access(actor).can("confirm_sensitive_grants"):
        raise AccessError("Only the Director can refuse a role.")
    if request.status != RoleRequest.Status.WAITING:
        raise AccessError("This role is not waiting for confirmation.")
    if actor.pk in (request.requested_by_id, request.user_id):
        raise AccessError(
            "Someone other than the person who asked and the person it is for must decide."
        )
    reason = (reason or "").strip()
    if not reason:
        raise AccessError("Give a reason for refusing the role.")
    request.status = RoleRequest.Status.REFUSED
    request.decided_by = actor
    request.decided_at = timezone.now()
    request.decision_reason = reason
    request.save(update_fields=["status", "decided_by", "decided_at", "decision_reason"])
    _tell_requester(request, "refused")
    return request


def _tell_requester(request: RoleRequest, what: str) -> None:
    from . import notifications

    notifications.notify(
        [request.requested_by],
        "admin_request_decided",
        title=(
            f"{request.role.name} for {request.user.full_name} was {what} "
            f"by {request.decided_by.full_name}"
        ),
        body=request.decision_reason,
        link=f"/admin/users/{request.user_id}",
    )


@audited("divisions_changed")
@transaction.atomic
def set_user_scope(actor: User, target: User, all_divisions: bool, divisions: list[Division]):
    if actor.pk == target.pk:
        raise AccessError("You cannot change your own access; another administrator must do it.")
    before = sorted(target.divisions.values_list("code", flat=True))
    target.all_divisions = all_divisions
    target.save(update_fields=["all_divisions"])
    target.divisions.set([] if all_divisions else divisions)
    after = sorted(target.divisions.values_list("code", flat=True))
    if before != after:  # many-to-many changes are not seen by the automatic capture
        record("update", target, {"divisions": [before, after]})


# --- Custom roles -----------------------------------------------------------------------


def validate_role_content(permissions: list[dict], actions: list[str]) -> None:
    for item in permissions:
        if item.get("area") not in AREAS:
            raise AccessError(f"Unknown area: {item.get('area')!r}.")
        if item.get("level") not in LEVELS:
            raise AccessError(f"Unknown access level: {item.get('level')!r}.")
    for action in actions:
        if action not in ACTIONS:
            raise AccessError(f"Unknown special action: {action!r}.")


@audited("role_saved")
@transaction.atomic
def save_custom_role(
    role: Role | None,
    *,
    code: str,
    name: str,
    description: str,
    permissions: list[dict],
    actions: list[str],
) -> Role:
    if role is not None and role.is_standard:
        raise AccessError("Standard roles cannot be changed. Copy it to make a custom role.")
    validate_role_content(permissions, actions)
    if role is None:
        role = Role.objects.create(code=code, name=name, description=description)
    else:
        role.name, role.description = name, description
        role.save(update_fields=["name", "description"])
        role.permissions.all().delete()
        role.actions.all().delete()
    for item in permissions:
        RolePermission.objects.get_or_create(
            role=role,
            area=item["area"],
            level=item["level"],
            defaults={"note": item.get("note", "")},
        )
    for action in set(actions):
        RoleAction.objects.create(role=role, action=action)
    return role
