"""The phone punch clock (backlog P2B-12; spec 7A).

- **Who**: employees HR has switched on (`Employee.phone_clock`): "from anywhere", or "only at
  a site". They clock in and out on their self-service page; the time is the **server's**,
  never the phone's.
- **Sites**: HR keeps the punch sites (a point and a radius, 20 m to 5 km). An employee limited
  to sites clocks in or out only within a site's radius. Their location is read **only at the
  moment they press the button, and only with their own consent**, given and withdrawn on
  their page; it is never tracked otherwise. Without consent they cannot use the phone clock
  and HR enters their days with the attendance sheet.
- **Punches never change** (database). One clock-in, then one clock-out: an open clock-in
  older than 20 hours is treated as forgotten.
- **Into attendance**: HR brings a pay month's punches into attendance, like an uploaded sheet
  (P2B-04), after a preview. Each day takes the first clock-in and the last clock-out (a night
  shift belongs to the day it started), and the active shift starting nearest to the
  clock-in (within 2 hours) for late and early minutes. Days already entered from a sheet are
  kept (the sheet is HR's correction); days brought in from punches before are replaced; a
  clock-in without a clock-out is listed for HR to enter in the sheet; today is left for
  tomorrow; confirmed months are never touched.
"""

import hashlib
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core.audit import audit_context
from apps.core.models import User
from apps.masters.models import Shift

from . import employees, periods
from .attendance import AttendanceError, Row, _measure, _minutes, first_of
from .models import AttendanceDay, AttendanceImport, AttendanceMonth, Employee, Punch, PunchSite

OPEN_HOURS = 20
NEAREST_SHIFT = 120  # minutes
WORST_ACCURACY = 150  # metres
EARTH = 6371000  # metres


class PunchError(Exception):
    pass


# --- Sites ---------------------------------------------------------------------------------------


def _coordinate(value, what: str, limit: int) -> Decimal:
    try:
        number = Decimal(str(value).strip()).quantize(Decimal("0.000001"))
    except (InvalidOperation, ValueError):
        raise PunchError(f"The {what} is a number of degrees, e.g. 6.927079.") from None
    if not -limit <= number <= limit:
        raise PunchError(f"The {what} is between -{limit} and {limit}.")
    return number


def _site_values(values: dict, current: PunchSite | None) -> dict:
    out = {}
    if current is None or "name" in values:
        out["name"] = str(values.get("name") or "").strip()[:100]
        if not out["name"]:
            raise PunchError("Give the site a name.")
        same = PunchSite.objects.filter(name__iexact=out["name"])
        if current is not None:
            same = same.exclude(pk=current.pk)
        if same.exists():
            raise PunchError(f"There is already a site called {out['name']}.")
    if current is None or "latitude" in values:
        out["latitude"] = _coordinate(values.get("latitude"), "latitude", 90)
    if current is None or "longitude" in values:
        out["longitude"] = _coordinate(values.get("longitude"), "longitude", 180)
    if current is None or "radius_m" in values:
        try:
            out["radius_m"] = int(values.get("radius_m") or 200)
        except (TypeError, ValueError):
            raise PunchError("The radius is a whole number of metres.") from None
        if not 20 <= out["radius_m"] <= 5000:
            raise PunchError("The radius is 20 to 5,000 metres.")
    if "is_active" in values:
        # JSON gives a boolean; a form gives "true" or "false".
        out["is_active"] = str(values["is_active"]).strip().lower() in ("true", "1", "yes")
    return out


def add_site(user: User, values: dict) -> PunchSite:
    if not employees.can_edit(user):
        raise PunchError("Only HR keeps the punch sites.")
    with audit_context("punch_site_added", ""), transaction.atomic():
        return PunchSite.objects.create(created_by=user, **_site_values(values, None))


