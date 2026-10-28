"""Company profile and divisions (backlog P0-07, spec 3 and 3.1).

Divisions are plain data: one added here is usable immediately in every picker, filter,
report and number series, with no restart or code change. Once a division has been used on
a document its code is fixed and it can only be deactivated, never deleted (rule 9); the
database enforces the same (migration 0007).
"""

import re

from django.db import transaction
from django.utils import timezone

from .audit import audit_context, audited, record
from .models import Company, Division, User

CODE_PATTERN = re.compile(r"^[A-Z0-9]{2}$")
LOGO_MAX_BYTES = 1024 * 1024
# PNG and JPEG only: no SVG, which can carry scripts.
LOGO_SIGNATURES = {b"\x89PNG\r\n\x1a\n": "png", b"\xff\xd8\xff": "jpg"}

COMPANY_FIELDS = (
    "name",
    "registration_no",
    "tin",
    "vat_no",
    "address",
    "phone",
    "email",
    "website",
    "financial_year_start_month",
)


class OrganisationError(Exception):
    pass


# --- Company ----------------------------------------------------------------------------


@audited("company_updated", reason_arg="reason")
@transaction.atomic
def update_company(data: dict, reason: str = "") -> Company:
    company = Company.objects.select_for_update().get(pk=1)
    if "base_currency" in data and data["base_currency"] != company.base_currency:
        raise OrganisationError("The base currency cannot be changed.")
    for field in COMPANY_FIELDS:
        if field in data:
            setattr(company, field, data[field])
    company.name = (company.name or "").strip()
    if not company.name:
        raise OrganisationError("The company name is required.")
    company.save()
    return company


def _logo_extension(content: bytes) -> str:
    for signature, extension in LOGO_SIGNATURES.items():
        if content.startswith(signature):
            return extension
    raise OrganisationError("The logo must be a PNG or JPEG image.")


@audited("company_logo_changed")
@transaction.atomic
def set_company_logo(uploaded) -> Company:
    if uploaded.size > LOGO_MAX_BYTES:
        raise OrganisationError("The logo must be 1 MB or smaller.")
    content = uploaded.read()
    extension = _logo_extension(content)
    company = Company.objects.select_for_update().get(pk=1)
    uploaded.seek(0)
    company.logo.save(f"logo.{extension}", uploaded, save=False)
    company.save()
    return company


@audited("company_logo_removed")
@transaction.atomic
def remove_company_logo() -> Company:
    company = Company.objects.select_for_update().get(pk=1)
    company.logo = ""
    company.save()
    return company


# --- Divisions --------------------------------------------------------------------------


def normalise_code(code: str) -> str:
    code = (code or "").strip().upper()
    if not CODE_PATTERN.match(code):
        raise OrganisationError(
            "The division code must be exactly two letters or digits, for example WS."
        )
    return code


def _document_relations():
    """Reverse relations that mean a document or record uses the division.

    Which users may work in a division is access, not a document, so it does not lock the
    code.
    """
    return [rel for rel in _relations() if not (rel.related_model is User and rel.many_to_many)]


def _relations():
    return [rel for rel in Division._meta.related_objects if rel.get_accessor_name()]


def linked_record_counts(division: Division) -> dict[str, int]:
    """How many records of each kind point at this division (users included)."""
    counts = {}
    for rel in _relations():
        accessor = rel.get_accessor_name()
        count = getattr(division, accessor).count()
        if count:
            counts[str(rel.related_model._meta.verbose_name_plural)] = count
    return counts


def is_in_use(division: Division) -> bool:
    """True once any document has used the division: its code is then fixed."""
    if division.first_used_at is not None:
        return True
    return any(getattr(division, rel.get_accessor_name()).exists() for rel in _document_relations())


def _check_name(name: str, exclude_pk: int | None = None) -> str:
    name = (name or "").strip()
    if not name:
        raise OrganisationError("The division name is required.")
    clash = Division.objects.filter(name__iexact=name)
    if exclude_pk:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        raise OrganisationError(f"There is already a division called {name}.")
    return name


def _check_type(division_type: str) -> str:
    if division_type not in Division.Type.values:
        raise OrganisationError("The division type must be Production or Shared.")
    return division_type


@audited("division_created", reason_arg="reason")
@transaction.atomic
def create_division(
    *, code: str, name: str, division_type: str = Division.Type.PRODUCTION, reason: str = ""
) -> Division:
    code = normalise_code(code)
    if Division.objects.filter(code=code).exists():
        raise OrganisationError(f"The code {code} is already used by another division.")
    return Division.objects.create(
        code=code, name=_check_name(name), division_type=_check_type(division_type)
    )


@transaction.atomic
def update_division(division: Division, data: dict, reason: str = "") -> Division:
    """Rename, retype, recode (only while unused), deactivate or reactivate a division."""
    division = Division.objects.select_for_update().get(pk=division.pk)
    event = "division_changed"

    if "code" in data:
        code = normalise_code(data["code"])
        if code != division.code:
            if is_in_use(division):
                raise OrganisationError(
                    f"The code {division.code} has been used on documents and cannot change."
                )
            if Division.objects.filter(code=code).exclude(pk=division.pk).exists():
                raise OrganisationError(f"The code {code} is already used by another division.")
            division.code = code
    if "name" in data:
        division.name = _check_name(data["name"], exclude_pk=division.pk)
    if "division_type" in data:
        division.division_type = _check_type(data["division_type"])
    if "is_active" in data and bool(data["is_active"]) != division.is_active:
        if data["is_active"]:
            event = "division_reactivated"
        else:
            if not (reason or "").strip():
                raise OrganisationError("Give a reason for deactivating the division.")
            others = Division.objects.filter(is_active=True).exclude(pk=division.pk)
            if not others.exists():
                raise OrganisationError("At least one division must stay active.")
            event = "division_deactivated"
        division.is_active = bool(data["is_active"])

    with audit_context(event, reason):
        division.save()
    return division


@audited("division_deleted", reason_arg="reason")
@transaction.atomic
def delete_division(division: Division, reason: str) -> None:
    """Delete a division set up by mistake. Anything with history is deactivated instead."""
    if not (reason or "").strip():
        raise OrganisationError("Give a reason for deleting the division.")
    division = Division.objects.select_for_update().get(pk=division.pk)
    if is_in_use(division):
        raise OrganisationError(
            f"{division.code} has been used on documents: it cannot be deleted, only deactivated."
        )
    linked = linked_record_counts(division)
    if linked:
        what = ", ".join(f"{count} {kind}" for kind, count in linked.items())
        raise OrganisationError(
            f"{division.code} is linked to {what}. Remove those links or deactivate it instead."
        )
    if not Division.objects.filter(is_active=True).exclude(pk=division.pk).exists():
        raise OrganisationError("At least one division must stay active.")
    division.delete()


@transaction.atomic
def mark_division_used(division: Division) -> None:
    """Record that a document has used this division (called by the number series, P0-08).

    Idempotent: only the first use is stored. From then on the code is fixed.
    """
    now = timezone.now()
    updated = Division.objects.filter(pk=division.pk, first_used_at__isnull=True).update(
        first_used_at=now
    )
    if updated:
        division.first_used_at = now
        record(
            "update",
            division,
            {"first_used_at": [None, now.isoformat()]},
            event="division_first_used",
        )
