"""The company-wide two-factor switch (owner, 12 Nov 2026).

While it is off, nobody is asked for an authenticator code at sign-in and nobody is held to
set one up; people who already set one up keep it for when the switch goes back on. Only the
Admin (User access: manage) changes it, with a reason, and the change is in the audit log.
It must be on before go-live: payments and payroll rely on it.
"""

from django.db import transaction

from .access import has_access
from .audit import audit_context
from .models import Company, User


class SecurityError(Exception):
    pass


def two_factor_on() -> bool:
    return Company.objects.filter(pk=1).values_list("two_factor_on", flat=True).first() is not False


def set_two_factor(user: User, on: bool, reason: str) -> Company:
    if not has_access(user, "users", "manage"):
        raise SecurityError("Only the Admin can switch two-factor sign-in on or off.")
    reason = (reason or "").strip()[:200]
    if not reason:
        raise SecurityError("Give the reason for the change.")
    company = Company.get()
    if company.two_factor_on == on:
        return company
    event = "two_factor_switched_on" if on else "two_factor_switched_off"
    with audit_context(event, reason), transaction.atomic():
        company.two_factor_on = on
        company.save(update_fields=["two_factor_on"])
    return company
