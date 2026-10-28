"""Shifts and rosters (backlog P0-10, spec 3A.2, 7.1A)."""

from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone

from apps.core.models import AuditEvent, Division
from apps.core.organisation import is_in_use as division_in_use
from apps.masters import rosters
from apps.masters.models import Crew, RosterAssignment, Section, Shift
from apps.masters.services import MastersError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db


def today():
    return timezone.localdate()


def tomorrow():
    return today() + timedelta(days=1)


def division(code="IM"):
    return Division.objects.get(code=code)


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def day_night():
    """12-hour Day and Night shifts, and the 6-day rotation Day, Day, Night, Night, Off, Off."""
    day = rosters.create_shift(
        code="D", name="Day 12-hour", start_time=time(7), end_time=time(19), break_minutes=60
    )
    night = rosters.create_shift(
        code="N", name="Night 12-hour", start_time=time(19), end_time=time(7), break_minutes=60
    )
    pattern = rosters.create_pattern(
        name="12-hour rotation", days=[day.pk, day.pk, night.pk, night.pk, None, None]
    )
    return day, night, pattern


def crews(*codes, div="IM"):
    return [rosters.create_crew(division=division(div), code=c) for c in codes]


def three_crew_roster(pattern, start=None, end=None):
    a, b, c = crews("A", "B", "C")
    return rosters.create_assignment(
        pattern=pattern,
        division=division(),
        start_date=start or tomorrow(),
        end_date=end,
        crews=[(a, 0), (b, 2), (c, 4)],
    )


# --- Shifts -----------------------------------------------------------------------------


def test_the_general_shift_is_ready_08_00_to_17_00():
    general = Shift.objects.get(code="G")
    assert (general.name, general.start_time, general.end_time) == ("General", time(8), time(17))
    assert general.working_minutes == 8 * 60
    assert not general.crosses_midnight


def test_a_shift_ending_after_midnight_is_detected(day_night):
    _, night, _ = day_night
    assert night.crosses_midnight
    assert night.length_minutes == 12 * 60
    assert night.working_minutes == 11 * 60


@pytest.mark.parametrize(
    "data, why",
    [
        ({"start_time": time(8), "end_time": time(8)}, "same time"),
        ({"break_minutes": 600}, "shorter than the shift"),
        ({"code": "G"}, "already used"),
        ({"code": "TOO-LONG"}, "1 to 5"),
        ({"name": "general"}, "already a shift"),
    ],
)
def test_a_shift_must_be_valid(data, why):
    base = {
        "code": "S2",
        "name": "Second",
        "start_time": time(14),
        "end_time": time(22),
        "break_minutes": 30,
    }
    with pytest.raises(MastersError, match=why):
        rosters.create_shift(**(base | data))


# --- Patterns ---------------------------------------------------------------------------


def test_a_pattern_shows_its_hours_per_cycle_and_per_week(day_night):
    _, _, pattern = day_night
    assert rosters.pattern_summary(pattern) == {
        "cycle_days": 6,
        "hours_per_cycle": 44.0,
        "average_hours_per_week": 51.33,
    }


def test_a_pattern_needs_a_working_day():
    with pytest.raises(MastersError, match="working day"):
        rosters.create_pattern(name="All off", days=[None, None])


# --- The roster calendar ----------------------------------------------------------------


def test_three_crews_two_days_apart_cover_day_and_night_every_day(day_night):
    day, night, pattern = day_night
    three_crew_roster(pattern)
    plan = rosters.schedule(division(), tomorrow(), 12)
    for _, entries in plan:
        on = sorted((e.shift.code, e.crew.code) for e in entries)
        assert [s for s, _ in on] == ["D", "N"]
    first_day = {e.crew.code: e.shift.code for e in plan[0][1]}
    assert first_day == {"A": "D", "B": "N"}  # crew C is off
    assert rosters.warnings(division(), tomorrow(), 28) == []


