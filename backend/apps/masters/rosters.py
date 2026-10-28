"""Shifts, roster patterns, crews and the roster calendar (backlog P0-10, spec 3A.2, 7.1A).

Rosters are dated: a seasonal change is a new assignment from a date. Once an assignment
has started, only its end date can be set, and the shifts and patterns it uses can no
longer change their times or days, so past days are never rewritten.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.audit import audit_context
from apps.core.models import Division

from .models import (
    Crew,
    RosterAssignment,
    RosterCrew,
    RosterPattern,
    RosterPatternDay,
    Section,
    Shift,
)
from .services import MastersError

SHIFT_CODE = re.compile(r"^[A-Z0-9]{1,5}$")
CREW_CODE = re.compile(r"^[A-Z0-9]{1,10}$")
MAX_CYCLE = 56
MAX_PREVIEW_DAYS = 62


def _reason_needed(reason: str, doing: str) -> None:
    if not (reason or "").strip():
        raise MastersError(f"Give a reason for {doing}.")


def _name(value: str, what: str) -> str:
    value = (value or "").strip()
    if not value:
        raise MastersError(f"The {what} name is required.")
    return value


# --- Shifts -----------------------------------------------------------------------------


def _shift_started(shift: Shift) -> bool:
    """Used by a roster that has already started: its times are then part of history."""
    return RosterAssignment.objects.filter(
        pattern__days__shift=shift, start_date__lte=timezone.localdate()
    ).exists()


def _check_times(start: time, end: time, break_minutes: int) -> None:
    if start == end:
        raise MastersError("A shift cannot start and end at the same time.")
    probe = Shift(start_time=start, end_time=end, break_minutes=0)
    if break_minutes < 0 or break_minutes >= probe.length_minutes:
        raise MastersError("The break must be shorter than the shift.")


def create_shift(*, code, name, start_time, end_time, break_minutes=0, reason="") -> Shift:
    code = (code or "").strip().upper()
    if not SHIFT_CODE.match(code):
        raise MastersError("The shift code must be 1 to 5 letters or digits, for example N.")
    with audit_context("shift_created", reason), transaction.atomic():
        if Shift.objects.filter(code=code).exists():
            raise MastersError(f"The shift code {code} is already used.")
        name = _name(name, "shift")
        if Shift.objects.filter(name__iexact=name).exists():
            raise MastersError(f"There is already a shift called {name}.")
        _check_times(start_time, end_time, break_minutes)
        return Shift.objects.create(
            code=code,
            name=name,
            start_time=start_time,
            end_time=end_time,
            break_minutes=break_minutes,
        )


def update_shift(shift: Shift, data: dict, reason: str = "") -> Shift:
    with transaction.atomic():
        shift = Shift.objects.select_for_update().get(pk=shift.pk)
        event = "shift_changed"
        timing = {k: data[k] for k in ("start_time", "end_time", "break_minutes") if k in data}
        changes_timing = any(getattr(shift, k) != v for k, v in timing.items())
        new_code = (data.get("code", shift.code) or "").strip().upper()
        if (changes_timing or new_code != shift.code) and _shift_started(shift):
            raise MastersError(
                f"Shift {shift.code} is used by a roster that has started, so its code and "
                "times cannot change. Add a new shift and use it in a new roster from a date."
            )
        if new_code != shift.code:
            if not SHIFT_CODE.match(new_code):
                raise MastersError("The shift code must be 1 to 5 letters or digits.")
            if Shift.objects.filter(code=new_code).exclude(pk=shift.pk).exists():
                raise MastersError(f"The shift code {new_code} is already used.")
            shift.code = new_code
        if "name" in data:
            name = _name(data["name"], "shift")
            if Shift.objects.filter(name__iexact=name).exclude(pk=shift.pk).exists():
                raise MastersError(f"There is already a shift called {name}.")
            shift.name = name
        for key, value in timing.items():
            setattr(shift, key, value)
        _check_times(shift.start_time, shift.end_time, shift.break_minutes)
        if "is_active" in data and bool(data["is_active"]) != shift.is_active:
            if not data["is_active"]:
                _reason_needed(reason, "making the shift inactive")
                if RosterPatternDay.objects.filter(shift=shift, pattern__is_active=True).exists():
                    raise MastersError(
                        f"Shift {shift.code} is in an active roster pattern; change the pattern "
                        "first."
                    )
                event = "shift_deactivated"
            else:
                event = "shift_reactivated"
            shift.is_active = bool(data["is_active"])
        with audit_context(event, reason):
            shift.save()
        return shift


# --- Roster patterns --------------------------------------------------------------------


def _pattern_started(pattern: RosterPattern) -> bool:
    return pattern.assignments.filter(start_date__lte=timezone.localdate()).exists()


def _cycle(shift_ids: list) -> list[Shift | None]:
    if not shift_ids:
        raise MastersError("A pattern needs at least one day.")
    if len(shift_ids) > MAX_CYCLE:
        raise MastersError(f"A pattern can have at most {MAX_CYCLE} days.")
    wanted = {i for i in shift_ids if i is not None}
    shifts = {s.pk: s for s in Shift.objects.filter(pk__in=wanted, is_active=True)}
    if len(shifts) != len(wanted):
        raise MastersError("Every day must be an active shift or Off.")
    days = [shifts.get(i) if i is not None else None for i in shift_ids]
    if all(day is None for day in days):
        raise MastersError("A pattern needs at least one working day.")
    return days


def _save_days(pattern: RosterPattern, days: list[Shift | None]) -> None:
    pattern.days.all().delete()
    RosterPatternDay.objects.bulk_create(
        RosterPatternDay(pattern=pattern, position=i, shift=shift) for i, shift in enumerate(days)
    )


def create_pattern(*, name: str, days: list, reason: str = "") -> RosterPattern:
    with audit_context("roster_pattern_created", reason), transaction.atomic():
        name = _name(name, "pattern")
        if RosterPattern.objects.filter(name__iexact=name).exists():
            raise MastersError(f"There is already a pattern called {name}.")
        cycle = _cycle(days)
        pattern = RosterPattern.objects.create(name=name)
        _save_days(pattern, cycle)
        return pattern


def update_pattern(pattern: RosterPattern, data: dict, reason: str = "") -> RosterPattern:
    with audit_context("roster_pattern_changed", reason), transaction.atomic():
        pattern = RosterPattern.objects.select_for_update().get(pk=pattern.pk)
        if "name" in data:
            name = _name(data["name"], "pattern")
            if RosterPattern.objects.filter(name__iexact=name).exclude(pk=pattern.pk).exists():
                raise MastersError(f"There is already a pattern called {name}.")
            pattern.name = name
        if "days" in data:
            cycle = _cycle(data["days"])
            current = [d.shift_id for d in pattern.days.all()]
            if [s.pk if s else None for s in cycle] != current:
                if _pattern_started(pattern):
                    raise MastersError(
                        f"{pattern.name} is used by a roster that has started, so its days "
                        "cannot change. Make a new pattern and use it from a date."
                    )
                _save_days(pattern, cycle)
        if "is_active" in data and bool(data["is_active"]) != pattern.is_active:
            if not data["is_active"]:
                _reason_needed(reason, "making the pattern inactive")
                if _open_assignments().filter(pattern=pattern).exists():
                    raise MastersError(
                        f"{pattern.name} is used by a current or future roster; end it first."
                    )
            pattern.is_active = bool(data["is_active"])
        pattern.save()
        return pattern


def pattern_summary(pattern: RosterPattern) -> dict:
    days = list(pattern.days.select_related("shift"))
    minutes = sum(d.shift.working_minutes for d in days if d.shift)
    length = len(days) or 1
    return {
        "cycle_days": len(days),
        "hours_per_cycle": round(minutes / 60, 2),
        "average_hours_per_week": round(minutes / 60 / length * 7, 2),
    }


# --- Crews ------------------------------------------------------------------------------


def _open_assignments():
    today = timezone.localdate()
    return RosterAssignment.objects.filter(Q(end_date__isnull=True) | Q(end_date__gte=today))


def create_crew(*, division: Division, code: str, name: str = "", reason: str = "") -> Crew:
    code = (code or "").strip().upper()
    if not CREW_CODE.match(code):
        raise MastersError("The crew code must be 1 to 10 letters or digits, for example A.")
    with audit_context("crew_created", reason), transaction.atomic():
        if not division.is_active:
            raise MastersError(f"Division {division.code} is deactivated.")
        if Crew.objects.filter(division=division, code=code).exists():
            raise MastersError(f"{division.code} already has a crew {code}.")
        return Crew.objects.create(division=division, code=code, name=(name or "").strip())


def update_crew(crew: Crew, data: dict, reason: str = "") -> Crew:
    with transaction.atomic():
        crew = Crew.objects.select_for_update().get(pk=crew.pk)
        event = "crew_changed"
        if "code" in data:
            code = (data["code"] or "").strip().upper()
            if code != crew.code:
                if not CREW_CODE.match(code):
                    raise MastersError("The crew code must be 1 to 10 letters or digits.")
                if crew.rosters.exists():
                    raise MastersError(
                        f"Crew {crew.code} is on a roster, so its code cannot change."
                    )
                if Crew.objects.filter(division=crew.division, code=code).exists():
                    raise MastersError(f"{crew.division.code} already has a crew {code}.")
                crew.code = code
        if "name" in data:
            crew.name = (data["name"] or "").strip()
        if "is_active" in data and bool(data["is_active"]) != crew.is_active:
            if not data["is_active"]:
                _reason_needed(reason, "making the crew inactive")
                if _open_assignments().filter(crews__crew=crew).exists():
                    raise MastersError(
                        f"Crew {crew.code} is on a current or future roster; end it first."
                    )
                event = "crew_deactivated"
            else:
                event = "crew_reactivated"
            crew.is_active = bool(data["is_active"])
        with audit_context(event, reason):
            crew.save()
        return crew


# --- Roster calendar --------------------------------------------------------------------


def _overlaps(start: date, end: date | None, other: RosterAssignment) -> bool:
    far = date.max
    return start <= (other.end_date or far) and other.start_date <= (end or far)


def _check_assignment(assignment: RosterAssignment, crews: list[tuple[Crew, int]]) -> None:
    if assignment.section_id and assignment.section.division_id != assignment.division_id:
        raise MastersError("The section must belong to the chosen division.")
    if not assignment.pattern.is_active:
        raise MastersError(f"Pattern {assignment.pattern.name} is inactive.")
    if not assignment.division.is_active:
        raise MastersError(f"Division {assignment.division.code} is deactivated.")
    if assignment.end_date and assignment.end_date < assignment.start_date:
        raise MastersError("The end date cannot be before the start date.")
    cycle = assignment.pattern.days.count()
    seen = set()
    for crew, position in crews:
        if crew.division_id != assignment.division_id:
            raise MastersError(f"Crew {crew.code} belongs to another division.")
        if not crew.is_active:
            raise MastersError(f"Crew {crew.code} is inactive.")
        if crew.pk in seen:
            raise MastersError(f"Crew {crew.code} is listed twice.")
        seen.add(crew.pk)
        if not 0 <= position < cycle:
            raise MastersError(f"Crew {crew.code} must start on a day of the cycle, 1 to {cycle}.")
        clash = (
            RosterAssignment.objects.filter(crews__crew=crew)
            .exclude(pk=assignment.pk)
            .select_related("pattern")
        )
        for other in clash:
            if _overlaps(assignment.start_date, assignment.end_date, other):
                raise MastersError(
                    f"Crew {crew.code} is already on {other.pattern.name} from "
                    f"{other.start_date}; a crew can follow only one roster at a time."
                )


def create_assignment(
    *,
    pattern: RosterPattern,
    division: Division,
    start_date: date,
    section: Section | None = None,
    end_date: date | None = None,
    crews: list[tuple[Crew, int]] = (),
    note: str = "",
    reason: str = "",
) -> RosterAssignment:
    if start_date < timezone.localdate():
        raise MastersError(
            "A roster cannot start in the past: past days keep the roster they had. "
            "Choose today or a later date."
        )
    with audit_context("roster_assigned", reason), transaction.atomic():
        assignment = RosterAssignment(
            pattern=pattern,
            division=division,
            section=section,
            start_date=start_date,
            end_date=end_date,
            note=(note or "").strip(),
        )
        _check_assignment(assignment, list(crews))
        assignment.save()
        RosterCrew.objects.bulk_create(
            RosterCrew(assignment=assignment, crew=crew, start_position=position)
            for crew, position in crews
        )
        return assignment


def update_assignment(
    assignment: RosterAssignment, data: dict, reason: str = ""
) -> RosterAssignment:
    """Before it starts, anything can change. Once started, only the end date, and not
    into the past."""
    today = timezone.localdate()
    with audit_context("roster_changed", reason), transaction.atomic():
        assignment = RosterAssignment.objects.select_for_update().get(pk=assignment.pk)
        started = assignment.start_date <= today
        changing = set(data) - {"end_date", "note"}
        if started and changing:
            raise MastersError(
                "This roster has started, so only its end date can change. To change the "
                "roster, end it and add a new one from the next day."
            )
        if started and data.get("end_date") is not None and data["end_date"] < today:
            raise MastersError("A roster that has started cannot end before today.")
        for key in ("pattern", "division", "section", "start_date", "end_date", "note"):
            if key in data:
                setattr(assignment, key, data[key])
        if not started and assignment.start_date < today:
            raise MastersError("A roster cannot start in the past.")
        crews = (
            list(data["crews"])
            if "crews" in data
            else [(rc.crew, rc.start_position) for rc in assignment.crews.select_related("crew")]
        )
        _check_assignment(assignment, crews)
        assignment.save()
        if "crews" in data:
            assignment.crews.all().delete()
            RosterCrew.objects.bulk_create(
                RosterCrew(assignment=assignment, crew=crew, start_position=position)
                for crew, position in crews
            )
        return assignment


def delete_assignment(assignment: RosterAssignment, reason: str) -> None:
    _reason_needed(reason, "removing the roster")
    if assignment.start_date <= timezone.localdate():
        raise MastersError("A roster that has started cannot be removed; set its end date.")
    with audit_context("roster_removed", reason), transaction.atomic():
        assignment.crews.all().delete()
        assignment.delete()


@dataclass
class OnShift:
    day: date
    shift: Shift
    crew: Crew | None
    assignment: RosterAssignment

    @property
    def starts(self) -> datetime:
        return datetime.combine(self.day, self.shift.start_time)

    @property
    def ends(self) -> datetime:
        return self.starts + timedelta(minutes=self.shift.length_minutes)


def _assignments_for(division: Division, section: Section | None):
    found = RosterAssignment.objects.filter(division=division).select_related("pattern")
    if section is not None:
        found = found.filter(Q(section__isnull=True) | Q(section=section))
    return found.prefetch_related("crews__crew", "pattern__days__shift")


def schedule(division: Division, start: date, days: int, section: Section | None = None):
    """Who is on which shift each day. A night shift is listed on the date it starts."""
    if not 1 <= days <= MAX_PREVIEW_DAYS:
        raise MastersError(f"Show between 1 and {MAX_PREVIEW_DAYS} days.")
    assignments = list(_assignments_for(division, section))
    result = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        entries = []
        for a in assignments:
            if day < a.start_date or (a.end_date and day > a.end_date):
                continue
            cycle = list(a.pattern.days.all())
            elapsed = (day - a.start_date).days
            crews = list(a.crews.all())
            for rc in crews or [None]:
                position = (elapsed + (rc.start_position if rc else 0)) % len(cycle)
                shift = cycle[position].shift
                if shift is not None:
                    entries.append(OnShift(day, shift, rc.crew if rc else None, a))
        result.append((day, entries))
    return result


def warnings(division: Division, start: date, days: int, section: Section | None = None):
    """Days on which a crew rotation leaves one of its shifts with no crew."""
    found = []
    assignments = list(_assignments_for(division, section))
    for day, entries in schedule(division, start, days, section):
        for a in assignments:
            running = a.start_date <= day and (a.end_date is None or day <= a.end_date)
            if not running or not a.crews.all():
                continue
            planned = {d.shift for d in a.pattern.days.all() if d.shift}
            covered = {e.shift for e in entries if e.assignment.pk == a.pk}
            for shift in sorted(planned - covered, key=lambda s: s.start_time):
                where = a.section.code if a.section else a.division.code
                found.append(f"{day.isoformat()}: no crew on {shift.name} ({where}).")
    return found


def on_shift_at(moment: datetime, division: Division, section: Section | None = None):
    """The shifts running at a moment, each with the date it belongs to: a night shift
    that started yesterday evening belongs to yesterday."""
    day = moment.date()
    running = []
    for _, entries in schedule(division, day - timedelta(days=1), 2, section):
        running.extend(e for e in entries if e.starts <= moment < e.ends)
    return running
