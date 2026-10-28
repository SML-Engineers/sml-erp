"""Sections, machines, machine rates and section scope (backlog P0-09, spec 3A.1).

Sections and machines are plain data: one added here appears at once on every entry page,
plan and report. Codes are fixed once a transaction has used them, and anything with
history is made inactive (sections) or retired (machines) rather than deleted (rule 9).
"""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from apps.core.access import AccessError, division_scope, sees_all_divisions
from apps.core.audit import audit_context, record
from apps.core.models import Division, User
from apps.core.organisation import OrganisationError, image_extension, related_rows

from .models import CODE_REGEX, Machine, MachineRate, Section

CODE_PATTERN = re.compile(CODE_REGEX)
PHOTO_MAX_BYTES = 5 * 1024 * 1024
MOULDING_FIELDS = (
    "clamping_force_t",
    "max_shot_weight_g",
    "screw_diameter_mm",
    "tie_bar_h_mm",
    "tie_bar_v_mm",
    "max_mould_height_mm",
    "max_mould_thickness_mm",
)
MACHINE_TEXT_FIELDS = ("make", "model", "serial_no", "notes")


class MastersError(Exception):
    pass


# --- Shared helpers ---------------------------------------------------------------------


def normalise_code(code: str, what: str) -> str:
    code = (code or "").strip().upper()
    if not CODE_PATTERN.match(code):
        raise MastersError(
            f"The {what} code must be 1 to 20 letters, digits or dashes, starting with a "
            "letter or digit, for example M-MIL."
        )
    return code


def _usage_relations(model):
    """Reverse relations that mean a transaction has used the record: not the structure
    under it, its settings history or who may work in it."""
    return [
        rel
        for rel in model._meta.related_objects
        if rel.get_accessor_name()
        and not rel.many_to_many
        and not getattr(rel.related_model, "is_structure", False)
    ]


def is_in_use(obj) -> bool:
    """True once a transaction has used the section or machine: its code is then fixed."""
    if obj.first_used_at is not None:
        return True
    return any(related_rows(rel, obj).exists() for rel in _usage_relations(type(obj)))


def linked_records(obj) -> dict[str, int]:
    counts = {}
    for rel in type(obj)._meta.related_objects:
        accessor = rel.get_accessor_name()
        if not accessor:
            continue
        count = related_rows(rel, obj).count()
        if count:
            counts[str(rel.related_model._meta.verbose_name_plural)] = count
    return counts


@transaction.atomic
def mark_used(obj) -> None:
    """Record that a transaction has used this section or machine (called by later phases).

    Idempotent: only the first use is stored. From then on the code is fixed.
    """
    now = timezone.now()
    if type(obj).objects.filter(pk=obj.pk, first_used_at__isnull=True).update(first_used_at=now):
        obj.first_used_at = now
        record("update", obj, {"first_used_at": [None, now.isoformat()]}, event="first_used")


def _require_reason(reason: str, doing: str) -> None:
    if not (reason or "").strip():
        raise MastersError(f"Give a reason for {doing}.")


def _name(name: str, what: str) -> str:
    name = (name or "").strip()
    if not name:
        raise MastersError(f"The {what} name is required.")
    return name


def _record_m2m(obj, field: str, before: list[str], after: list[str]) -> None:
    if sorted(before) != sorted(after):  # many-to-many changes are not seen by the signals
        record("update", obj, {field: [sorted(before), sorted(after)]})


# --- Sections ---------------------------------------------------------------------------


def _check_category(section_type: str, category: str) -> str:
    if section_type not in Section.Type.values:
        raise MastersError("The section type must be Machining, Moulding or Support.")
    category = category or ""
    if section_type == Section.Type.MACHINING:
        if category not in Section.Category.values:
            raise MastersError("A machining section must be Manual or CNC.")
        return category
    if category:
        raise MastersError("Only machining sections are Manual or CNC.")
    return ""


def _supervisors(user_ids) -> list[User]:
    ids = set(user_ids or [])
    users = list(User.objects.filter(pk__in=ids, is_active=True))
    if len(users) != len(ids):
        raise MastersError("A supervisor must be an active user.")
    return users


def create_section(
    *,
    code: str,
    name: str,
    division: Division,
    section_type: str,
    category: str = "",
    supervisors=(),
    is_active: bool = True,
    reason: str = "",
) -> Section:
    with audit_context("section_created", reason), transaction.atomic():
        code = normalise_code(code, "section")
        if Section.objects.filter(code=code).exists():
            raise MastersError(f"The section code {code} is already used.")
        if not division.is_active:
            raise MastersError(f"Division {division.code} is deactivated.")
        section = Section.objects.create(
            code=code,
            name=_name(name, "section"),
            division=division,
            section_type=section_type,
            category=_check_category(section_type, category),
            is_active=is_active,
        )
        people = _supervisors(supervisors)
        if people:
            section.supervisors.set(people)
            _record_m2m(section, "supervisors", [], [u.email for u in people])
        return section


