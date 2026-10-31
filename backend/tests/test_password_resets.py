"""Password resets: the Admin asks, the Director approves, the Admin makes a temporary
password shown once (owner's decision, 31 Oct 2026)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core import password_resets
from apps.core.access import AccessError
from apps.core.models import AuditEvent, Notification, PasswordReset, RecoveryCode, User

from .test_access import as_user, person

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def clerk():
    user = person("clerk@sml.lk", "clerk", all_divisions=True)
    RecoveryCode.objects.create(user=user, code_hash="x")
    return user


def test_the_admin_asks_the_director_approves_the_admin_makes_the_password(admin, director, clerk):
    reset = password_resets.request(admin, clerk, "Forgot it", with_authenticator=True)
    assert reset.status == "waiting"
    note = Notification.objects.get(user=director, event="admin_request_waiting")
    assert note.link == f"/admin/users/{clerk.pk}"
    with pytest.raises(AccessError, match="Only the Admin who asked"):
        password_resets.issue(admin, reset)  # not approved yet

    password_resets.decide(director, reset, approve=True)
    assert Notification.objects.filter(user=admin, event="admin_request_decided").exists()
    password = password_resets.issue(admin, reset)

    clerk.refresh_from_db()
    assert clerk.check_password(password) and clerk.must_change_password
    assert clerk.totp_confirmed_at is None and clerk.totp_secret_encrypted == ""
    assert not RecoveryCode.objects.filter(user=clerk).exists()
    reset.refresh_from_db()
    assert reset.status == "done"
    with pytest.raises(AccessError):
        password_resets.issue(admin, reset)  # once only
    events = set(AuditEvent.objects.values_list("event", flat=True))
    assert {
        "password_reset_requested",
        "password_reset_approved",
        "password_reset_done",
    } <= events


def test_a_password_only_reset_keeps_the_authenticator(admin, director, clerk):
    reset = password_resets.request(admin, clerk, "Forgot it")
    password_resets.decide(director, reset, approve=True)
    password_resets.issue(admin, reset)
    clerk.refresh_from_db()
    assert clerk.totp_confirmed_at is not None


def test_who_may_not_ask_or_decide(admin, director, clerk):
    with pytest.raises(AccessError, match="your own password"):
        password_resets.request(admin, admin, "Mine")
    with pytest.raises(AccessError, match="Only the Admin"):
        password_resets.request(director, clerk, "Help")
    with pytest.raises(AccessError, match="reason"):
        password_resets.request(admin, clerk, " ")
    reset = password_resets.request(admin, clerk, "Forgot it")
    with pytest.raises(AccessError, match="already open"):
        password_resets.request(admin, clerk, "Again")
    with pytest.raises(AccessError, match="Only the Director"):
        password_resets.decide(admin, reset, approve=True)
    both = person("both@sml.lk", "system_admin", "director", all_divisions=True)
    person("director2@sml.lk", "director", all_divisions=True)  # someone left to approve
    own = password_resets.request(both, director, "Lost phone")
    with pytest.raises(AccessError, match="Someone other than"):
        password_resets.decide(both, own, approve=True)  # asked for it
    with pytest.raises(AccessError, match="Someone other than"):
        password_resets.decide(director, own, approve=True)  # it is their own
    with pytest.raises(AccessError, match="reason for refusing"):
        password_resets.decide(director, reset, approve=False)
    password_resets.decide(director, reset, approve=False, reason="Ask her to try again")
    reset.refresh_from_db()
    assert reset.status == "refused"
    with pytest.raises(AccessError):
        password_resets.issue(admin, reset)


def test_with_no_one_to_approve_it_is_refused(admin):
    lone_director = person("director@sml.lk", "director", all_divisions=True)
    with pytest.raises(AccessError, match="Nobody else can approve"):
        password_resets.request(admin, lone_director, "Forgot it")
    assert not PasswordReset.objects.exists()


def test_an_approval_lapses_after_a_day(admin, director, clerk):
    reset = password_resets.request(admin, clerk, "Forgot it")
    password_resets.decide(director, reset, approve=True)
    PasswordReset.objects.filter(pk=reset.pk).update(
        decided_at=timezone.now() - timedelta(hours=25)
    )
    with pytest.raises(AccessError, match="lapsed"):
        password_resets.issue(admin, PasswordReset.objects.get(pk=reset.pk))
    password_resets.request(admin, clerk, "Again")  # a new one can be asked


def test_through_the_api(admin, director, clerk):
    url = f"/api/v1/users/{clerk.pk}/password-resets/"
    made = as_user(admin).post(url, {"reason": "Forgot it"}, format="json")
    assert made.status_code == 201, made.json()
    listed = as_user(director).get(url).json()
    assert listed["can_request"] is False
    [row] = listed["resets"]
    assert (row["status"], row["can_decide"], row["can_issue"]) == ("waiting", True, False)
    assert as_user(clerk).get(url).status_code == 403
    assert as_user(admin).post(f"/api/v1/password-resets/{row['id']}/approve/").status_code == 403
    approved = as_user(director).post(f"/api/v1/password-resets/{row['id']}/approve/")
    assert approved.json()["status"] == "approved"
    issued = as_user(admin).post(f"/api/v1/password-resets/{row['id']}/issue/").json()
    assert User.objects.get(pk=clerk.pk).check_password(issued["temporary_password"])
    again = as_user(admin).get(url).json()["resets"][0]
    assert again["status"] == "done" and "temporary_password" not in again
