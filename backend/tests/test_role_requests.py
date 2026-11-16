"""Every new role waits for the Director (owner, 15 Nov 2026). The Admin gives a role; it does
not work until someone who confirms sensitive access (the Director), other than the person
who asked and the person it is for, confirms it. Removing a role works at once. The
Director is told and sees it on the Dashboard; the Admin hears the decision."""

import pytest
from django.db import IntegrityError, transaction

from apps.core import access
from apps.core.models import Notification, Role, RoleRequest, User

from .test_access import admin, as_user, person  # noqa: F401

pytestmark = pytest.mark.django_db


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def rights(user):
    return access.effective_access(User.objects.get(pk=user.pk))


def roles(client, user, codes, reason="New job"):
    return client.put(
        f"/api/v1/users/{user.pk}/roles/", {"roles": codes, "reason": reason}, format="json"
    )


def test_a_new_role_waits_for_the_director(admin, director):  # noqa: F811
    clerk = person("clerk@sml.lk", "clerk")
    response = roles(as_user(admin), clerk, ["clerk", "cashier"])
    assert response.status_code == 200
    body = response.json()["user"]
    assert [r["code"] for r in body["roles"]] == ["clerk"]  # held
    assert [r["code"] for r in body["pending_roles"]] == ["cashier"]  # waiting
    assert not rights(clerk).has("payments", "enter")
    # The Director is told and sees it on the Dashboard.
    note = Notification.objects.get(user=director)
    assert "Cashier / Payment Officer" in note.title and note.link == "/admin/access-to-confirm"
    waiting = as_user(director).get("/api/v1/approvals/waiting/").json()
    assert {"document_type": "access", "label": "Access to confirm", "count": 1} in waiting
    # The Admin who asked cannot confirm it, nor is it counted for them.
    (req,) = as_user(admin).get("/api/v1/role-requests/").json()
    assert as_user(admin).post(f"/api/v1/role-requests/{req['id']}/confirm/").status_code == 400
    assert all(
        w["document_type"] != "access"
        for w in as_user(admin).get("/api/v1/approvals/waiting/").json()
    )

    confirmed = as_user(director).post(f"/api/v1/role-requests/{req['id']}/confirm/")
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    assert rights(clerk).has("payments", "enter")
    assert Notification.objects.filter(user=admin, title__contains="was confirmed").exists()
    assert as_user(director).get("/api/v1/role-requests/").json() == []


def test_the_director_refuses_with_a_reason_and_removing_works_at_once(admin, director):  # noqa: F811
    clerk = person("clerk@sml.lk", "clerk")
    roles(as_user(admin), clerk, ["clerk", "cashier"])
    req = RoleRequest.objects.get()
    url = f"/api/v1/role-requests/{req.pk}/refuse/"
    assert as_user(director).post(url, {"reason": ""}, format="json").status_code == 400
    assert as_user(director).post(url, {"reason": "Not his job"}, format="json").status_code == 200
    assert not rights(clerk).has("payments", "enter")
    # Removing a role needs nobody.
    roles(as_user(admin), clerk, [])
    assert not rights(clerk).has("vouchers", "enter")


def test_unticking_a_waiting_role_withdraws_it(admin, director):  # noqa: F811
    clerk = person("clerk@sml.lk", "clerk")
    roles(as_user(admin), clerk, ["clerk", "cashier"])
    roles(as_user(admin), clerk, ["clerk"])
    assert RoleRequest.objects.get().status == "withdrawn"
    # Saving again with it still ticked does not ask twice.
    roles(as_user(admin), clerk, ["clerk", "cashier"])
    roles(as_user(admin), clerk, ["clerk", "cashier"])
    assert RoleRequest.objects.filter(status="waiting").count() == 1


def test_copy_access_asks_the_director_too(admin, director):  # noqa: F811
    source = person("old@sml.lk", "cashier")
    target = person("new@sml.lk")
    response = as_user(admin).post(
        f"/api/v1/users/{target.pk}/copy-access/",
        {"source_user": source.pk, "reason": "Same job"},
        format="json",
    )
    assert response.status_code == 200
    assert [r["code"] for r in response.json()["user"]["pending_roles"]] == ["cashier"]
    assert not rights(target).has("payments", "enter")


def test_nobody_confirms_their_own_role_and_the_database_agrees(admin, director):  # noqa: F811
    second = person("director2@sml.lk", "director", all_divisions=True)
    # The Director asks the Admin's role for themselves: only another Director may confirm.
    req = RoleRequest.objects.create(
        user=director, role=Role.objects.get(code="cashier"), requested_by=admin
    )
    with pytest.raises(access.AccessError, match="Someone other"):
        access.confirm_role(director, req)
    access.confirm_role(second, req)
    other = RoleRequest.objects.create(
        user=second, role=Role.objects.get(code="clerk"), requested_by=admin
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        RoleRequest.objects.filter(pk=other.pk).update(status="confirmed", decided_by=second)


def test_with_no_director_to_confirm_a_role_works_at_once(admin):  # noqa: F811
    """A new system: the first Director's role cannot wait for a Director."""
    first = person("first@sml.lk")
    roles(as_user(admin), first, ["director"])
    assert rights(first).can("confirm_sensitive_grants")
    assert not RoleRequest.objects.exists()


def test_the_director_sees_everything_waiting_in_one_list(admin, director):  # noqa: F811
    clerk = person("clerk@sml.lk", "clerk")
    roles(as_user(admin), clerk, ["clerk", "cashier"])
    as_user(admin).post(
        f"/api/v1/users/{clerk.pk}/overrides/",
        {"effect": "grant", "area": "vouchers", "level": "approve", "reason": "Cover"},
        format="json",
    )
    as_user(admin).post(
        f"/api/v1/users/{clerk.pk}/password-resets/", {"reason": "Lost phone"}, format="json"
    )
    d = as_user(director).get("/api/v1/access-to-confirm/").json()
    assert d["can_confirm"] is True
    assert [(r["user"], r["code"], r["mine"]) for r in d["roles"]] == [
        (clerk.full_name, "cashier", False)
    ]
    assert [(g["user_name"], g["area"], g["level"]) for g in d["grants"]] == [
        (clerk.full_name, "vouchers", "approve")
    ]
    assert [(r["user_name"], r["can_decide"]) for r in d["resets"]] == [(clerk.full_name, True)]
    waiting = as_user(director).get("/api/v1/approvals/waiting/").json()
    assert {"document_type": "access", "label": "Access to confirm", "count": 3} in waiting
    assert as_user(clerk).get("/api/v1/access-to-confirm/").status_code == 403
