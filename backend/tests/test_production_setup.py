"""Reject and downtime reasons and the production settings (backlog P3-02): starting lists per
division kept by the Admin, a used reason never renamed in code or deleted; dated settings
(4 hours' grace, 5% rejects, 10% overrun) changed from today on, never in force."""

from datetime import date, timedelta
from decimal import Decimal as D

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core.models import Division
from apps.production import reasons
from apps.production.models import ProductionSetting, ReasonCode
from apps.production.reasons import ReasonError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db
URL = "/api/v1/production-setup/"


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


def test_the_starting_reasons_and_settings(admin):
    im = Division.objects.get(code="IM")
    downtime = reasons.active(im, "downtime")
    assert "MOULD-CHANGE" in {r.code for r in downtime}
    assert {r.code for r in downtime if r.planned} == {"PLANNED-PM", "NO-PLAN"}
    assert "SHORT-SHOT" in {r.code for r in reasons.active(im, "reject")}
    ws = Division.objects.get(code="WS")
    assert "MOULD-CHANGE" not in {r.code for r in reasons.active(ws, "downtime")}
    s = reasons.setting_on(date(2026, 11, 7))
    assert (s.grace_hours, s.reject_alert_pct, s.overrun_alert_pct, s.min_margin_pct) == (
        D("4.0"),
        D("5.00"),
        D("10.00"),
        None,
    )
    body = as_user(admin).get(URL).json()
    assert body["can_manage"] is True and body["settings"][0]["in_force"] is True


def test_the_admin_keeps_the_reasons(admin):
    added = as_user(admin).post(
        "/api/v1/production-reasons/",
        {"division": "IM", "kind": "reject", "code": "gate mark", "name": "Gate mark"},
        format="json",
    )
    assert added.status_code == 200, added.json()
    reason = ReasonCode.objects.get(code="GATE-MARK")
    assert reason.sort_order > ReasonCode.objects.get(division__code="IM", code="FLASH").sort_order
    with pytest.raises(ReasonError, match="Only a downtime reason can be planned"):
        reasons.add(
            admin, {"division": "IM", "kind": "reject", "code": "X", "name": "X", "planned": True}
        )
    with pytest.raises(ReasonError, match="already has a reject reason GATE-MARK"):
        reasons.add(admin, {"division": "IM", "kind": "reject", "code": "GATE-MARK", "name": "Y"})
    # The same code may be used by the other division.
    reasons.add(admin, {"division": "WS", "kind": "reject", "code": "GATE-MARK", "name": "Y"})
    changed = as_user(admin).patch(
        f"/api/v1/production-reasons/{reason.pk}/", {"name": "Gate vestige", "is_active": False}
    )
    assert changed.status_code == 200
    reason.refresh_from_db()
    assert (reason.name, reason.is_active) == ("Gate vestige", False)
    assert reason not in reasons.active(reason.division, "reject")
    # Once a shift report uses it, the code is fixed and it is never deleted.
    ReasonCode.objects.filter(pk=reason.pk).update(first_used_at=timezone.now())
    reason.refresh_from_db()
    with pytest.raises(ReasonError, match="its code cannot change"):
        reasons.change(admin, reason, {"code": "GATE"})
    with pytest.raises(ReasonError, match="deactivate it instead"):
        reasons.remove(admin, reason)
    with pytest.raises(DatabaseError), transaction.atomic():
        ReasonCode.objects.filter(pk=reason.pk).delete()
    planner = person("planner@sml.lk", "production_planner", divisions=["IM"])
    assert as_user(planner).post("/api/v1/production-reasons/", {}).status_code == 403


def test_settings_are_dated_and_never_changed_once_in_force(admin):
    today = timezone.localdate()
    later = today + timedelta(days=10)
    values = {
        "effective_from": later.isoformat(),
        "grace_hours": "3",
        "reject_alert_pct": "4%",
        "overrun_alert_pct": "12.5",
        "min_margin_pct": "15",
        "reason": "Tighter limits from the Production Manager's review",
    }
    for changed, message in [
        ({"effective_from": (today - timedelta(days=1)).isoformat()}, "today or later"),
        ({"grace_hours": "60"}, "0 to 48 hours"),
        ({"reject_alert_pct": "0"}, "more than 0"),
        ({"overrun_alert_pct": "1.555"}, "two decimal places"),
        ({"reason": ""}, "Give the reason"),
    ]:
        with pytest.raises(ReasonError, match=message):
            reasons.add_setting(admin, values | changed)
    done = as_user(admin).post(URL, values, format="json")
    assert done.status_code == 200, done.json()
    assert reasons.setting_on(today).grace_hours == D("4.0")  # today keeps the old values
    assert reasons.setting_on(later).reject_alert_pct == D("4.00")
    # The same future date entered again replaces it: it is not in force yet.
    reasons.add_setting(admin, values | {"grace_hours": "2.5"})
    assert reasons.setting_on(later).grace_hours == D("2.5")
    assert ProductionSetting.objects.count() == 2
    with pytest.raises(DatabaseError), transaction.atomic():
        ProductionSetting.objects.filter(effective_from=date(2026, 1, 1)).update(grace_hours=D("8"))
    hr = person("hr@sml.lk", "hr_payroll_officer", all_divisions=True)
    assert as_user(hr).post(URL, values, format="json").status_code == 403
