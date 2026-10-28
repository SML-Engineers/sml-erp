"""Sending documents and reports by email (backlog P0-19, spec 3B)."""

import hashlib

import pytest
from django.core import mail
from django.core.mail import EmailMessage
from django.db import transaction
from django.db.utils import DatabaseError

from apps.core import crypto, document_email
from apps.core.document_email import EmailError
from apps.core.models import AuditEvent, MailAccount, SentEmail

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

URL = "/api/v1/settings/document-email/"


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def finance(admin):
    """The sending mailbox, set up as the Admin would."""
    document_email.update_account(
        admin,
        {
            "from_name": "SML Engineers Finance",
            "from_address": "finance@smlengineers.lk",
            "reply_to": "accounts@smlengineers.lk",
            "copy_to": "finance@smlengineers.lk",
            "host": "smtp.hostinger.com",
            "port": 465,
            "security": "ssl",
            "username": "finance@smlengineers.lk",
            "password": "Mailbox-Secret-1",
        },
        reason="go-live",
    )
    return MailAccount.get()


# --- The sending account ----------------------------------------------------------------


def test_the_mailbox_password_is_stored_encrypted_and_never_returned(admin, finance):
    assert finance.password_encrypted != "Mailbox-Secret-1"
    assert crypto.decrypt(finance.password_encrypted) == "Mailbox-Secret-1"
    body = as_user(admin).get(URL).json()
    assert body["has_password"] is True and body["is_ready"] is True
    assert "password" not in body and "password_encrypted" not in body
    assert "Mailbox-Secret-1" not in str(body)
    events = AuditEvent.objects.filter(event="mail_account_changed")
    assert events.exists()
    assert all("Mailbox-Secret-1" not in str(e.changes) for e in events)
    # leaving the password out keeps it; only a new one replaces it
    document_email.update_account(admin, {"from_name": "Finance"})
    assert crypto.decrypt(MailAccount.get().password_encrypted) == "Mailbox-Secret-1"


def test_only_the_admin_changes_the_sending_account(accountant):
    assert as_user(accountant).get(URL).status_code == 200
    response = as_user(accountant).put(URL, {"host": "evil.example"}, format="json")
    assert response.status_code == 403
    with pytest.raises(EmailError, match="Only the Admin"):
        document_email.update_account(accountant, {"host": "evil.example"})


@pytest.mark.parametrize(
    "values, why",
    [
        ({"from_address": "finance at sml"}, "not a valid email"),
        ({"port": 70000}, "between 1 and 65535"),
        ({"security": "tls13"}, "connection security"),
        ({"host": "smtp.example.com/x"}, "host name"),
        ({"host": "smtp.example.com", "from_address": ""}, "sent from"),
    ],
)
def test_the_sending_account_must_be_valid(admin, values, why):
    with pytest.raises(EmailError, match=why):
        document_email.update_account(admin, values)


def test_a_test_email_checks_the_settings(admin, finance, monkeypatch):
    result = as_user(admin).post(f"{URL}test/", {"to": "owner@sml.lk"}, format="json").json()
    assert result["test_ok"] is True and result["last_test_ok"] is True
    [sent] = mail.outbox
    assert sent.to == ["owner@sml.lk"]
    assert sent.from_email == '"SML Engineers Finance" <finance@smlengineers.lk>'

    def refuse(self, *args, **kwargs):
        raise OSError("535 authentication failed")

    monkeypatch.setattr(EmailMessage, "send", refuse)
    result = document_email.send_test(admin, "owner@sml.lk")
    assert result["test_ok"] is False and "535 authentication failed" in result["test_error"]
    assert MailAccount.get().last_test_ok is False


# --- Default messages -------------------------------------------------------------------


def test_every_kind_of_document_has_a_default_message(admin):
    rows = as_user(admin).get(f"{URL}templates/").json()
    kinds = {r["kind"] for r in rows}
    assert {"quotation", "tax_invoice", "customer_statement", "report"} <= kinds
    assert all(r["subject"] and r["body"] for r in rows)
    invoice = next(r for r in rows if r["kind"] == "tax_invoice")
    assert {"customer_name", "recipient_name", "due_date"} & {
        p["name"] for p in invoice["placeholders"]
    }


