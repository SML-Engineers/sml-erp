"""The audit log (backlog P0-05).

Every create, change and delete on a registered model is recorded automatically with who did
it, when, from which address, and the old and new values. Services add the business meaning
(an event name and the reason) with `audited(...)` or `audit_context(...)`.

Not recorded: secrets (passwords, authenticator secrets) appear only as "changed"; fields that
change on their own (last sign-in time) are skipped. Bulk queryset updates bypass this, so
services save audited records one by one.
"""

import datetime
import decimal
import functools
import inspect
from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import post_delete, post_save, pre_save

_request: ContextVar = ContextVar("audit_request", default=None)
_context: ContextVar = ContextVar("audit_context", default=None)

HIDDEN = "(hidden)"
CHANGED = "(changed)"

# model -> {"exclude": fields never recorded, "secret": fields recorded only as changed}
_registry: dict = {}


# --- Who and why ------------------------------------------------------------------------


class AuditMiddleware:
    """Makes the current request (and so the signed-in user and address) known to the log."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _request.set(request)
        try:
            return self.get_response(request)
        finally:
            _request.reset(token)


@contextmanager
def audit_context(event: str, reason: str = ""):
    """Label every change made inside this block with what was done and why."""
    token = _context.set({"event": event, "reason": reason or ""})
    try:
        yield
    finally:
        _context.reset(token)


def audited(event: str, reason_arg: str | None = None):
    """Decorator form of audit_context for service functions."""

    def wrap(func):
        signature = inspect.signature(func)

        @functools.wraps(func)
        def inner(*args, **kwargs):
            reason = ""
            if reason_arg:
                bound = signature.bind_partial(*args, **kwargs)
                reason = bound.arguments.get(reason_arg) or ""
            with audit_context(event, str(reason)):
                return func(*args, **kwargs)

        return inner

    return wrap


def _actor():
    request = _request.get()
    user = getattr(request, "user", None) if request is not None else None
    if user is not None and getattr(user, "is_authenticated", False):
        return user
    return None


def _ip():
    request = _request.get()
    if request is None:
        return None
    from .auth_services import client_ip

    return client_ip(request)


# --- Recording --------------------------------------------------------------------------


def _value(instance, field):
    if field.is_relation and field.many_to_one:
        related_id = getattr(instance, field.attname)
        if related_id is None:
            return None
        try:
            return str(getattr(instance, field.name))
        except Exception:  # noqa: BLE001 - deleted or unreachable related row
            return related_id
    value = field.value_from_object(instance)
    if isinstance(value, datetime.datetime | datetime.date | datetime.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, list | dict | str | int | float | bool) or value is None:
        return value
    return str(value)


def _snapshot(instance) -> dict:
    rules = _registry[type(instance)]
    data = {}
    for field in instance._meta.concrete_fields:
        if field.primary_key or field.name in rules["exclude"]:
            continue
        data[field.name] = HIDDEN if field.name in rules["secret"] else _value(instance, field)
    return data


def _related_user_id(instance):
    from .models import User

    if isinstance(instance, User):
        return instance.pk
    return getattr(instance, "user_id", None)


def record(action: str, instance, changes: dict, *, event: str = "", reason: str = ""):
    """Write one audit row. Usually called by the signals; services may call it directly for
    changes the signals cannot see (e.g. many-to-many fields)."""
    from .models import AuditEvent

    context = _context.get() or {}
    actor = _actor()
    AuditEvent.objects.create(
        actor=actor,
        actor_email=actor.email if actor else "system",
        ip_address=_ip(),
        action=action,
        object_type=instance._meta.label_lower,
        object_id=str(instance.pk),
        object_repr=str(instance)[:255],
        related_user_id=_related_user_id(instance),
        event=event or context.get("event", ""),
        reason=reason or context.get("reason", ""),
        changes=changes,
    )


def _pre_save(sender, instance, raw=False, **kwargs):
    if raw:
        return
    old = sender._base_manager.filter(pk=instance.pk).first() if instance.pk else None
    instance._audit_before = _snapshot(old) if old is not None else None
    for name in _registry[sender]["secret"]:
        setattr(instance, f"_audit_secret_{name}", getattr(old, name) if old else None)


def _post_save(sender, instance, created, raw=False, **kwargs):
    if raw:
        return
    after = _snapshot(instance)
    before = getattr(instance, "_audit_before", None)
    if created or before is None:
        record("create", instance, {k: [None, v] for k, v in after.items() if v not in ("", None)})
        return
    changes = {}
    for name, new in after.items():
        old = before.get(name)
        if name in _registry[sender]["secret"]:
            if _secret_changed(sender, instance, name):
                changes[name] = [HIDDEN, CHANGED]
        elif old != new:
            changes[name] = [old, new]
    if changes:
        record("update", instance, changes)


def _secret_changed(sender, instance, name) -> bool:
    return getattr(instance, f"_audit_secret_{name}", None) != getattr(instance, name)


def _post_delete(sender, instance, **kwargs):
    record("delete", instance, {k: [v, None] for k, v in _snapshot(instance).items()})


def register(model, *, exclude=(), secret=()):
    """Record every create, change and delete of `model` in the audit log."""
    _registry[model] = {"exclude": set(exclude), "secret": set(secret)}
    uid = f"audit-{model._meta.label_lower}"
    pre_save.connect(_pre_save, sender=model, dispatch_uid=f"{uid}-pre")
    post_save.connect(_post_save, sender=model, dispatch_uid=f"{uid}-post")
    post_delete.connect(_post_delete, sender=model, dispatch_uid=f"{uid}-delete")


def register_core_models():
    from . import models as m

    register(
        m.User,
        exclude=("last_login", "totp_last_timestep", "password_changed_at", "date_joined"),
        secret=("password", "totp_secret_encrypted"),
    )
    register(m.Company, exclude=("updated_at",))
    register(m.NumberSeries, exclude=("updated_at",))
    register(m.ApprovalRule)
    register(m.ApprovalReminder, exclude=("updated_at",))
    register(
        m.MailAccount,
        exclude=("updated_at", "last_test_at", "last_test_ok", "last_test_error"),
        secret=("password_encrypted",),
    )
    register(m.EmailTemplate, exclude=("updated_at",))
    for model in (
        m.Division,
        m.Role,
        m.RolePermission,
        m.RoleAction,
        m.UserRole,
        m.AccessReview,
        m.AccessOverride,
        m.PasswordReset,
    ):
        register(model)
