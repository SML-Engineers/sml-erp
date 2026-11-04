"""Sending documents and reports by email (spec 3B, backlog P0-19).

The Admin sets the sending mailbox (e.g. finance@domain.com) and a default subject and
message for each kind of document. A document module offers an Email button: it calls
`draft()` for the filled-in message, lets the person edit it, and calls `send()` with the
final text and the PDF. Every email sent or attempted is recorded exactly as sent, for good.

The mailbox password is stored encrypted (FIELD_ENCRYPTION_KEY, never in the repository) and
never leaves the server. System notifications use their own account (settings.EMAIL_*).
"""

import hashlib
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.mail import EmailMessage, get_connection
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from . import crypto
from .access import has_access
from .audit import audit_context
from .email_catalogue import KINDS, allowed
from .models import Company, EmailTemplate, MailAccount, SentEmail, User

MAX_RECIPIENTS = 20
MAX_BODY = 20000
MAX_ATTACHMENT = 15 * 1024 * 1024
TIMEOUT_SECONDS = 20


class EmailError(Exception):
    pass


def _admin(user: User) -> None:
    if not has_access(user, "settings", "manage"):
        raise EmailError("Only the Admin can change the document email settings.")


def _kind(kind: str) -> tuple[str, dict]:
    if kind not in KINDS:
        raise EmailError(f"Unknown kind of document {kind!r}.")
    return KINDS[kind]


def _address(value: str, what: str) -> str:
    value = (value or "").strip()
    if value:
        try:
            validate_email(value)
        except ValidationError:
            raise EmailError(f"The {what} {value} is not a valid email address.") from None
    return value


# --- The sending account ----------------------------------------------------------------


def account_view() -> dict:
    account = MailAccount.get()
    return {
        "from_name": account.from_name,
        "from_address": account.from_address,
        "reply_to": account.reply_to,
        "copy_to": account.copy_to,
        "host": account.host,
        "port": account.port,
        "security": account.security,
        "username": account.username,
        "has_password": bool(account.password_encrypted),
        "is_ready": account.is_ready,
        "last_test_at": account.last_test_at,
        "last_test_ok": account.last_test_ok,
        "last_test_error": account.last_test_error,
    }


def update_account(user: User, values: dict, reason: str = "") -> dict:
    """Change the sending mailbox. `password` replaces the stored one when given; it is
    never returned. `clear_password` removes it."""
    _admin(user)
    with audit_context("mail_account_changed", reason), transaction.atomic():
        account = MailAccount.objects.select_for_update().get_or_create(pk=1)[0]
        for field in ("from_address", "reply_to", "copy_to"):
            if field in values:
                setattr(account, field, _address(values[field], field.replace("_", " ")))
        if "from_name" in values:
            account.from_name = " ".join((values["from_name"] or "").split())[:100]
        if "host" in values:
            host = (values["host"] or "").strip()
            if host and (" " in host or "/" in host):
                raise EmailError("The mail server must be a host name, e.g. smtp.hostinger.com.")
            account.host = host
        if "port" in values:
            try:
                port = int(values["port"])
            except (TypeError, ValueError):
                raise EmailError("The port must be a number.") from None
            if not 1 <= port <= 65535:
                raise EmailError("The port must be between 1 and 65535.")
            account.port = port
        if "security" in values:
            if values["security"] not in MailAccount.Security.values:
                raise EmailError("Choose the connection security.")
            account.security = values["security"]
        if "username" in values:
            account.username = (values["username"] or "").strip()
        if values.get("password"):
            account.password_encrypted = crypto.encrypt(values["password"])
        elif values.get("clear_password"):
            account.password_encrypted = ""
        if account.host and not account.from_address:
            raise EmailError("Enter the address documents are sent from.")
        account.last_test_ok = None  # the settings changed: test again
        account.save()
    return account_view()


def _connection(account: MailAccount):
    """A connection to the mailbox's server. The backend class is the one configured for
    the system (SMTP on the servers; in tests, an in-memory outbox)."""
    password = crypto.decrypt(account.password_encrypted) if account.password_encrypted else ""
    return get_connection(
        backend=settings.EMAIL_BACKEND,
        host=account.host,
        port=account.port,
        username=account.username,
        password=password,
        use_tls=account.security == MailAccount.Security.STARTTLS,
        use_ssl=account.security == MailAccount.Security.SSL,
        timeout=TIMEOUT_SECONDS,
    )


