"""The audit log (backlog P0-05)."""

from datetime import timedelta

import pyotp
import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import access_admin
from apps.core.audit import audit_context
from apps.core.models import AccessOverride, AuditEvent, Division, User

from .conftest import PASSWORD, secret_of
from .test_access import as_user, person

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def rows(**filters):
    return list(AuditEvent.objects.filter(**filters).order_by("id"))


# --- What is recorded -------------------------------------------------------------------


def test_creating_a_record_is_logged_with_its_values():
    with audit_context("test", "setting up a new division"):
        division = Division.objects.create(code="TS", name="Tool Shop")
    [row] = rows(object_type="core.division", object_id=str(division.pk))
    assert row.action == "create"
    assert row.changes["name"] == [None, "Tool Shop"]
    assert row.reason == "setting up a new division"
    assert row.actor_email == "system"  # no signed-in user: a system job


def test_a_change_writes_one_row_with_old_and_new_values():
    division = Division.objects.get(code="IM")
    division.name = "Injection Moulding"
    division.save()
    [row] = rows(object_type="core.division", action="update")
    assert row.changes == {"name": ["Plastic Injection Moulding", "Injection Moulding"]}


def test_saving_without_a_change_writes_nothing():
    division = Division.objects.get(code="IM")
    division.save()
    assert rows(object_type="core.division", action="update") == []


def test_deleting_is_logged_with_the_old_values(admin):
    clerk = person("clerk@sml.lk", "clerk")
    as_user(admin).put(f"/api/v1/users/{clerk.pk}/roles/", {"roles": []}, format="json")
    [row] = rows(object_type="core.userrole", action="delete")
    assert row.changes["role"][0] == "Accounts Clerk"
    assert row.related_user == clerk


def test_secrets_are_never_written_to_the_log(user, client):
    client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    client.post(
        "/api/v1/auth/password/change/",
        {"current_password": PASSWORD, "new_password": "Another-Strong-77"},
        format="json",
    )
    [row] = rows(object_type="core.user", event="password_changed")
    assert row.changes["password"] == ["(hidden)", "(changed)"]
    assert "Another-Strong-77" not in str(row.changes)
    assert row.actor == user


def test_authenticator_secret_is_hidden(user, client):
    client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    client.post("/api/v1/auth/two-factor/setup/")
    secret = secret_of(user)
    client.post(
        "/api/v1/auth/two-factor/confirm/", {"code": pyotp.TOTP(secret).now()}, format="json"
    )
    logged = str([r.changes for r in rows(object_type="core.user")])
    assert secret not in logged
    assert rows(event="two_factor_enabled")


def test_routine_sign_ins_do_not_fill_the_log(user, client):
    before = AuditEvent.objects.count()
    client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}, format="json")
    assert AuditEvent.objects.count() == before  # last sign-in time is not an audited change


# --- Insert-only ------------------------------------------------------------------------


def test_audit_rows_cannot_be_changed_or_deleted():
    Division.objects.create(code="TS", name="Tool Shop")
    row = AuditEvent.objects.latest("id")
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditEvent.objects.filter(pk=row.pk).update(reason="tampered")
    with pytest.raises(DatabaseError), transaction.atomic():
        AuditEvent.objects.filter(pk=row.pk).delete()


def test_the_api_offers_no_way_to_change_the_log(director):
    client = as_user(director)
    assert client.post("/api/v1/audit/", {}).status_code in (403, 405)
    assert client.delete("/api/v1/audit/").status_code in (403, 405)


# --- Access changes, with who, address, event and reason -------------------------------


def test_role_changes_record_who_from_where_and_why(admin):
    clerk = person("clerk@sml.lk")
    client = APIClient(REMOTE_ADDR="10.0.0.5")
    client.force_authenticate(admin)
    client.put(
        f"/api/v1/users/{clerk.pk}/roles/",
        {"roles": ["clerk", "cashier"], "reason": "Only one finance person in December"},
        format="json",
    )
    created = rows(object_type="core.userrole", action="create", related_user=clerk)
    assert len(created) == 2
    assert all(r.actor == admin and r.event == "roles_changed" for r in created)
    assert all(r.reason == "Only one finance person in December" for r in created)
    assert all(r.ip_address == "10.0.0.5" and r.related_user == clerk for r in created)


def test_division_scope_changes_are_logged(admin):
    clerk = person("clerk@sml.lk", "clerk", divisions=["IM"])
    as_user(admin).put(
        f"/api/v1/users/{clerk.pk}/scope/",
        {"all_divisions": False, "divisions": ["IM", "WS"]},
        format="json",
    )
    [row] = rows(event="divisions_changed", changes__has_key="divisions")
    assert row.changes["divisions"] == [["IM"], ["IM", "WS"]]


