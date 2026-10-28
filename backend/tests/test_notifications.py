"""Notifications: the bell and email (backlog P0-18)."""

import pytest
from django.core import mail
from django.db import transaction

from apps.core import approvals, notifications, tasks
from apps.core.models import Division, Notification

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

V = "voucher"


@pytest.fixture(autouse=True)
def worker(monkeypatch):
    """Stand in for the background worker: send the email at once."""
    monkeypatch.setattr(
        notifications, "_queue", lambda ids: [notifications.send_email(pk) for pk in ids]
    )


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def submit(user, doc_id=1):
    return approvals.submit(
        user,
        V,
        doc_id,
        created_by=user,
        amount="25000.00",
        division=Division.objects.get(code="WS"),
        title=f"Voucher WS26102900{doc_id}",
        link=f"/vouchers/{doc_id}",
    )


def titles(user):
    return [n.title for n in Notification.objects.filter(user=user).order_by("id")]


def test_the_next_approver_is_told_a_voucher_is_waiting(
    clerk, accountant, director, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        submit(clerk)
    assert titles(accountant) == ["Voucher WS261029001 is waiting for your approval (level 2)"]
    assert titles(director) == [] and titles(clerk) == []
    [email] = mail.outbox
    assert email.to == ["accountant@sml.lk"]
    assert email.subject == "SML ERP: Voucher WS261029001 is waiting for your approval (level 2)"
    assert "http://localhost:8080/vouchers/1" in email.body
    with django_capture_on_commit_callbacks(execute=True):
        approvals.approve(accountant, V, 1)
    assert titles(director) == ["Voucher WS261029001 is waiting for your approval (level 3)"]
    with django_capture_on_commit_callbacks(execute=True):
        approvals.approve(director, V, 1)
    assert titles(clerk) == ["Voucher WS261029001 was approved"]
    assert len(mail.outbox) == 3


def test_the_creator_is_told_when_returned_or_rejected_with_the_reason(clerk, accountant):
    submit(clerk)
    approvals.send_back(accountant, V, 1, reason="Attach the invoice")
    returned = Notification.objects.get(user=clerk)
    assert returned.title == "Voucher WS261029001 was returned to you"
    assert returned.body == "Attach the invoice" and returned.link == "/vouchers/1"
    submit(clerk, doc_id=2)
    approvals.reject(accountant, V, 2, reason="Duplicate")
    assert titles(clerk)[-1] == "Voucher WS261029002 was rejected"


def test_nobody_is_asked_to_approve_their_own_document(accountant):
    maker = person("maker@sml.lk", "clerk", "accountant", all_divisions=True)
    submit(maker)
    assert titles(maker) == []
    assert len(titles(accountant)) == 1


def test_each_person_chooses_bell_and_email_per_kind_of_event(
    clerk, accountant, django_capture_on_commit_callbacks
):
    notifications.set_preference(clerk, "document_returned", email=False)
    notifications.set_preference(accountant, "approval_waiting", in_app=False, email=False)
    with django_capture_on_commit_callbacks(execute=True):
        submit(clerk)
        approvals.send_back(accountant, V, 1, reason="Wrong payee")
    assert titles(accountant) == []  # switched off entirely
    returned = Notification.objects.get(user=clerk)
    assert (returned.in_app, returned.email) == (True, False)
    assert mail.outbox == []


def test_nothing_is_announced_if_the_action_is_undone(clerk, accountant):
    with pytest.raises(RuntimeError), transaction.atomic():
        submit(clerk)
        raise RuntimeError("the voucher could not be saved")
    assert not Notification.objects.exists()


def test_waiting_emails_are_sent_once_by_the_periodic_job(clerk, accountant, director):
    submit(clerk)  # no commit in a test, so the email waits for the periodic job
    assert mail.outbox == []
    assert tasks.send_waiting_notification_emails() == 1
    assert tasks.send_waiting_notification_emails() == 0
    assert len(mail.outbox) == 1
    approvals.approve(accountant, V, 1)
    director.is_active = False
    director.save()
    assert notifications.send_waiting_emails() == 0  # nothing goes to a deactivated user


# --- The bell API -----------------------------------------------------------------------


def test_the_bell_shows_my_notifications_and_counts_the_unread(clerk, accountant):
    submit(clerk, 1)
    submit(clerk, 2)
    client = as_user(accountant)
    body = client.get("/api/v1/notifications/").json()
    assert body["unread"] == 2
    assert [item["link"] for item in body["items"]] == ["/vouchers/2", "/vouchers/1"]
    first = body["items"][1]["id"]
    assert client.post("/api/v1/notifications/read/", {"ids": [first]}, format="json").json() == {
        "unread": 1
    }
    unread = client.get("/api/v1/notifications/?unread=1").json()["items"]
    assert [item["link"] for item in unread] == ["/vouchers/2"]
    # someone else cannot see or mark my notifications
    other = as_user(clerk)
    assert other.get("/api/v1/notifications/").json()["unread"] == 0
    other.post("/api/v1/notifications/read/", {}, format="json")
    assert client.post("/api/v1/notifications/read/", {}, format="json").json() == {"unread": 0}


def test_my_notification_choices(clerk):
    client = as_user(clerk)
    rows = client.get("/api/v1/notifications/preferences/").json()
    assert {r["event"] for r in rows} == set(notifications.EVENTS)
    assert all(r["in_app"] and r["email"] for r in rows)
    rows = client.put(
        "/api/v1/notifications/preferences/",
        {"event": "document_approved", "email": False},
        format="json",
    ).json()
    approved = next(r for r in rows if r["event"] == "document_approved")
    assert (approved["in_app"], approved["email"]) == (True, False)
    bad = client.put("/api/v1/notifications/preferences/", {"event": "x"}, format="json")
    assert bad.status_code == 400
