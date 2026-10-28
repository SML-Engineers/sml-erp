"""Per-user overrides and access administration (backlog P0-04b, spec 1.3)."""

from datetime import timedelta

import pytest
from django.contrib.sessions.models import Session
from django.core import mail
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import access, access_admin, hard_controls
from apps.core.models import AccessOverride, AccessReview, Role, User, UserRole

from .conftest import PASSWORD
from .test_access import as_user, person

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def rights(user):
    return access.effective_access(User.objects.get(pk=user.pk))


def grant(client, user, **body):
    body.setdefault("reason", "Needed for month-end")
    return client.post(
        f"/api/v1/users/{user.pk}/overrides/", {"effect": "grant", **body}, format="json"
    )


def remove(client, user, **body):
    body.setdefault("reason", "Not needed in this job")
    return client.post(
        f"/api/v1/users/{user.pk}/overrides/", {"effect": "remove", **body}, format="json"
    )


# --- Grants and removals ----------------------------------------------------------------


def test_admin_grants_access_to_one_user(admin):
    clerk = person("clerk@sml.lk", "clerk")
    response = grant(as_user(admin), clerk, area="stores", level="view")
    assert response.status_code == 201
    assert response.json()["status"] == "active"
    assert rights(clerk).has("stores", "view")
    assert not rights(person("other@sml.lk", "clerk")).has("stores", "view")


def test_admin_removes_access_a_role_gives(admin):
    accountant = person("acc@sml.lk", "accountant")
    remove(as_user(admin), accountant, area="banking", level="view")
    assert not rights(accountant).has("banking", "view")
    assert not rights(accountant).has("banking", "manage")  # removing View removes the area
    assert rights(accountant).has("accounting", "manage")  # the rest is untouched


def test_removing_a_higher_level_keeps_the_lower_ones(admin):
    accountant = person("acc@sml.lk", "accountant")
    remove(as_user(admin), accountant, area="accounting", level="manage")
    assert not rights(accountant).has("accounting", "manage")
    assert rights(accountant).has("accounting", "enter")
    assert rights(accountant).has("accounting", "view")


def test_removing_enter_keeps_view(admin):
    clerk = person("clerk@sml.lk", "clerk")
    remove(as_user(admin), clerk, area="vouchers", level="enter")
    assert not rights(clerk).has("vouchers", "enter")
    assert rights(clerk).has("vouchers", "view")


def test_a_removal_beats_a_grant(admin):
    clerk = person("clerk@sml.lk", "clerk")
    client = as_user(admin)
    grant(client, clerk, area="stores", level="view")
    remove(client, clerk, area="stores", level="view")
    assert not rights(clerk).has("stores", "view")


def test_a_reason_is_required(admin):
    clerk = person("clerk@sml.lk", "clerk")
    response = grant(as_user(admin), clerk, area="stores", level="view", reason="  ")
    assert response.status_code == 400
    assert not AccessOverride.objects.exists()


def test_end_date_cannot_be_in_the_past(admin):
    clerk = person("clerk@sml.lk", "clerk")
    yesterday = (timezone.localdate() - timedelta(days=1)).isoformat()
    response = grant(as_user(admin), clerk, area="stores", level="view", ends_on=yesterday)
    assert response.status_code == 400


def test_temporary_access_stops_after_its_end_date_and_the_user_is_told(admin):
    clerk = person("clerk@sml.lk", "clerk")
    grant(
        as_user(admin), clerk, area="stores", level="view", ends_on=timezone.localdate().isoformat()
    )
    assert rights(clerk).has("stores", "view")  # still valid on its last day

    AccessOverride.objects.update(ends_on=timezone.localdate() - timedelta(days=1))
    assert not rights(clerk).has("stores", "view")

    assert access_admin.notify_expired_overrides() == 1
    assert mail.outbox[0].to == ["clerk@sml.lk"]
    assert "temporary" in mail.outbox[0].subject.lower()
    assert access_admin.notify_expired_overrides() == 0  # told only once


# --- Sensitive grants need the Director --------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {"area": "vouchers", "level": "approve"},
        {"area": "users", "level": "manage"},
        {"area": "hr_payroll", "level": "view"},
        {"action": "record_payment"},
        {"action": "delete_submitted_voucher"},
        {"action": "change_bank_details"},
        {"action": "close_period"},
    ],
)
def test_sensitive_grants_wait_for_the_director(admin, director, body):
    clerk = person("clerk@sml.lk", "clerk")
    created = grant(as_user(admin), clerk, **body).json()
    assert created["status"] == "pending"
    level_or_action = body.get("action") or body["level"]
    check = (
        rights(clerk).can if "action" in body else (lambda lv: rights(clerk).has(body["area"], lv))
    )
    assert not check(level_or_action)

    confirm = as_user(director).post(f"/api/v1/overrides/{created['id']}/confirm/")
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "active"
    assert (
        rights(clerk).can(body["action"])
        if "action" in body
        else rights(clerk).has(body["area"], body["level"])
    )