def update_section(section: Section, data: dict, reason: str = "") -> Section:
    with transaction.atomic():
        section = Section.objects.select_for_update().get(pk=section.pk)
        event = "section_changed"
        if "code" in data:
            code = normalise_code(data["code"], "section")
            if code != section.code:
                if is_in_use(section):
                    raise MastersError(
                        f"Section {section.code} has been used and its code cannot change."
                    )
                if Section.objects.filter(code=code).exclude(pk=section.pk).exists():
                    raise MastersError(f"The section code {code} is already used.")
                section.code = code
        if "name" in data:
            section.name = _name(data["name"], "section")
        if "division" in data and data["division"].pk != section.division_id:
            if is_in_use(section) or section.machines.exists():
                raise MastersError(
                    "A section with machines or history cannot move to another division. "
                    "Add a new section in that division instead."
                )
            section.division = data["division"]
        section_type = data.get("section_type", section.section_type)
        category = data.get("category", section.category)
        if "section_type" in data or "category" in data:
            section.section_type = section_type
            section.category = _check_category(section_type, category)
        if "is_active" in data and bool(data["is_active"]) != section.is_active:
            if data["is_active"]:
                event = "section_reactivated"
            else:
                _require_reason(reason, "making the section inactive")
                event = "section_deactivated"
            section.is_active = bool(data["is_active"])
        with audit_context(event, reason):
            section.save()
            if "supervisors" in data:
                before = list(section.supervisors.values_list("email", flat=True))
                people = _supervisors(data["supervisors"])
                section.supervisors.set(people)
                _record_m2m(section, "supervisors", before, [u.email for u in people])
        return section


def delete_section(section: Section, reason: str) -> None:
    _require_reason(reason, "deleting the section")
    with audit_context("section_deleted", reason), transaction.atomic():
        section = Section.objects.select_for_update().get(pk=section.pk)
        if is_in_use(section):
            raise MastersError(
                f"Section {section.code} has been used: it cannot be deleted, only made inactive."
            )
        linked = linked_records(section)
        if linked:
            what = ", ".join(f"{count} {kind}" for kind, count in linked.items())
            raise MastersError(
                f"Section {section.code} has {what}. Move or remove them first, "
                "or make the section inactive."
            )
        section.delete()


# --- Machines ---------------------------------------------------------------------------


def _measure(value, label: str):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise MastersError(f"{label} must be a number.") from None
    if number < 0:
        raise MastersError(f"{label} cannot be negative.")
    if number != number.quantize(Decimal("0.1")):
        raise MastersError(f"{label} can have at most one decimal place.")
    return number


def _year(value):
    if value in (None, ""):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        raise MastersError("The year must be a whole number, for example 2019.") from None
    if not 1900 <= year <= timezone.localdate().year + 1:
        raise MastersError("The year is not a valid year of manufacture.")
    return year


def _status(value) -> str:
    if value not in Machine.Status.values:
        raise MastersError("The status must be Active, Under maintenance or Retired.")
    return value


def _apply_machine_fields(machine: Machine, data: dict) -> None:
    if "name" in data:
        machine.name = _name(data["name"], "machine")
    for field in MACHINE_TEXT_FIELDS:
        if field in data:
            setattr(machine, field, (data[field] or "").strip())
    if "year" in data:
        machine.year = _year(data["year"])
    for field in MOULDING_FIELDS:
        if field in data:
            label = Machine._meta.get_field(field).verbose_name
            setattr(machine, field, _measure(data[field], str(label)))


def _check_section_for_new_work(section: Section) -> None:
    if not section.is_active:
        raise MastersError(f"Section {section.code} is inactive.")


def create_machine(*, code: str, section: Section, reason: str = "", **data) -> Machine:
    with audit_context("machine_created", reason), transaction.atomic():
        code = normalise_code(code, "machine")
        if Machine.objects.filter(code=code).exists():
            raise MastersError(f"The machine code {code} is already used.")
        _check_section_for_new_work(section)
        machine = Machine(code=code, section=section)
        data.setdefault("name", "")
        _apply_machine_fields(machine, data)
        machine.status = _status(data.get("status", Machine.Status.ACTIVE))
        machine.save()
        return machine


def update_machine(machine: Machine, data: dict, reason: str = "") -> Machine:
    with transaction.atomic():
        machine = Machine.objects.select_for_update().get(pk=machine.pk)
        event = "machine_changed"
        if "code" in data:
            code = normalise_code(data["code"], "machine")
            if code != machine.code:
                if is_in_use(machine):
                    raise MastersError(
                        f"Machine {machine.code} has been used and its code cannot change."
                    )
                if Machine.objects.filter(code=code).exclude(pk=machine.pk).exists():
                    raise MastersError(f"The machine code {code} is already used.")
                machine.code = code
        if "section" in data and data["section"].pk != machine.section_id:
            # Earlier production keeps the section it was recorded under (spec 3A.1).
            _check_section_for_new_work(data["section"])
            machine.section = data["section"]
            event = "machine_moved"
        _apply_machine_fields(machine, data)
        if "status" in data and data["status"] != machine.status:
            status = _status(data["status"])
            if status == Machine.Status.RETIRED:
                _require_reason(reason, "retiring the machine")
                event = "machine_retired"
            elif machine.status == Machine.Status.RETIRED:
                event = "machine_reinstated"
            machine.status = status
        with audit_context(event, reason):
            machine.save()
        return machine


