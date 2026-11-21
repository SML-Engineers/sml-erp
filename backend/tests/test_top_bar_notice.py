"""The top-bar notice (owner, 21 Nov 2026): the Admin asks to switch it on or off or change its
words, with a reason; it changes only when a Director other than the Admin approves. English is
shown with Sinhala below it, whatever language the person uses."""

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core import notice
from apps.core.models import AuditEvent, NoticeChange, Notification

from .test_access import admin, as_user, person  # noqa: F401

pytestmark = pytest.mark.django_db

ADMIN_URL = "/api/v1/access/notice/"
SEEN = "/api/v1/notice/"
EN = "Entering false information into the system is a punishable offence."
SI = "පද්ධතියට අසත්‍ය තොරතුරු ඇතුළත් කිරීම දඬුවම් ලැබිය හැකි වරදකි."


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


def ask(client, show=True, text_en=EN, text_si=SI, reason="Staff reminder"):
    return client.post(
        ADMIN_URL,
        {"show": show, "text_en": text_en, "text_si": text_si, "reason": reason},
        format="json",
    )


def test_the_notice_is_off_until_a_director_approves(admin, director):  # noqa: F811
    clerk = person("clerk@sml.lk", "clerk")
    assert as_user(clerk).get(SEEN).json() == {"show": False, "text_en": "", "text_si": ""}

    asked = ask(as_user(admin))
    assert asked.status_code == 201, asked.json()
    assert asked.json()["status"] == "waiting"
    # Still off while it waits.
    assert as_user(clerk).get(SEEN).json()["show"] is False
    # The Director is told and sees it in Access to confirm and on the Dashboard.
    note = Notification.objects.get(user=director)
    assert "notice" in note.title and note.link == "/admin/access-to-confirm"
    waiting = as_user(director).get("/api/v1/approvals/waiting/").json()
    assert {"document_type": "access", "label": "Access to confirm", "count": 1} in waiting
    listed = as_user(director).get("/api/v1/access-to-confirm/").json()["notice"]
    assert listed["text_en"] == EN and listed["can_decide"] is True

    approved = as_user(director).post(f"{ADMIN_URL}{asked.json()['id']}/approve/")
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    # Everyone sees both languages, whatever language they chose.
    assert as_user(clerk).get(SEEN).json() == {"show": True, "text_en": EN, "text_si": SI}
    assert Notification.objects.filter(user=admin, title__contains="approved").exists()
    assert AuditEvent.objects.filter(event="notice_change_approved").exists()


def test_the_admin_cannot_approve_their_own_change(admin, director):  # noqa: F811
    change_id = ask(as_user(admin)).json()["id"]
    refused = as_user(admin).post(f"{ADMIN_URL}{change_id}/approve/")
    assert refused.status_code == 400
    assert as_user(admin).get(SEEN).json()["show"] is False
    # Nor is it counted for the Admin.
    assert all(
        w["document_type"] != "access"
        for w in as_user(admin).get("/api/v1/approvals/waiting/").json()
    )


def test_only_the_admin_asks_and_only_the_director_decides(admin, director):  # noqa: F811
    clerk = person("clerk@sml.lk", "clerk")
    assert ask(as_user(clerk)).status_code == 403
    assert ask(as_user(director)).status_code in (400, 403)
    change_id = ask(as_user(admin)).json()["id"]
    accountant = person("accountant@sml.lk", "accountant")
    assert as_user(accountant).post(f"{ADMIN_URL}{change_id}/approve/").status_code in (400, 403)
    assert NoticeChange.objects.get(pk=change_id).status == "waiting"


def test_a_reason_and_both_languages_are_needed(admin, director):  # noqa: F811
    assert "reason" in ask(as_user(admin), reason=" ").json()["detail"]
    assert "both English and Sinhala" in ask(as_user(admin), text_si="").json()["detail"]
    assert "200 characters" in ask(as_user(admin), text_en="x" * 201).json()["detail"]
    assert not NoticeChange.objects.exists()


def test_one_change_waits_at_a_time_and_can_be_withdrawn(admin, director):  # noqa: F811
    first = ask(as_user(admin)).json()["id"]
    again = ask(as_user(admin), text_en="Another line")
    assert again.status_code == 400 and "Withdraw it first" in again.json()["detail"]
    withdrawn = as_user(admin).post(f"{ADMIN_URL}{first}/withdraw/")
    assert withdrawn.json()["status"] == "withdrawn"
    assert ask(as_user(admin), text_en="Another line").status_code == 201


def test_the_director_refuses_with_a_reason(admin, director):  # noqa: F811
    change_id = ask(as_user(admin)).json()["id"]
    no_reason = as_user(director).post(f"{ADMIN_URL}{change_id}/refuse/", {}, format="json")
    assert no_reason.status_code == 400
    refused = as_user(director).post(
        f"{ADMIN_URL}{change_id}/refuse/", {"reason": "Wording to be checked"}, format="json"
    )
    assert refused.json()["status"] == "refused"
    assert as_user(admin).get(SEEN).json()["show"] is False
    assert Notification.objects.filter(user=admin, title__contains="refused").exists()


def test_switching_off_also_waits_for_the_director(admin, director):  # noqa: F811
    on = ask(as_user(admin)).json()["id"]
    as_user(director).post(f"{ADMIN_URL}{on}/approve/")
    off = ask(as_user(admin), show=False, text_en="", text_si="", reason="Not needed now")
    assert off.status_code == 201
    assert as_user(admin).get(SEEN).json()["show"] is True  # until approved
    as_user(director).post(f"{ADMIN_URL}{off.json()['id']}/approve/")
    assert as_user(admin).get(SEEN).json()["show"] is False
    # The words are kept for switching on again.
    page = as_user(admin).get(ADMIN_URL).json()
    assert page["in_force"] == {"text_en": EN, "text_si": SI}
    # Asking for what is already in force is refused.
    assert ask(as_user(admin), show=False, reason="again").status_code == 400


def test_the_admin_page_offers_the_suggested_words(admin):  # noqa: F811
    page = as_user(admin).get(ADMIN_URL).json()
    assert page["defaults"] == {"text_en": notice.DEFAULT_EN, "text_si": notice.DEFAULT_SI}
    assert page["current"]["show"] is False and page["waiting"] is None


def test_the_database_keeps_decided_changes(admin, director):  # noqa: F811
    change_id = ask(as_user(admin)).json()["id"]
    as_user(director).post(f"{ADMIN_URL}{change_id}/approve/")
    for sql in (
        "UPDATE core_noticechange SET text_en = 'changed' WHERE id = %s",
        "UPDATE core_noticechange SET status = 'refused' WHERE id = %s",
        "DELETE FROM core_noticechange WHERE id = %s",
    ):
        with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql, [change_id])


def test_the_database_refuses_changing_what_was_asked(admin):  # noqa: F811
    change_id = ask(as_user(admin)).json()["id"]
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("UPDATE core_noticechange SET text_en = 'x' WHERE id = %s", [change_id])


def test_the_database_refuses_self_approval_and_a_shown_notice_without_words(admin):  # noqa: F811
    change = NoticeChange.objects.create(
        show=True, text_en=EN, text_si=SI, reason="r", requested_by=admin
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        NoticeChange.objects.filter(pk=change.pk).update(
            status="approved", decided_by=admin, decided_at=timezone.now()
        )
    NoticeChange.objects.filter(pk=change.pk).update(status="withdrawn")
    with pytest.raises(IntegrityError), transaction.atomic():
        NoticeChange.objects.create(
            show=True, text_en=EN, text_si="", reason="r", requested_by=admin
        )
