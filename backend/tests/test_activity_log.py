"""The activity log level (owner, 14 Nov 2026): changes and sign-ins only / sensitive (the
default: payslips, salaries and bank details opened, and every download) / everything. The
Admin changes it with a reason; the record of views and downloads is insert-only."""

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.http import HttpResponse
from django.test import RequestFactory

from apps.core import activity
from apps.core.models import ActivityEvent, AuditEvent, Company

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

URL = "/api/v1/access/sign-in-security/"
LOG = "/api/v1/activity-log/"


@pytest.fixture
def admin():
    return person("admin3@sml.lk", "system_admin", all_divisions=True)


@pytest.fixture
def director():
    return person("dir3@sml.lk", "director", all_divisions=True)


def level(value):
    Company.objects.filter(pk=1).update(activity_log_level=value)


def note(user, path, download=False, status=200, method="get"):
    """Run the recording rule on one request, as the middleware does after the page answered."""
    request = getattr(RequestFactory(), method)(path)
    request.user = user
    response = HttpResponse(status=status)
    if download:
        response["Content-Disposition"] = 'attachment; filename="customers.xlsx"'
    return activity.note(request, response)


# --- The setting ------------------------------------------------------------------------


def test_sensitive_is_the_default():
    assert Company.get().activity_log_level == "sensitive"


def test_only_the_admin_changes_the_level_with_a_reason(admin, director):
    assert as_user(director).get(URL).json() == {
        "two_factor_on": True,
        "activity_log_level": "sensitive",
    }
    refused = as_user(director).put(
        URL, {"activity_log_level": "everything", "reason": "x"}, format="json"
    )
    assert refused.status_code == 403
    no_reason = as_user(admin).put(URL, {"activity_log_level": "everything"}, format="json")
    assert no_reason.status_code == 400 and "reason" in no_reason.json()["detail"]
    wrong = as_user(admin).put(
        URL, {"activity_log_level": "some", "reason": "testing"}, format="json"
    )
    assert wrong.status_code == 400 and Company.get().activity_log_level == "sensitive"

    changed = as_user(admin).put(
        URL, {"activity_log_level": "everything", "reason": "Audit month"}, format="json"
    )
    assert changed.status_code == 200
    assert changed.json() == {"two_factor_on": True, "activity_log_level": "everything"}
    event = AuditEvent.objects.filter(event="activity_log_level_changed").latest("id")
    assert event.reason == "Audit month" and event.actor_email == admin.email
    assert event.changes["activity_log_level"] == ["sensitive", "everything"]
    # The two-factor switch on the same page still works on its own.
    off = as_user(admin).put(URL, {"two_factor_on": False, "reason": "testing"}, format="json")
    assert off.json() == {"two_factor_on": False, "activity_log_level": "everything"}


# --- What is recorded at each level -----------------------------------------------------


@pytest.mark.parametrize(
    ("address", "category"),
    [
        ("payroll/4/payslips/", "payslip"),
        ("my/payslips/12/", "payslip"),
        ("my/apit-certificate/", "payslip"),
        ("payroll/4/", "salary"),
        ("payroll/", "salary"),
        ("employees/7/pay/", "salary"),
        ("employees/excel/", "salary"),
        ("pay-changes/3/", "salary"),
        ("gratuity/", "salary"),
        ("my/", "salary"),
        ("employees/7/", "bank"),
        ("payees/2/bank-accounts/", "bank"),
        ("company-accounts/", "bank"),
        ("bank-statements/5/", "bank"),
        ("reconciliation/", "bank"),
        ("my/details/", "bank"),
        ("employees/7/leave/", "other"),
        ("payroll-tax-tables/", "other"),
        ("customers/", "other"),
    ],
)
def test_what_counts_as_sensitive(address, category):
    assert activity.category_of(address) == category


def test_at_sensitive_payslips_salaries_bank_and_every_download(director):
    level("sensitive")
    seen = note(director, "/api/v1/employees/7/")
    assert (seen.kind, seen.category, seen.user_email, seen.level) == (
        "view",
        "bank",
        director.email,
        "sensitive",
    )
    assert note(director, "/api/v1/customers/") is None  # an ordinary page is not recorded
    download = note(director, "/api/v1/customers/export/", download=True)
    assert (download.kind, download.category, download.file_name) == (
        "download",
        "other",
        "customers.xlsx",
    )


def test_at_changes_only_nothing_more_is_recorded(director):
    level("changes")
    assert note(director, "/api/v1/my/payslips/3/", download=True) is None
    assert note(director, "/api/v1/employees/7/") is None


def test_at_everything_every_page_but_not_the_screens_own_checks(director):
    level("everything")
    assert note(director, "/api/v1/customers/?search=abc").path == "/api/v1/customers/?search=abc"
    for quiet in ("auth/me/", "notifications/", "approvals/waiting/", "activity-log/"):
        assert note(director, f"/api/v1/{quiet}") is None


def test_changes_failures_and_strangers_are_not_views(director):
    from django.contrib.auth.models import AnonymousUser

    level("everything")
    assert note(director, "/api/v1/employees/7/", method="post") is None  # in the audit log
    assert note(director, "/api/v1/employees/7/", status=403) is None
    assert note(AnonymousUser(), "/api/v1/employees/7/") is None
    assert note(director, "/admin/") is None


def test_through_a_real_request():
    level("everything")
    clerk = person("clerk3@sml.lk", "clerk", divisions=["WS"])
    assert as_user(clerk).get("/api/v1/divisions/").status_code == 200
    row = ActivityEvent.objects.latest("id")
    assert (row.user_email, row.path, row.kind) == (clerk.email, "/api/v1/divisions/", "view")
    level("sensitive")
    before = ActivityEvent.objects.count()
    as_user(clerk).get("/api/v1/divisions/")
    assert ActivityEvent.objects.count() == before


# --- The record ------------------------------------------------------------------------


def test_rows_cannot_be_changed_or_deleted(director):
    row = note(director, "/api/v1/employees/7/")
    with pytest.raises(DatabaseError), transaction.atomic():
        ActivityEvent.objects.filter(pk=row.pk).update(path="tampered")
    with pytest.raises(DatabaseError), transaction.atomic():
        ActivityEvent.objects.filter(pk=row.pk).delete()


def test_reading_the_record(director):
    level("sensitive")
    note(director, "/api/v1/employees/7/")
    note(director, "/api/v1/customers/export/", download=True)
    other = person("hr3@sml.lk", "clerk", divisions=["WS"])
    note(other, "/api/v1/my/payslips/3/")
    rows = as_user(director).get(LOG).json()
    assert [r["category"] for r in rows] == ["payslip", "other", "bank"]
    mine = as_user(director).get(LOG, {"person": director.email, "kind": "download"}).json()
    assert [r["file_name"] for r in mine] == ["customers.xlsx"]
    assert as_user(director).get(LOG, {"from": "16-11-2026"}).status_code == 400
    assert as_user(person("clerk4@sml.lk", "clerk")).get(LOG).status_code == 403
    # Read only: there is no way to change it through the API.
    assert as_user(director).delete(LOG).status_code in (403, 405)
    assert as_user(director).post(LOG, {}).status_code in (403, 405)