def delete_machine(machine: Machine, reason: str) -> None:
    _require_reason(reason, "deleting the machine")
    with audit_context("machine_deleted", reason), transaction.atomic():
        machine = Machine.objects.select_for_update().get(pk=machine.pk)
        if is_in_use(machine):
            raise MastersError(
                f"Machine {machine.code} has been used: it cannot be deleted, only retired."
            )
        if machine.rates.exists():
            raise MastersError(
                f"Machine {machine.code} has rate history: retire it instead of deleting it."
            )
        machine.delete()


def set_machine_photo(machine: Machine, uploaded) -> Machine:
    if uploaded.size > PHOTO_MAX_BYTES:
        raise MastersError("The photo must be 5 MB or smaller.")
    try:
        extension = image_extension(uploaded.read(), "The photo")
    except OrganisationError as error:
        raise MastersError(str(error)) from None
    uploaded.seek(0)
    with audit_context("machine_photo_changed"), transaction.atomic():
        machine = Machine.objects.select_for_update().get(pk=machine.pk)
        machine.photo.save(f"{machine.pk}.{extension}", uploaded, save=False)
        machine.save()
        return machine


def remove_machine_photo(machine: Machine) -> Machine:
    with audit_context("machine_photo_removed"), transaction.atomic():
        machine = Machine.objects.select_for_update().get(pk=machine.pk)
        machine.photo = ""
        machine.save()
        return machine


# --- Machine rates (effective-dated, rule 11) ------------------------------------------


def _money(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise MastersError("The hourly rate must be an amount, for example 2500.00.") from None
    if not amount.is_finite() or amount < 0:
        raise MastersError("The hourly rate cannot be negative.")
    if amount != amount.quantize(Decimal("0.01")):
        raise MastersError("The hourly rate can have at most two decimal places.")
    if amount >= Decimal("1e16"):
        raise MastersError("The hourly rate is too large.")
    return amount.quantize(Decimal("0.01"))


def add_rate(machine: Machine, *, effective_from: date, rate, reason: str = "", user=None):
    """A new hourly rate from a date. Earlier work keeps the rate in force at the time, so
    a rate can start today or later, never in the past."""
    amount = _money(rate)
    if effective_from < timezone.localdate():
        raise MastersError(
            "A new rate cannot start in the past: earlier jobs keep the rate they had. "
            "Choose today or a later date."
        )
    with audit_context("machine_rate_added", reason), transaction.atomic():
        if MachineRate.objects.filter(machine=machine, effective_from=effective_from).exists():
            raise MastersError(
                f"Machine {machine.code} already has a rate from {effective_from}. "
                "Remove that one first if it has not started yet."
            )
        return MachineRate.objects.create(
            machine=machine,
            effective_from=effective_from,
            rate=amount,
            reason=reason or "",
            created_by=user if user is not None and user.is_authenticated else None,
        )


def remove_rate(rate: MachineRate, reason: str) -> None:
    """Remove a rate that has not started yet (e.g. entered by mistake)."""
    _require_reason(reason, "removing the rate")
    if rate.effective_from <= timezone.localdate():
        raise MastersError(
            "This rate is already in force and cannot be removed. Add a new rate instead."
        )
    with audit_context("machine_rate_removed", reason), transaction.atomic():
        rate.delete()


def rate_on(machine: Machine, on_date: date) -> Decimal | None:
    """The hourly rate in force on a date, or None if none had started."""
    return (
        machine.rates.filter(effective_from__lte=on_date)
        .order_by("-effective_from")
        .values_list("rate", flat=True)
        .first()
    )


# --- Section scope (spec 1.1) -----------------------------------------------------------


def section_scope(user: User) -> QuerySet[Section]:
    """The sections this user may see and work in: within their divisions, and limited to
    their assigned and supervised sections unless they see all sections."""
    sections = Section.objects.filter(division__in=division_scope(user))
    if sees_all_divisions(user) or user.all_sections:
        return sections
    return sections.filter(Q(users=user) | Q(supervisors=user)).distinct()


def filter_by_section(queryset: QuerySet, user: User, field_name: str = "section") -> QuerySet:
    """Limit any queryset of section-owned records to the user's sections (rule 8)."""
    return queryset.filter(**{f"{field_name}__in": section_scope(user)})


def set_user_sections(actor: User, target: User, all_sections: bool, sections: list[Section]):
    if actor.pk == target.pk:
        raise AccessError("You cannot change your own access; another administrator must do it.")
    with audit_context("sections_changed"), transaction.atomic():
        before = sorted(target.sections.values_list("code", flat=True))
        target.all_sections = all_sections
        target.save(update_fields=["all_sections"])
        target.sections.set([] if all_sections else sections)
        after = sorted(target.sections.values_list("code", flat=True))
        if before != after:
            record("update", target, {"sections": [before, after]})
