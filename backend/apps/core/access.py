"""Access rules (backlog P0-04, spec 1.1 and 1.2).

A user's effective access = the union of their active roles' permissions, limited to their
data scope (divisions). Per-user overrides and hard controls are added in P0-04b.
"""

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import QuerySet

from .access_defaults import (
    ACTIONS,
    AREAS,
    CONFLICTING_PAIRS,
    IMPLIES,
    LEVELS,
    TWO_FACTOR_ROLES,
)
from .models import Division, Role, RoleAction, RolePermission, User, UserRole


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


def effective_access(user: User) -> EffectiveAccess:
    """Everything this user may do, from their active roles. Nothing for anonymous users."""
    access = EffectiveAccess()
    if not user or not user.is_authenticated or not user.is_active:
        return access
    cached = getattr(user, "_effective_access", None)
    if cached is not None:
        return cached

    roles = Role.objects.filter(assignments__user=user, is_active=True)
    for area, level in RolePermission.objects.filter(role__in=roles).values_list("area", "level"):
        access.areas.setdefault(area, set()).update(IMPLIES.get(level, set()))
    access.actions.update(
        RoleAction.objects.filter(role__in=roles).values_list("action", flat=True)
    )
    user._effective_access = access  # cached for the rest of this request
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


@transaction.atomic
def set_user_roles(actor: User, target: User, roles: list[Role], reason: str = "") -> list[str]:
    """Replace a user's roles. Returns any conflict warnings that were accepted with a reason."""
    if actor.pk == target.pk:
        raise AccessError("You cannot change your own roles; another administrator must do it.")
    inactive = [role.name for role in roles if not role.is_active]
    if inactive:
        raise AccessError(f"Not available yet: {', '.join(inactive)}.")

    codes = {role.code for role in roles}
    warnings = conflict_warnings(codes)
    reason = (reason or "").strip()
    if warnings and not reason:
        raise AccessError(
            "These roles should normally be held by different people. "
            "Give a reason to assign them anyway.",
            warnings,
        )

    target.role_assignments.exclude(role__in=roles).delete()
    held = set(target.role_assignments.values_list("role_id", flat=True))
    for role in roles:
        if role.pk not in held:
            UserRole.objects.create(
                user=target,
                role=role,
                assigned_by=actor,
                reason=reason,
                conflict_warning=" ".join(warnings),
            )
    if codes & TWO_FACTOR_ROLES and not target.two_factor_required:
        target.two_factor_required = True
        target.save(update_fields=["two_factor_required"])
    target.__dict__.pop("_effective_access", None)
    return warnings


@transaction.atomic
def set_user_scope(actor: User, target: User, all_divisions: bool, divisions: list[Division]):
    if actor.pk == target.pk:
        raise AccessError("You cannot change your own access; another administrator must do it.")
    target.all_divisions = all_divisions
    target.save(update_fields=["all_divisions"])
    target.divisions.set([] if all_divisions else divisions)


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