def _sender(account: MailAccount) -> str:
    if account.from_name:
        return f'"{account.from_name}" <{account.from_address}>'
    return account.from_address


def _safe_error(error: Exception) -> str:
    """The server's answer, without anything that could hold the password."""
    text = f"{type(error).__name__}: {error}"
    return text.replace("\n", " ")[:500]


def send_test(user: User, to: str) -> dict:
    """Send a short test email and remember whether it worked."""
    _admin(user)
    to = _address(to, "test address")
    if not to:
        raise EmailError("Enter the address to send the test email to.")
    account = MailAccount.get()
    if not account.is_ready:
        raise EmailError("Enter the sending address and the mail server first.")
    message = EmailMessage(
        subject="SML ERP: test email",
        body=(
            "This is a test email from SML ERP. If you can read it, documents and reports "
            f"can be emailed from {account.from_address}."
        ),
        from_email=_sender(account),
        to=[to],
        connection=_connection(account),
    )
    try:
        message.send()
        ok, error = True, ""
    except Exception as exc:  # noqa: BLE001 - any failure is reported to the Admin
        ok, error = False, _safe_error(exc)
    MailAccount.objects.filter(pk=1).update(
        last_test_at=timezone.now(), last_test_ok=ok, last_test_error=error
    )
    return {**account_view(), "test_ok": ok, "test_error": error}


# --- Default messages -------------------------------------------------------------------


def _check_placeholders(kind: str, text: str, what: str) -> None:
    names = allowed(kind)
    try:
        parsed = list(string.Formatter().parse(text))
    except ValueError:
        raise EmailError(
            f"The {what} has an unmatched {{ or }}. Placeholders look like {{customer_name}}."
        ) from None
    for _literal, field, spec, conversion in parsed:
        if field is None:
            continue
        if field not in names or spec or conversion:
            raise EmailError(
                f"The {what} uses {{{field}}}, which is not a placeholder for this kind of "
                f"document. Allowed: {', '.join('{' + n + '}' for n in names)}."
            )


def templates() -> list[dict]:
    stored = {t.document_type: t for t in EmailTemplate.objects.all()}
    rows = []
    for kind, (label, _) in KINDS.items():
        template = stored.get(kind)
        rows.append(
            {
                "kind": kind,
                "label": label,
                "subject": template.subject if template else "",
                "body": template.body if template else "",
                "placeholders": [
                    {"name": name, "label": text} for name, text in allowed(kind).items()
                ],
                "updated_at": template.updated_at if template else None,
            }
        )
    return rows


def update_template(user: User, kind: str, *, subject: str, body: str, reason: str = ""):
    _admin(user)
    _kind(kind)
    subject = (subject or "").strip()
    body = (body or "").strip()
    if not subject or "\n" in subject or "\r" in subject:
        raise EmailError("The subject is required and must be on one line.")
    if len(subject) > 200:
        raise EmailError("The subject can have at most 200 characters.")
    if not body:
        raise EmailError("The message is required.")
    if len(body) > MAX_BODY:
        raise EmailError(f"The message can have at most {MAX_BODY} characters.")
    _check_placeholders(kind, subject, "subject")
    _check_placeholders(kind, body, "message")
    with audit_context("email_template_changed", reason):
        template, _ = EmailTemplate.objects.update_or_create(
            document_type=kind,
            defaults={"subject": subject, "body": body, "updated_by": user},
        )
    return template


class _Values(dict):
    def __missing__(self, key):
        return ""


def fill(kind: str, text: str, values: dict) -> str:
    return text.format_map(_Values({k: "" if v is None else str(v) for k, v in values.items()}))


def _common(user: User) -> dict:
    company = Company.get()
    return {
        "company_name": company.name,
        "company_phone": company.phone,
        "company_email": company.email,
        "sender_name": user.full_name,
    }


def draft(user: User, kind: str, values: dict, *, to=(), cc=()) -> dict:
    """The default message for this document, filled in, for the person to edit."""
    _kind(kind)
    template = EmailTemplate.objects.filter(document_type=kind).first()
    if template is None:
        raise EmailError("There is no default message for this kind of document yet.")
    context = {**_common(user), **values}
    account = MailAccount.get()
    return {
        "from": _sender(account) if account.is_ready else "",
        "ready": account.is_ready,
        "to": [a for a in to if a],
        "cc": [a for a in cc if a],
        "subject": fill(kind, template.subject, context),
        "body": fill(kind, template.body, context),
    }