def test_the_admin_sets_a_default_message_with_known_placeholders_only(admin, accountant):
    url = f"{URL}templates/tax_invoice/"
    body = {
        "subject": "Invoice {document_number}",
        "body": "Dear {recipient_name}, due {due_date}.",
    }
    assert as_user(accountant).put(url, body, format="json").status_code == 403
    response = as_user(admin).put(url, body, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["subject"] == "Invoice {document_number}"
    bad = {"subject": "Invoice {document_number}", "body": "Pay {bank_password}"}
    response = as_user(admin).put(url, bad, format="json")
    assert response.status_code == 400 and "{bank_password}" in response.json()["detail"]
    with pytest.raises(EmailError, match="unmatched"):
        document_email.update_template(admin, "tax_invoice", subject="x", body="Dear {name")
    with pytest.raises(EmailError, match="not a placeholder"):
        document_email.update_template(admin, "tax_invoice", subject="{amount!r}", body="x")
    with pytest.raises(EmailError, match="one line"):
        document_email.update_template(admin, "tax_invoice", subject="a\nBcc: x@y.z", body="x")
    preview = as_user(admin).post(f"{url}preview/", body, format="json").json()
    assert preview["subject"] == "Invoice [Invoice number]"


def test_the_draft_is_filled_in_for_the_person_sending(accountant, finance):
    draft = document_email.draft(
        accountant,
        "tax_invoice",
        {
            "recipient_name": "Lanka Plastics (Pvt) Ltd",
            "document_number": "26SEP_W1_35",
            "document_date": "09/30/2026",
            "due_date": "10/30/2026",
            "amount": "139,487.43",
            "currency": "LKR",
        },
        to=["accounts@lankaplastics.lk"],
    )
    assert draft["subject"].startswith("Tax invoice 26SEP_W1_35 from ")
    assert "Dear Lanka Plastics (Pvt) Ltd" in draft["body"]
    assert "LKR 139,487.43, due on 10/30/2026" in draft["body"]
    assert accountant.full_name in draft["body"]
    assert draft["to"] == ["accounts@lankaplastics.lk"] and draft["ready"] is True


# --- Sending ----------------------------------------------------------------------------


def test_the_edited_message_is_what_is_sent_and_recorded(accountant, finance):
    pdf = b"%PDF-1.7 invoice"
    record = document_email.send(
        accountant,
        kind="tax_invoice",
        label="Tax invoice 26SEP_W1_35",
        document_id=35,
        to="accounts@lankaplastics.lk; buyer@lankaplastics.lk",
        cc=["owner@sml.lk"],
        subject="Tax invoice 26SEP_W1_35 (corrected address)",
        body="Dear Sir,\n\nAs discussed, the corrected invoice is attached.",
        attachment=("26SEP_W1_35.pdf", pdf, "application/pdf"),
    )
    assert record.status == "sent"
    [sent] = mail.outbox
    assert sent.to == ["accounts@lankaplastics.lk", "buyer@lankaplastics.lk"]
    assert sent.cc == ["owner@sml.lk"] and sent.bcc == ["finance@smlengineers.lk"]
    assert sent.reply_to == ["accounts@smlengineers.lk"]
    assert sent.subject == "Tax invoice 26SEP_W1_35 (corrected address)"
    assert sent.body.startswith("Dear Sir,")
    assert sent.attachments[0][0] == "26SEP_W1_35.pdf"
    record.refresh_from_db()
    assert record.body == sent.body and record.subject == sent.subject
    assert record.attachment_sha256 == hashlib.sha256(pdf).hexdigest()
    assert record.attachment.read() == pdf
    assert [r.pk for r in document_email.sent_for("tax_invoice", 35)] == [record.pk]


def test_sending_needs_a_set_up_account(accountant):
    with pytest.raises(EmailError, match="not set up yet"):
        document_email.send(
            accountant,
            kind="report",
            label="Outstanding report",
            to="a@b.lk",
            subject="x",
            body="y",
        )


@pytest.mark.parametrize(
    "to, subject, why",
    [
        ("", "Statement", "at least one recipient"),
        ("not-an-address", "Statement", "not a valid email"),
        (",".join(f"c{i}@b.lk" for i in range(21)), "Statement", "at most 20"),
        ("a@b.lk", "Line one\nBcc: spy@x.lk", "one line"),
    ],
)
def test_sending_is_refused_when_the_email_is_not_valid(accountant, finance, to, subject, why):
    with pytest.raises(EmailError, match=why):
        document_email.send(
            accountant,
            kind="customer_statement",
            label="Statement",
            to=to,
            subject=subject,
            body="Hello",
        )
    assert not SentEmail.objects.exists()


def test_a_failed_send_is_recorded_with_the_error(accountant, finance, monkeypatch):
    def refuse(self, *args, **kwargs):
        raise OSError("421 service not available")

    monkeypatch.setattr(EmailMessage, "send", refuse)
    record = document_email.send(
        accountant,
        kind="report",
        label="Aging report",
        to="owner@sml.lk",
        subject="Aging",
        body="Attached.",
    )
    assert record.status == "failed" and "421 service not available" in record.error
    assert SentEmail.objects.get().status == "failed"


def test_the_sent_email_record_cannot_be_changed_or_deleted(accountant, finance):
    document_email.send(
        accountant,
        kind="report",
        label="Aging report",
        to="owner@sml.lk",
        subject="Aging",
        body="Attached.",
    )
    row = SentEmail.objects.get()
    with pytest.raises(DatabaseError), transaction.atomic():
        SentEmail.objects.filter(pk=row.pk).update(body="something else")
    with pytest.raises(DatabaseError), transaction.atomic():
        SentEmail.objects.filter(pk=row.pk).delete()


def test_the_sent_emails_are_visible_to_the_admin_and_auditor_only(accountant, finance):
    document_email.send(
        accountant,
        kind="report",
        label="Aging report",
        to="owner@sml.lk",
        subject="Aging",
        body="Attached.",
    )
    auditor = person("auditor@sml.lk", "auditor", all_divisions=True)
    rows = as_user(auditor).get("/api/v1/sent-emails/?document_type=report").json()
    assert rows[0]["to"] == "owner@sml.lk" and rows[0]["status"] == "sent"
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).get("/api/v1/sent-emails/").status_code == 403