def test_only_the_director_confirms(admin):
    clerk = person("clerk@sml.lk", "clerk")
    other_admin = person("admin2@sml.lk", "system_admin")
    created = grant(as_user(admin), clerk, action="record_payment").json()
    response = as_user(other_admin).post(f"/api/v1/overrides/{created['id']}/confirm/")
    assert response.status_code == 403
    assert not rights(clerk).can("record_payment")


def test_the_requester_cannot_confirm_their_own_request(director):
    # A director who also manages users asks for the grant: someone else must confirm it.
    UserRole.objects.create(user=director, role=Role.objects.get(code="system_admin"))
    clerk = person("clerk@sml.lk", "clerk")
    created = grant(as_user(director), clerk, action="record_payment").json()
    response = as_user(director).post(f"/api/v1/overrides/{created['id']}/confirm/")
    assert response.status_code == 403


def test_removals_take_effect_immediately_without_confirmation(admin):
    cashier = person("cash@sml.lk", "cashier")
    created = remove(as_user(admin), cashier, action="record_payment").json()
    assert created["status"] == "active"
    assert not rights(cashier).can("record_payment")


def test_director_sees_grants_waiting_for_confirmation(admin, director):
    clerk = person("clerk@sml.lk", "clerk")
    grant(as_user(admin), clerk, action="record_payment")
    grant(as_user(admin), clerk, area="stores", level="view")  # not sensitive
    waiting = as_user(director).get("/api/v1/overrides/pending/").json()
    assert [o["action"] for o in waiting] == ["record_payment"]


# --- Hard controls ----------------------------------------------------------------------


def test_no_override_lets_anyone_approve_their_own_document(admin, director):
    clerk = person("clerk@sml.lk", "clerk")
    created = grant(as_user(admin), clerk, area="vouchers", level="approve").json()
    as_user(director).post(f"/api/v1/overrides/{created['id']}/confirm/")
    assert rights(clerk).has("vouchers", "approve")

    refusal = hard_controls.approval_refusal(clerk, created_by_id=clerk.pk, earlier_approver_ids=[])
    assert refusal == "You cannot approve a document you created."


def test_no_one_approves_one_document_at_two_levels(director):
    refusal = hard_controls.approval_refusal(
        director, created_by_id=999, earlier_approver_ids=[director.pk]
    )
    assert refusal is not None


def test_every_voucher_needs_three_levels():
    assert hard_controls.voucher_levels_required() == 3


def test_admin_cannot_change_their_own_overrides(admin):
    response = grant(as_user(admin), admin, area="payments", level="view")
    assert response.status_code == 403
    assert not AccessOverride.objects.exists()


def test_admin_cannot_end_overrides_on_themselves(admin):
    other = person("admin2@sml.lk", "system_admin")
    created = grant(as_user(other), admin, area="stores", level="view").json()
    response = as_user(admin).post(
        f"/api/v1/overrides/{created['id']}/revoke/", {"reason": "x"}, format="json"
    )
    assert response.status_code == 403


# --- Copy, reset, history ---------------------------------------------------------------


def test_copy_access_from_another_user(admin):
    source = person("old@sml.lk", "clerk", divisions=["IM"])
    as_user(admin).post(
        f"/api/v1/users/{source.pk}/overrides/",
        {"effect": "grant", "area": "stores", "level": "view", "reason": "Stock checks"},
        format="json",
    )
    target = person("new@sml.lk")
    response = as_user(admin).post(
        f"/api/v1/users/{target.pk}/copy-access/", {"source_user": source.pk}, format="json"
    )
    assert response.status_code == 200
    target = User.objects.get(pk=target.pk)
    assert list(target.divisions.values_list("code", flat=True)) == ["IM"]
    assert rights(target).has("vouchers", "enter")
    assert rights(target).has("stores", "view")


def test_reset_to_role_defaults(admin):
    clerk = person("clerk@sml.lk", "clerk")
    client = as_user(admin)
    grant(client, clerk, area="stores", level="view")
    remove(client, clerk, area="vouchers", level="enter")
    response = client.post(
        f"/api/v1/users/{clerk.pk}/reset-overrides/", {"reason": "Job review"}, format="json"
    )
    assert response.json() == {"ended": 2}
    assert not rights(clerk).has("stores", "view")
    assert rights(clerk).has("vouchers", "enter")


def test_grid_shows_role_default_override_and_result(admin):
    accountant = person("acc@sml.lk", "accountant")
    remove(as_user(admin), accountant, area="banking", level="manage")
    grid = as_user(admin).get(f"/api/v1/users/{accountant.pk}/access/").json()
    banking = next(a for a in grid["areas"] if a["area"] == "banking")
    manage = next(lv for lv in banking["levels"] if lv["level"] == "manage")
    assert manage["from_roles"] is True
    assert manage["override"]["effect"] == "remove"
    assert manage["effective"] is False