def test_override_life_is_logged_from_request_to_end(admin, director):
    clerk = person("clerk@sml.lk", "clerk")
    created = (
        as_user(admin)
        .post(
            f"/api/v1/users/{clerk.pk}/overrides/",
            {"effect": "grant", "action": "record_payment", "reason": "Cashier on leave"},
            format="json",
        )
        .json()
    )
    as_user(director).post(f"/api/v1/overrides/{created['id']}/confirm/")
    as_user(admin).post(
        f"/api/v1/overrides/{created['id']}/revoke/", {"reason": "Cashier back"}, format="json"
    )

    events = [
        (r.event, r.actor_email)
        for r in rows(object_type="core.accessoverride", object_id=str(created["id"]))
    ]
    assert events == [
        ("access_granted", "admin@sml.lk"),
        ("access_confirmed", "director@sml.lk"),
        ("access_ended", "admin@sml.lk"),
    ]
    assert rows(event="access_ended")[0].reason == "Cashier back"


def test_expiry_and_deactivation_and_review_are_logged(admin, director):
    clerk = person("clerk@sml.lk", "clerk")
    as_user(admin).post(
        f"/api/v1/users/{clerk.pk}/overrides/",
        {"effect": "grant", "area": "stores", "level": "view", "reason": "Stock count"},
        format="json",
    )
    AccessOverride.objects.update(ends_on=timezone.localdate() - timedelta(days=1))
    access_admin.notify_expired_overrides()
    as_user(director).post(
        "/api/v1/access-review/", {"user": clerk.pk, "outcome": "confirmed"}, format="json"
    )
    as_user(admin).post(
        f"/api/v1/users/{clerk.pk}/deactivate/", {"reason": "Left the company"}, format="json"
    )

    assert rows(event="access_expired", related_user=clerk)
    assert rows(event="access_reviewed", related_user=clerk)[0].actor == director
    deactivated = rows(event="user_deactivated", object_type="core.user")
    assert deactivated[0].changes["is_active"] == [True, False]
    assert deactivated[0].reason == "Left the company"


def test_reset_logs_each_ended_override(admin):
    clerk = person("clerk@sml.lk", "clerk")
    client = as_user(admin)
    for area in ("stores", "quality"):
        client.post(
            f"/api/v1/users/{clerk.pk}/overrides/",
            {"effect": "grant", "area": area, "level": "view", "reason": "Audit support"},
            format="json",
        )
    client.post(f"/api/v1/users/{clerk.pk}/reset-overrides/", {"reason": "Done"}, format="json")
    assert len(rows(event="access_reset")) == 2


def test_new_users_are_logged(admin):
    as_user(admin).post("/api/v1/users/", {"email": "n@sml.lk", "full_name": "N"}, format="json")
    [row] = rows(event="user_created")
    assert row.changes["email"] == [None, "n@sml.lk"]
    assert row.changes["password"] == [None, "(hidden)"]


# --- Reading the log --------------------------------------------------------------------


def test_auditor_and_director_can_read_the_log_clerk_cannot(director):
    Division.objects.create(code="TS", name="Tool Shop")
    assert as_user(person("auditor@sml.lk", "auditor")).get("/api/v1/audit/").status_code == 200
    assert as_user(director).get("/api/v1/audit/").status_code == 200
    assert as_user(person("clerk@sml.lk", "clerk")).get("/api/v1/audit/").status_code == 403


def test_log_can_be_filtered_by_person(admin, director):
    clerk = person("clerk@sml.lk", "clerk")
    other = person("other@sml.lk", "clerk")
    as_user(admin).put(f"/api/v1/users/{clerk.pk}/roles/", {"roles": []}, format="json")
    as_user(admin).put(f"/api/v1/users/{other.pk}/roles/", {"roles": []}, format="json")

    data = as_user(director).get(f"/api/v1/audit/?user={clerk.pk}").json()
    assert data and all(r["related_user"] == clerk.pk for r in data)


def test_bad_filters_are_refused_politely(director):
    assert as_user(director).get("/api/v1/audit/?from=28-10-2026").status_code == 400


def test_users_created_from_the_command_line_are_logged_as_system():
    User.objects.create_user("cli@sml.lk", "Command Line", PASSWORD)
    assert rows(object_type="core.user", action="create")[-1].actor_email == "system"