def preview(kind: str, subject: str, body: str) -> dict:
    """A template with each placeholder shown as [what it stands for]."""
    _kind(kind)
    _check_placeholders(kind, subject or "", "subject")
    _check_placeholders(kind, body or "", "message")
    sample = {name: f"[{label}]" for name, label in allowed(kind).items()}
    return {"subject": fill(kind, subject or "", sample), "body": fill(kind, body or "", sample)}


# --- Sending ----------------------------------------------------------------------------


def _addresses(values, what: str) -> list[str]:
    if isinstance(values, str):
        values = values.replace(";", ",").split(",")
    result = []
    for value in values or []:
        address = _address(value, what)
        if address and address.lower() not in {a.lower() for a in result}:
            result.append(address)
    return result


def send(
    user: User,
    *,
    kind: str,
    label: str,
    to,
    subject: str,
    body: str,
    cc=(),
    document_id: int | None = None,
    attachment: tuple[str, bytes, str] | None = None,
    others: list[tuple[str, bytes, str]] | tuple = (),
) -> SentEmail:
    """Send the email exactly as given and record it. A failure is recorded too, and the
    record returned has status "failed" with the server's answer. The caller checks that
    the user may send this document."""
    _kind(kind)
    account = MailAccount.get()
    if not account.is_ready:
        raise EmailError(
            "Document email is not set up yet. Ask the Admin to enter the sending mailbox "
            "under Settings → Document email."
        )
    to, cc = _addresses(to, "recipient"), _addresses(cc, "copy address")
    if not to:
        raise EmailError("Enter at least one recipient.")
    if len(to) + len(cc) > MAX_RECIPIENTS:
        raise EmailError(f"An email can go to at most {MAX_RECIPIENTS} addresses.")
    subject = (subject or "").strip()
    if not subject or "\n" in subject or "\r" in subject or len(subject) > 200:
        raise EmailError("The subject is required, on one line, at most 200 characters.")
    body = (body or "").strip()
    if not body or len(body) > MAX_BODY:
        raise EmailError(f"The message is required and can have at most {MAX_BODY} characters.")
    bcc = [account.copy_to] if account.copy_to else []

    message = EmailMessage(
        subject=subject,
        body=body,
        from_email=_sender(account),
        to=to,
        cc=cc,
        bcc=bcc,
        reply_to=[account.reply_to] if account.reply_to else None,
        connection=_connection(account),
    )
    record = SentEmail(
        document_type=kind,
        document_id=document_id,
        document_label=(label or KINDS[kind][0])[:200],
        from_address=_sender(account)[:300],
        to=", ".join(to),
        cc=", ".join(cc),
        bcc=", ".join(bcc),
        subject=subject,
        body=body,
        sent_by=user,
    )
    if attachment is not None:
        name, content, mimetype = attachment
        if len(content) > MAX_ATTACHMENT:
            raise EmailError("The attachment is larger than 15 MB.")
        message.attach(name, content, mimetype)
        record.attachment_name = name[:200]
        record.attachment_sha256 = hashlib.sha256(content).hexdigest()
        record.attachment = ContentFile(content, name=name)
    if others:
        total = sum(len(c) for _, c, _ in ([attachment] if attachment else []) + list(others))
        if total > MAX_ATTACHMENT:
            raise EmailError("The attachments together are larger than 15 MB.")
        listed = []
        for name, content, mimetype in others:
            message.attach(name, content, mimetype)
            listed.append(f"{name[:200]} {hashlib.sha256(content).hexdigest()}")
        record.other_attachments = "\n".join(listed)
    try:
        message.send()
        record.status = SentEmail.Status.SENT
    except Exception as exc:  # noqa: BLE001 - recorded and reported to the person sending
        record.status = SentEmail.Status.FAILED
        record.error = _safe_error(exc)
    record.save()
    return record


def sent_for(kind: str, document_id: int):
    return SentEmail.objects.filter(document_type=kind, document_id=document_id).select_related(
        "sent_by"
    )