def test_history_keeps_ended_overrides(admin):
    clerk = person("clerk@sml.lk", "clerk")
    created = grant(as_user(admin), clerk, area="stores", level="view").json()
    as_user(admin).post(
        f"/api/v1/overrides/{created['id']}/revoke/", {"reason": "Done"}, format="json"
    )
    history = as_user(admin).get(f"/api/v1/users/{clerk.pk}/history/").json()
    assert history["overrides"][0]["status"] == "revoked"
    assert history["overrides"][0]["revoke_reason"] == "Done"


def test_clerk_cannot_reach_user_access_pages():
    clerk = person("clerk@sml.lk", "clerk")
    other = person("other@sml.lk", "clerk")
    assert as_user(clerk).get(f"/api/v1/users/{other.pk}/access/").status_code == 403
    assert grant(as_user(clerk), other, area="stores", level="view").status_code == 403


# --- Leavers and inactivity -------------------------------------------------------------


def test_deactivating_a_leaver_ends_sessions_and_overrides(admin):
    leaver = person("leaver@sml.lk", "clerk")
    leaver.totp_confirmed_at = None
    leaver.save()
    browser = APIClient()
    browser.post(
        "/api/v1/auth/login/", {"email": leaver.email, "password": PASSWORD}, format="json"
    )
    assert Session.objects.count() == 1
    grant(as_user(admin), leaver, area="stores", level="view")

    response = as_user(admin).post(
        f"/api/v1/users/{leaver.pk}/deactivate/", {"reason": "Left the company"}, format="json"
    )
    assert response.status_code == 200
    assert Session.objects.count() == 0
    assert browser.get("/api/v1/auth/me/").json()["authenticated"] is False
    assert leaver.access_overrides.get().status == "revoked"
    assert User.objects.filter(pk=leaver.pk, is_active=False).exists()  # record stays


def test_accounts_unused_for_90_days_are_deactivated():
    idle = person("idle@sml.lk", "clerk")
    recent = person("recent@sml.lk", "clerk")
    User.objects.filter(pk=idle.pk).update(last_login=timezone.now() - timedelta(days=91))
    User.objects.filter(pk=recent.pk).update(last_login=timezone.now() - timedelta(days=5))

    assert access_admin.deactivate_inactive_accounts() == ["idle@sml.lk"]
    assert not User.objects.get(pk=idle.pk).is_active
    assert User.objects.get(pk=recent.pk).is_active


def test_the_last_administrator_is_never_deactivated_for_inactivity(admin):
    User.objects.filter(pk=admin.pk).update(last_login=timezone.now() - timedelta(days=200))
    assert access_admin.deactivate_inactive_accounts() == []
    assert User.objects.get(pk=admin.pk).is_active


# --- Access review ----------------------------------------------------------------------


def test_quarterly_review_lists_everyone_with_sensitive_access(admin, director):
    cashier = person("cash@sml.lk", "cashier")
    grant(as_user(admin), cashier, area="stores", level="view")
    report = as_user(director).get("/api/v1/access-review/").json()
    row = next(r for r in report["rows"] if r["email"] == "cash@sml.lk")
    assert "Record supplier payments" in row["sensitive_access"]
    assert row["overrides"][0]["target"] == "stores view"
    assert row["review"] is None
    assert report["period"].startswith(str(timezone.localdate().year))


def test_director_records_the_review(director):
    clerk = person("clerk@sml.lk", "clerk")
    response = as_user(director).post(
        "/api/v1/access-review/", {"user": clerk.pk, "outcome": "confirmed"}, format="json"
    )
    assert response.status_code == 200
    review = AccessReview.objects.get(user=clerk)
    assert review.reviewed_by == director
    assert review.period == access_admin.current_period()


def test_only_the_director_records_the_review(admin):
    clerk = person("clerk@sml.lk", "clerk")
    response = as_user(admin).post(
        "/api/v1/access-review/", {"user": clerk.pk, "outcome": "confirmed"}, format="json"
    )
    assert response.status_code == 403


def test_review_flags_unconfirmed_sensitive_grants(admin, director):
    clerk = person("clerk@sml.lk", "clerk")
    grant(as_user(admin), clerk, action="record_payment")
    row = next(
        r
        for r in as_user(director).get("/api/v1/access-review/").json()["rows"]
        if r["email"] == "clerk@sml.lk"
    )
    assert row["pending_sensitive"] == 1


def test_period_names():
    from datetime import date

    assert access_admin.current_period(date(2026, 10, 28)) == "2026-Q4"
    assert access_admin.current_period(date(2027, 1, 1)) == "2027-Q1"
