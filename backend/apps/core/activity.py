"""The activity log level and the record of views and downloads (owner, 14 Nov 2026).

Changes and sign-ins are always recorded (the audit log and the sign-in history). The level,
set by the Admin with a reason, decides what else is recorded:

- "changes": nothing more;
- "sensitive" (the default): opening payslips, salaries and pay, and bank details, plus every
  download (Excel, PDF, CSV, scans);
- "everything": every page of data opened as well, apart from the background checks the
  screens make on their own (the bell, the signed-in user).

What counts as sensitive is decided here, from the address of the request, so every page and
download is covered in one place. The record is insert-only (migration core 0030).
"""

import logging
import re

from django.db import transaction

from .access import has_access
from .audit import audit_context
from .models import ActivityEvent, Company, User

log = logging.getLogger(__name__)

API = "/api/v1/"
Level = Company.LogLevel
Category = ActivityEvent.Category

# Checked in this order; the first match decides. Addresses are without the /api/v1/ prefix.
SENSITIVE: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^(payroll/\d+/payslips|my/payslips|my/apit-certificate)(/|$)"), Category.PAYSLIP),
    (
        re.compile(
            r"^(payroll|payroll-takeover|payroll-returns|pay-changes|gratuity|staff-credits)/"
            r"|^employees/\d+/pay/|^employees/excel/|^my/$"
        ),
        Category.SALARY,
    ),
    (
        re.compile(
            r"^employees/\d+/$|^payees/\d+/bank-accounts/|^company-accounts/"
            r"|^bank-statements/|^reconciliation/|^my/details/"
        ),
        Category.BANK,
    ),
]

# Requests the screens make on their own, not a person opening something: never recorded.
QUIET = re.compile(
    r"^(auth/|health/|notifications/|approvals/waiting/|activity-log/|access/catalog/)"
)


class LevelError(Exception):
    pass


def current_level() -> str:
    level = Company.objects.filter(pk=1).values_list("activity_log_level", flat=True).first()
    return level or Level.SENSITIVE


def set_level(user: User, level: str, reason: str) -> Company:
    if not has_access(user, "users", "manage"):
        raise LevelError("Only the Admin can change the activity log level.")
    if level not in Level.values:
        raise LevelError("Choose one of the three levels.")
    reason = (reason or "").strip()[:200]
    if not reason:
        raise LevelError("Give the reason for the change.")
    company = Company.get()
    if company.activity_log_level == level:
        return company
    with audit_context("activity_log_level_changed", reason), transaction.atomic():
        company.activity_log_level = level
        company.save(update_fields=["activity_log_level"])
    return company


def category_of(address: str) -> str:
    for pattern, category in SENSITIVE:
        if pattern.search(address):
            return category
    return Category.OTHER


def _file_name(disposition: str) -> str:
    found = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disposition)
    return found.group(1)[:255] if found else ""


def note(request, response) -> ActivityEvent | None:
    """Record this request if the level asks for it. Only successful reads by a signed-in
    person are considered; changes are already in the audit log."""
    if request.method not in ("GET", "HEAD") or response.status_code >= 400:
        return None
    if not request.path.startswith(API):
        return None
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return None
    address = request.path[len(API) :]
    disposition = response.get("Content-Disposition", "")
    kind = ActivityEvent.Kind.DOWNLOAD if disposition else ActivityEvent.Kind.VIEW
    category = category_of(address)
    if kind == ActivityEvent.Kind.VIEW and category == Category.OTHER and QUIET.search(address):
        return None
    level = current_level()
    if level == Level.CHANGES:
        return None
    if level == Level.SENSITIVE and kind == ActivityEvent.Kind.VIEW and category == Category.OTHER:
        return None
    from .auth_services import client_ip

    return ActivityEvent.objects.create(
        user=user,
        user_email=user.email,
        ip_address=client_ip(request),
        kind=kind,
        category=category,
        path=request.get_full_path()[:300],
        file_name=_file_name(disposition),
        level=level,
    )


class ActivityLogMiddleware:
    """Records views and downloads after the page has answered (see `note`). A failure to
    record is written to the server log and never stops the person's page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            note(request, response)
        except Exception:  # noqa: BLE001 - recording must not break the page
            log.exception("Activity log: could not record %s", request.path)
        return response
