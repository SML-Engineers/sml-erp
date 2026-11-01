"""Reminders for documents waiting too long for approval (backlog P1-09, spec 4.3)."""

from datetime import timedelta
from unittest import mock

import pytest
from django.db.models import F
from django.utils import timezone

from apps.accounting.models import Account
from apps.core import approvals
from apps.core.models import ApprovalReminder, AuditEvent, Notification
from apps.vouchers import services
from apps.vouchers.services import CodingInput, LineInput

from .test_access import as_user, person
from .test_vouchers import attach, draft, payee, ws

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def voucher(clerk):
    v = draft(clerk, payee(), LineInput(amount="1000.00", invoice_no="INV-1"))
    attach(clerk, v)
    return services.submit(clerk, v)


def waited(days):
    """As if the document had been waiting this many days at its level."""
    return mock.patch.object(
        approvals, "waiting_since", return_value=timezone.now() - timedelta(days=days)
    )


def reminders(user=None):
    rows = Notification.objects.filter(event="approval_reminder")
    return rows.filter(user=user) if user else rows


def test_approvers_are_reminded_once_a_day_after_the_set_days(clerk, accountant, director, voucher):
    with waited(2):
        assert approvals.send_reminders() == 0  # vouchers: after 3 days
    with waited(3):
        assert approvals.send_reminders() == 1
        assert approvals.send_reminders() == 0  # not twice on the same day
    reminder = reminders(accountant).get()
    assert reminder.title.startswith(f"Reminder: Voucher {voucher.number}")
    assert "waited 3 days for your approval (level 2)" in reminder.title
    assert reminder.link == f"/vouchers/{voucher.pk}"
    assert not reminders(clerk).exists() and not reminders(director).exists()
    Notification.objects.update(created_at=F("created_at") - timedelta(days=1))  # next day
    with waited(4):
        assert approvals.send_reminders() == 1
    assert reminders(accountant).count() == 2


def test_the_waiting_starts_again_at_each_level(clerk, accountant, director, voucher):
    services.code_lines(
        accountant,
        voucher,
        [CodingInput(line_no=1, account=Account.objects.get(number="6210"), division=ws())],
    )
    services.approve(accountant, voucher)
    state = approvals.state_of("voucher", voucher.pk)
    last = approvals.history("voucher", voucher.pk).last()
    assert last.action == "approve" and approvals.waiting_since(state) == last.acted_at
    assert approvals.send_reminders() == 0  # waiting 0 days at the Director's level
    with waited(5):
        approvals.send_reminders()
    assert reminders(director).count() == 1 and not reminders(accountant).exists()


def test_no_reminders_when_switched_off_or_when_nothing_waits(clerk, accountant, voucher):
    ApprovalReminder.objects.filter(document_type="voucher").update(enabled=False)
    with waited(10):
        assert approvals.send_reminders() == 0
    ApprovalReminder.objects.filter(document_type="voucher").update(enabled=True)
    services.send_back(accountant, voucher, "Wrong invoice")  # no longer waiting
    with waited(10):
        assert approvals.send_reminders() == 0


def test_the_admin_sets_the_reminders(admin, accountant):
    client = as_user(admin)
    rows = client.get("/api/v1/settings/approval-reminders/").json()
    assert {(r["document_type"], r["enabled"], r["after_days"]) for r in rows} == {
        ("voucher", True, 3),
        ("voucher_cancellation", True, 3),
        ("quotation", True, 3),
        ("customer_advance", True, 3),
        ("sales_order", True, 3),
        ("purchase_order", True, 2),
        ("goods_receipt", True, 1),
        ("goods_receipt_reversal", True, 1),
    }
    changed = client.put(
        "/api/v1/settings/approval-reminders/",
        {"document_type": "voucher", "enabled": True, "after_days": 5, "reason": "Too many"},
        format="json",
    )
    assert changed.status_code == 200
    assert ApprovalReminder.objects.get(document_type="voucher").after_days == 5
    assert AuditEvent.objects.filter(event="approval_reminder_changed").exists()
    too_long = client.put(
        "/api/v1/settings/approval-reminders/",
        {"document_type": "voucher", "enabled": True, "after_days": 90},
        format="json",
    )
    assert too_long.status_code == 400
    refused = as_user(accountant).put(
        "/api/v1/settings/approval-reminders/",
        {"document_type": "voucher", "enabled": False, "after_days": 3},
        format="json",
    )
    assert refused.status_code == 403


def test_each_person_can_turn_reminder_emails_off(accountant):
    events = {
        p["event"] for p in as_user(accountant).get("/api/v1/notifications/preferences/").json()
    }
    assert "approval_reminder" in events