def test_a_night_shift_belongs_to_the_date_it_started(day_night):
    _, _, pattern = day_night
    three_crew_roster(pattern)
    start = tomorrow()
    two_am_next_day = datetime.combine(start + timedelta(days=1), time(2))
    [running] = rosters.on_shift_at(two_am_next_day, division())
    assert running.shift.code == "N"
    assert running.day == start
    assert running.crew.code == "B"


def test_a_day_or_night_with_no_crew_is_warned(day_night):
    _, _, pattern = day_night
    a, b = crews("A", "B")
    rosters.create_assignment(
        pattern=pattern, division=division(), start_date=tomorrow(), crews=[(a, 0), (b, 2)]
    )
    found = rosters.warnings(division(), tomorrow(), 6)
    assert f"{(tomorrow() + timedelta(days=2)).isoformat()}: no crew on Day 12-hour (IM)." in found
    assert any("no crew on Night 12-hour" in w for w in found)


def test_a_crew_cannot_follow_two_rosters_at_once(day_night):
    _, _, pattern = day_night
    three_crew_roster(pattern)
    a = Crew.objects.get(code="A")
    with pytest.raises(MastersError, match="only one roster at a time"):
        rosters.create_assignment(
            pattern=pattern,
            division=division(),
            start_date=tomorrow() + timedelta(days=10),
            crews=[(a, 0)],
        )


def test_staff_on_general_shift_and_crews_can_share_a_section(day_night):
    _, _, pattern = day_night
    general = rosters.create_pattern(
        name="General Mon-Sat",
        days=[Shift.objects.get(code="G").pk] * 6 + [None],
    )
    rosters.create_assignment(pattern=general, division=division(), start_date=tomorrow())
    a, b, c = crews("A", "B", "C")
    rosters.create_assignment(
        pattern=pattern,
        division=division(),
        section=Section.objects.get(code="IM-MLD"),
        start_date=tomorrow(),
        crews=[(a, 0), (b, 2), (c, 4)],
    )
    [(_, entries)] = rosters.schedule(division(), tomorrow(), 1, Section.objects.get(code="IM-MLD"))
    assert sorted((e.shift.code, e.crew.code if e.crew else "-") for e in entries) == [
        ("D", "A"),
        ("G", "-"),
        ("N", "B"),
    ]


def test_a_seasonal_change_is_a_new_roster_from_a_date(day_night):
    day, night, pattern = day_night
    first = three_crew_roster(pattern, start=today())
    change_on = today() + timedelta(days=7)
    rosters.update_assignment(first, {"end_date": change_on - timedelta(days=1)})
    general = rosters.create_pattern(name="General week", days=[Shift.objects.get(code="G").pk])
    rosters.create_assignment(pattern=general, division=division(), start_date=change_on)
    plan = dict(rosters.schedule(division(), today(), 10))
    assert {e.shift.code for e in plan[change_on - timedelta(days=1)]} == {"D", "N"}
    assert {e.shift.code for e in plan[change_on]} == {"G"}


# --- Past days never change -------------------------------------------------------------


def test_a_roster_cannot_start_in_the_past(day_night):
    _, _, pattern = day_night
    with pytest.raises(MastersError, match="past"):
        rosters.create_assignment(
            pattern=pattern, division=division(), start_date=today() - timedelta(days=1)
        )


def test_a_started_roster_can_only_get_an_end_date(day_night):
    _, _, pattern = day_night
    started = three_crew_roster(pattern, start=today())
    with pytest.raises(MastersError, match="only its end date"):
        rosters.update_assignment(started, {"start_date": tomorrow()})
    with pytest.raises(MastersError, match="before today"):
        rosters.update_assignment(started, {"end_date": today() - timedelta(days=1)})
    with pytest.raises(MastersError, match="cannot be removed"):
        rosters.delete_assignment(started, reason="x")
    rosters.update_assignment(started, {"end_date": today() + timedelta(days=30)})
    assert RosterAssignment.objects.get(pk=started.pk).end_date == today() + timedelta(days=30)