def change_site(user: User, site_id, values: dict) -> PunchSite:
    if not employees.can_edit(user):
        raise PunchError("Only HR keeps the punch sites.")
    with audit_context("punch_site_changed", ""), transaction.atomic():
        site = PunchSite.objects.select_for_update().filter(pk=site_id).first()
        if site is None:
            raise PunchError("There is no such site.")
        for key, value in _site_values(values, site).items():
            setattr(site, key, value)
        site.save()
        return site


def distance(lat1, lon1, lat2, lon2) -> int:
    """Metres between two points (haversine). A geometric check, not an amount."""
    p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
    dp, dl = p2 - p1, math.radians(float(lon2) - float(lon1))
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * EARTH * math.asin(math.sqrt(a)))


def nearest_site(latitude, longitude) -> tuple[PunchSite | None, int | None]:
    best, best_m = None, None
    for site in PunchSite.objects.filter(is_active=True):
        metres = distance(latitude, longitude, site.latitude, site.longitude)
        if best_m is None or metres < best_m:
            best, best_m = site, metres
    return best, best_m


# --- The employee --------------------------------------------------------------------------------


def _employee(user: User) -> Employee:
    employee = Employee.objects.filter(user=user).first()
    if employee is None:
        raise PunchError("Your sign-in is not linked to an employee record yet. Ask HR to link it.")
    return employee


def open_punch(employee: Employee, now: datetime | None = None) -> Punch | None:
    """The clock-in not yet followed by a clock-out, if it is less than 20 hours old."""
    now = now or timezone.now()
    last = employee.punches.order_by("-at", "-pk").first()
    if last and last.kind == Punch.Kind.IN and now - last.at < timedelta(hours=OPEN_HOURS):
        return last
    return None


def _hm(moment: datetime) -> str:
    return timezone.localtime(moment).strftime("%H:%M")


def status(employee: Employee) -> dict | None:
    """What the self-service page shows; None when the phone clock is not used."""
    if employee.phone_clock == Employee.PhoneClock.OFF:
        return None
    now = timezone.now()
    since = timezone.make_aware(datetime.combine(timezone.localdate() - timedelta(days=1), time()))
    recent = employee.punches.filter(at__gte=since).select_related("site").order_by("-at")
    current = open_punch(employee, now)
    return {
        "mode": employee.phone_clock,
        "mode_label": employee.get_phone_clock_display(),
        "needs_location": employee.phone_clock == Employee.PhoneClock.SITES,
        "consent": employee.location_consent_at is not None,
        "consent_at": employee.location_consent_at,
        "clocked_in": current is not None,
        "since": _hm(current.at) if current else "",
        "recent": [
            {
                "kind": p.kind,
                "kind_label": p.get_kind_display(),
                "at": timezone.localtime(p.at).strftime("%Y-%m-%d %H:%M"),
                "site": p.site.name if p.site_id else "",
            }
            for p in recent[:10]
        ],
        "sites": [s.name for s in PunchSite.objects.filter(is_active=True)]
        if employee.phone_clock == Employee.PhoneClock.SITES
        else [],
    }


def consent(user: User, given: bool) -> Employee:
    with audit_context("location_consent_given" if given else "location_consent_withdrawn", ""):
        with transaction.atomic():
            employee = Employee.objects.select_for_update().filter(user=user).first()
            if employee is None:
                raise PunchError(
                    "Your sign-in is not linked to an employee record yet. Ask HR to link it."
                )
            employee.location_consent_at = timezone.now() if given else None
            employee.save(update_fields=["location_consent_at"])
            return employee