def test_a_future_roster_can_be_changed_or_removed(day_night):
    _, _, pattern = day_night
    future = three_crew_roster(pattern)
    rosters.update_assignment(future, {"start_date": tomorrow() + timedelta(days=3)})
    rosters.delete_assignment(future, reason="planned by mistake")
    assert not RosterAssignment.objects.exists()


def test_shift_times_and_pattern_days_are_fixed_once_a_roster_using_them_starts(day_night):
    day, night, pattern = day_night
    three_crew_roster(pattern, start=today())
    with pytest.raises(MastersError, match="cannot change"):
        rosters.update_shift(day, {"start_time": time(6)})
    with pytest.raises(MastersError, match="cannot change"):
        rosters.update_pattern(pattern, {"days": [day.pk, night.pk, None]})
    renamed = rosters.update_shift(day, {"name": "Day shift"})
    assert renamed.name == "Day shift"


def test_a_crew_on_a_current_roster_cannot_be_made_inactive(day_night):
    _, _, pattern = day_night
    three_crew_roster(pattern)
    with pytest.raises(MastersError, match="current or future roster"):
        rosters.update_crew(Crew.objects.get(code="A"), {"is_active": False}, reason="x")


def test_crews_and_rosters_do_not_fix_a_division_code(day_night):
    _, _, pattern = day_night
    three_crew_roster(pattern)
    assert not division_in_use(division())


# --- The settings page API --------------------------------------------------------------


def test_the_admin_sets_up_a_rotation_and_previews_four_weeks(admin):
    client = as_user(admin)
    for code, name, start, end in (
        ("D", "Day", "07:00", "19:00"),
        ("N", "Night", "19:00", "07:00"),
    ):
        response = client.post(
            "/api/v1/settings/shifts/",
            {"code": code, "name": name, "start_time": start, "end_time": end, "break_minutes": 60},
            format="json",
        )
        assert response.status_code == 201, response.json()
    response = client.post(
        "/api/v1/settings/roster-patterns/",
        {"name": "12-hour rotation", "days": ["D", "D", "N", "N", "", ""]},
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert response.json()["summary"]["cycle_days"] == 6
    pattern_id = response.json()["id"]
    for code in "ABC":
        response = client.post(
            "/api/v1/settings/crews/", {"division": "IM", "code": code}, format="json"
        )
        assert response.status_code == 201, response.json()
    response = client.post(
        "/api/v1/settings/rosters/",
        {
            "pattern": pattern_id,
            "division": "IM",
            "start_date": tomorrow().isoformat(),
            "crews": [
                {"crew": "A", "start_day": 1},
                {"crew": "B", "start_day": 3},
                {"crew": "C", "start_day": 5},
            ],
            "reason": "night production from November",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    assert AuditEvent.objects.filter(event="roster_assigned").exists()

    preview = client.get(
        "/api/v1/settings/rosters/preview/",
        {"division": "IM", "start": tomorrow().isoformat()},
    ).json()
    assert len(preview["days"]) == 28
    first = {s["crew"]: s["shift"] for s in preview["days"][0]["shifts"]}
    assert first == {"A": "D", "B": "N"}
    assert preview["warnings"] == []


def test_only_settings_managers_change_shifts_and_rosters():
    clerk = person("clerk@sml.lk", "clerk")
    director = person("director@sml.lk", "director", all_divisions=True)
    data = {"code": "S2", "name": "Second", "start_time": "14:00", "end_time": "22:00"}
    assert as_user(clerk).get("/api/v1/settings/shifts/").status_code == 403
    assert as_user(director).get("/api/v1/settings/shifts/").status_code == 200
    for user in (clerk, director):
        assert (
            as_user(user).post("/api/v1/settings/shifts/", data, format="json").status_code == 403
        )