def punch(user: User, kind: str, latitude=None, longitude=None, accuracy=None) -> Punch:
    if kind not in Punch.Kind.values:
        raise PunchError("Clock in or clock out.")
    with audit_context(f"clock_{kind}", ""), transaction.atomic():
        employee = Employee.objects.select_for_update().filter(pk=_employee(user).pk).first()
        today = timezone.localdate()
        if employee.phone_clock == Employee.PhoneClock.OFF:
            raise PunchError("HR has not switched on the phone clock for you.")
        if not employee.is_active or (employee.leaving_date and today > employee.leaving_date):
            raise PunchError("You are no longer employed.")
        if AttendanceMonth.objects.filter(
            division=employee.division, month=periods.pay_month_of(today), confirmed=True
        ).exists():
            raise PunchError("This pay month's attendance is already confirmed; ask HR.")
        now = timezone.now()
        current = open_punch(employee, now)
        if kind == Punch.Kind.IN and current:
            raise PunchError(f"You clocked in at {_hm(current.at)}; clock out first.")
        if kind == Punch.Kind.OUT and current is None:
            raise PunchError("You have not clocked in.")
        place = {}
        if employee.phone_clock == Employee.PhoneClock.SITES:
            if employee.location_consent_at is None:
                raise PunchError("Agree to the location check first, or ask HR to enter your days.")
            if latitude in (None, "") or longitude in (None, ""):
                raise PunchError("Allow your phone to share its location, then try again.")
            lat = _coordinate(latitude, "latitude", 90)
            lon = _coordinate(longitude, "longitude", 180)
            try:
                metres = round(float(accuracy)) if accuracy not in (None, "") else None
            except (TypeError, ValueError):
                metres = None
            if metres is not None and metres > WORST_ACCURACY:
                raise PunchError(
                    f"Your phone's location is only accurate to {metres} m; "
                    "wait a moment or step outside, then try again."
                )
            site, away = nearest_site(lat, lon)
            if site is None:
                raise PunchError("HR has not set up any punch sites yet.")
            if away > site.radius_m:
                raise PunchError(
                    f"You are {away:,} m from the nearest site ({site.name}); "
                    f"clock {kind} within {site.radius_m:,} m of it."
                )
            place = {
                "latitude": lat,
                "longitude": lon,
                "accuracy_m": metres,
                "site": site,
                "distance_m": away,
            }
        return Punch.objects.create(employee=employee, kind=kind, at=now, created_by=user, **place)


# --- Into attendance -----------------------------------------------------------------------------


@dataclass
class Day:
    employee: Employee
    day: date
    time_in: datetime
    time_out: datetime


def _pairs(punches: list[Punch]) -> tuple[list[tuple[Punch, Punch]], list[Punch]]:
    """Clock-ins with their clock-outs, and the clock-ins never closed."""
    pairs, unclosed, current = [], [], None
    for p in punches:
        if p.kind == Punch.Kind.IN:
            if current is not None:
                unclosed.append(current)
            current = p
        elif current is not None:
            if p.at - current.at < timedelta(hours=OPEN_HOURS):
                pairs.append((current, p))
            else:
                unclosed.append(current)
            current = None
    if current is not None:
        unclosed.append(current)
    return pairs, unclosed


def nearest_shift(moment: time, shifts: list[Shift]) -> Shift | None:
    best, gap = None, None
    for shift in shifts:
        diff = abs(_minutes(moment) - _minutes(shift.start_time))
        diff = min(diff, 24 * 60 - diff)
        if diff <= NEAREST_SHIFT and (gap is None or diff < gap):
            best, gap = shift, diff
    return best


def bring_in(user: User, month, *, dry_run: bool) -> dict:
    if not employees.can_edit(user):
        raise PunchError("Only HR brings punches into attendance.")
    try:
        month = first_of(month) if month else periods.last_pay_month()
    except AttendanceError as error:
        raise PunchError(str(error)) from None
    first, last = periods.pay_period(month)
    today = timezone.localdate()
    start = timezone.make_aware(datetime.combine(first, time()))
    end = timezone.make_aware(datetime.combine(last + timedelta(days=2), time()))
    people = employees.visible(user)
    punches = list(
        Punch.objects.filter(employee__in=people, at__gte=start, at__lt=end)
        .select_related("employee", "employee__division")
        .order_by("employee__number", "at", "pk")
    )
    confirmed = set(
        AttendanceMonth.objects.filter(month=month, confirmed=True).values_list(
            "division_id", flat=True
        )
    )
    shifts = list(Shift.objects.filter(is_active=True))
    by_employee: dict[int, list[Punch]] = {}
    for p in punches:
        by_employee.setdefault(p.employee_id, []).append(p)
    days: dict[tuple[int, date], Day] = {}
    notes: list[str] = []
    for items in by_employee.values():
        employee = items[0].employee
        if employee.division_id in confirmed:
            notes.append(
                f"{employee.number}: pay month {month:%B %Y} is confirmed for "
                f"{employee.division.code}; nothing brought in."
            )
            continue
        pairs, unclosed = _pairs(items)
        for p in unclosed:
            moment = timezone.localtime(p.at)
            if first <= moment.date() <= last and moment.date() < today:
                notes.append(
                    f"{employee.number} {moment:%Y-%m-%d}: clocked in at {moment:%H:%M} but never "
                    "out; enter the day in the attendance sheet."
                )
        for p_in, p_out in pairs:
            t_in, t_out = timezone.localtime(p_in.at), timezone.localtime(p_out.at)
            day = t_in.date()
            if not first <= day <= last or day >= today:
                continue
            key = (employee.pk, day)
            if key in days:
                days[key].time_out = t_out
            else:
                days[key] = Day(employee, day, t_in, t_out)
    existing = {
        (d.employee_id, d.date): d.source.kind
        for d in AttendanceDay.objects.filter(
            employee__in=people, date__range=(first, last)
        ).select_related("source")
    }
    rows = []
    ordered = sorted(days.items(), key=lambda x: (x[1].employee.number, x[0][1]))
    for (employee_id, day), d in ordered:
        if existing.get((employee_id, day)) == AttendanceImport.Kind.SHEET:
            notes.append(
                f"{d.employee.number} {day:%Y-%m-%d}: kept as entered from the attendance sheet."
            )
            continue
        employee = d.employee
        if day < employee.join_date or (employee.leaving_date and day > employee.leaving_date):
            notes.append(f"{employee.number} {day:%Y-%m-%d}: not employed on that date.")
            continue
        time_in = d.time_in.time().replace(second=0, microsecond=0)
        time_out = d.time_out.time().replace(second=0, microsecond=0)
        row = Row(0, employee, day, nearest_shift(time_in, shifts), time_in, time_out, None, "")
        try:
            _measure(row)
        except AttendanceError as error:
            notes.append(f"{employee.number} {day:%Y-%m-%d}: {error}.")
            continue
        rows.append(row)
    result = {
        "month": month.isoformat()[:7],
        "period": periods.label(month),
        "punches": len(punches),
        "days": len(rows),
        "employees": len({r.employee.pk for r in rows}),
        "notes": notes[:200],
        "rows": [
            {
                "number": r.employee.number,
                "name": r.employee.full_name,
                "date": r.day,
                "time_in": r.time_in.strftime("%H:%M"),
                "time_out": r.time_out.strftime("%H:%M"),
                "shift": r.shift.code if r.shift else "",
            }
            for r in rows[:500]
        ],
        "saved": False,
    }
    if dry_run or not rows:
        return result
    fingerprint = hashlib.sha256(",".join(str(p.pk) for p in punches).encode()).hexdigest()
    label = f"Phone punches {month:%Y-%m}"
    with audit_context("punches_brought_in", label), transaction.atomic():
        source = AttendanceImport.objects.create(
            kind=AttendanceImport.Kind.PUNCHES,
            file_name=label,
            sha256=fingerprint,
            rows=len(rows),
            created_by=user,
        )
        for r in rows:
            AttendanceDay.objects.update_or_create(
                employee=r.employee,
                date=r.day,
                defaults={
                    "shift": r.shift,
                    "time_in": r.time_in,
                    "time_out": r.time_out,
                    "leave_type": None,
                    "remarks": "Phone punches",
                    "worked_minutes": r.worked,
                    "late_minutes": r.late,
                    "early_minutes": r.early,
                    "source": source,
                },
            )
    return result | {"saved": True}
