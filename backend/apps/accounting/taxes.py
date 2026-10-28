"""Taxes, as QuickBooks keeps them (backlog P0-20, spec 3 and 6.1).

- A **tax component** is one tax (VAT, SSCL, WHT…) with its dated rates and the accounts it
  is recorded in. The Accountant adds components and rates; a rate applies from its date
  (rule 11) and documents keep the rate and amount they were given.
- A **tax code** is what is chosen on a document line ("VAT 18% + SSCL", "Exempt"): the
  components it applies, in order, each on the net amount or on the net amount plus the
  taxes above it. The tax invoice's SSCL-then-VAT rule (spec 6.1) is such a code.
- `calculate()` gives each tax rounded half-up to the cent.

Once a document uses a component or a code, its code is fixed and it cannot be deleted; a
used code's make-up is fixed (a new code is made instead) and a used component's rates in
force cannot change (a new rate is added). The database enforces this (migration 0004).
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context, record
from apps.core.models import User

from .catalogue import section_of
from .models import TAX_CODE_REGEX, Account, TaxCode, TaxCodeLine, TaxComponent, TaxRate
from .services import AccountingError

CENT = Decimal("0.01")
CODE = re.compile(TAX_CODE_REGEX)


def _manage(user: User) -> None:
    if not effective_access(user).has("accounting", "manage"):
        raise AccountingError("Only the Accountant can change taxes.")


def _code(value, what: str) -> str:
    code = (value or "").strip().upper()
    if not CODE.match(code):
        raise AccountingError(
            f"The {what} code must be 1 to 20 letters, digits or dashes, e.g. VAT-SSCL."
        )
    return code


def _name(value, what: str) -> str:
    name = " ".join((value or "").split())
    if not name:
        raise AccountingError(f"The {what} name is required.")
    return name[:100]


def _account(value, what: str, balance_sheet: bool) -> Account | None:
    if value in (None, ""):
        return None
    account = value if isinstance(value, Account) else Account.objects.filter(pk=value).first()
    if account is None or not account.is_active or account.merged_into_id:
        raise AccountingError(f"The {what} must be an active account.")
    if balance_sheet and section_of(account.account_type) == "profit_and_loss":
        raise AccountingError(f"The {what} must be a balance sheet account (e.g. VAT payable).")
    return account


def is_used(obj) -> bool:
    return obj.first_used_at is not None


@transaction.atomic
def mark_used(obj) -> None:
    """Record that a document used this component or code (called by document modules)."""
    now = timezone.now()
    if type(obj).objects.filter(pk=obj.pk, first_used_at__isnull=True).update(first_used_at=now):
        obj.first_used_at = now
        record("update", obj, {"first_used_at": [None, now.isoformat()]}, event="first_used")


# --- Components and rates ---------------------------------------------------------------


def save_component(user: User, component: TaxComponent | None, values: dict, reason=""):
    _manage(user)
    with audit_context("tax_component_saved", reason), transaction.atomic():
        if component is None:
            component = TaxComponent()
        else:
            component = TaxComponent.objects.select_for_update().get(pk=component.pk)
        if "code" in values or component.pk is None:
            code = _code(values.get("code", component.code), "tax")
            if code != component.code:
                if component.pk and is_used(component):
                    raise AccountingError(
                        f"{component.code} has been used; its code cannot change."
                    )
                if TaxComponent.objects.filter(code=code).exclude(pk=component.pk).exists():
                    raise AccountingError(f"There is already a tax {code}.")
                component.code = code
        if "name" in values or component.pk is None:
            component.name = _name(values.get("name"), "tax")
        if "kind" in values:
            if values["kind"] not in TaxComponent.Kind.values:
                raise AccountingError("Choose whether the tax is charged or withheld.")
            if component.pk and is_used(component) and values["kind"] != component.kind:
                raise AccountingError(f"{component.code} has been used; its kind cannot change.")
            component.kind = values["kind"]
        if "sales_account" in values:
            component.sales_account = _account(values["sales_account"], "sales account", True)
        if "purchase_account" in values:
            component.purchase_account = _account(
                values["purchase_account"], "purchase account", False
            )
        if "is_active" in values:
            component.is_active = bool(values["is_active"])
        component.save()
        return component


def _percent(value) -> Decimal:
    if isinstance(value, float):
        raise AccountingError("The rate must be an exact decimal, not floating point.")
    try:
        rate = Decimal(str(value).strip().rstrip("%"))
    except (InvalidOperation, AttributeError):
        raise AccountingError("The rate must be a percentage, e.g. 18 or 2.125.") from None
    if not rate.is_finite() or rate < 0 or rate > 100:
        raise AccountingError("The rate must be between 0 and 100 percent.")
    if rate != rate.quantize(Decimal("0.0001")):
        raise AccountingError("The rate can have at most four decimals.")
    return rate


def add_rate(user: User, component: TaxComponent, *, effective_from: date, rate, reason=""):
    """A new rate from a date. Once the tax has been used on a document, a new rate can
    only start today or later; before that, any date can be entered (setting up)."""
    _manage(user)
    rate = _percent(rate)
    today = timezone.localdate()
    with audit_context("tax_rate_added", reason), transaction.atomic():
        component = TaxComponent.objects.select_for_update().get(pk=component.pk)
        if is_used(component) and effective_from < today:
            raise AccountingError(
                f"{component.code} has been used on documents, so a new rate cannot start "
                "before today."
            )
        if TaxRate.objects.filter(component=component, effective_from=effective_from).exists():
            raise AccountingError(f"{component.code} already has a rate from {effective_from}.")
        return TaxRate.objects.create(
            component=component, effective_from=effective_from, rate=rate, created_by=user
        )


def remove_rate(user: User, rate: TaxRate, reason: str) -> None:
    _manage(user)
    if not (reason or "").strip():
        raise AccountingError("Give a reason for removing the rate.")
    in_force = rate.effective_from <= timezone.localdate()
    if in_force and is_used(rate.component):
        raise AccountingError(
            "This rate is in force on a tax already used on documents; add a new rate instead."
        )
    with audit_context("tax_rate_removed", reason):
        rate.delete()


def rate_on(component: TaxComponent, on_date: date) -> TaxRate:
    found = component.rates.filter(effective_from__lte=on_date).order_by("-effective_from").first()
    if found is None:
        raise AccountingError(
            f"{component.code} has no rate on {on_date}. The Accountant enters it under "
            "Accounts → Taxes."
        )
    return found


# --- Tax codes --------------------------------------------------------------------------


def save_code(user: User, tax_code: TaxCode | None, values: dict, reason="") -> TaxCode:
    """`values["components"]`: [{"component": id, "base": "net" | "net_and_tax"}], in order."""
    _manage(user)
    with audit_context("tax_code_saved", reason), transaction.atomic():
        if tax_code is None:
            tax_code = TaxCode()
        else:
            tax_code = TaxCode.objects.select_for_update().get(pk=tax_code.pk)
        used = tax_code.pk is not None and is_used(tax_code)
        if "code" in values or tax_code.pk is None:
            code = _code(values.get("code", tax_code.code), "tax")
            if code != tax_code.code:
                if used:
                    raise AccountingError(f"{tax_code.code} has been used; its code cannot change.")
                if TaxCode.objects.filter(code=code).exclude(pk=tax_code.pk).exists():
                    raise AccountingError(f"There is already a tax code {code}.")
                tax_code.code = code
        if "name" in values or tax_code.pk is None:
            tax_code.name = _name(values.get("name"), "tax code")
        if "description" in values:
            tax_code.description = (values["description"] or "").strip()[:300]
        if "use" in values:
            if values["use"] not in TaxCode.Use.values:
                raise AccountingError("Choose where the tax code is used.")
            tax_code.use = values["use"]
        if "is_active" in values:
            tax_code.is_active = bool(values["is_active"])
        tax_code.save()
        if "components" in values:
            _set_components(tax_code, values["components"], used)
        return tax_code


def _set_components(tax_code: TaxCode, parts, used: bool) -> None:
    wanted = []
    for index, part in enumerate(parts or [], start=1):
        component = TaxComponent.objects.filter(pk=part.get("component")).first()
        if component is None:
            raise AccountingError(f"Line {index}: unknown tax.")
        if component.kind != TaxComponent.Kind.CHARGED:
            raise AccountingError(
                f"{component.code} is withheld from payments; it is applied when paying, not "
                "in a tax code."
            )
        base = part.get("base") or TaxCodeLine.Base.NET
        if base not in TaxCodeLine.Base.values:
            raise AccountingError(f"Line {index}: choose what {component.code} is charged on.")
        if index == 1 and base == TaxCodeLine.Base.NET_AND_TAX:
            base = TaxCodeLine.Base.NET  # nothing above the first tax
        wanted.append((component.pk, base))
    if len({pk for pk, _ in wanted}) != len(wanted):
        raise AccountingError("A tax can appear only once in a tax code.")
    current = list(tax_code.lines.values_list("component_id", "base"))
    if current == wanted:
        return
    if used:
        raise AccountingError(
            f"{tax_code.code} has been used on documents, so its taxes cannot change. "
            "Make a new tax code and switch this one off."
        )
    tax_code.lines.all().delete()
    for sequence, (pk, base) in enumerate(wanted, start=1):
        TaxCodeLine.objects.create(tax_code=tax_code, sequence=sequence, component_id=pk, base=base)
    record("update", tax_code, {"components": [current, wanted]})


def delete_code(user: User, tax_code: TaxCode, reason: str) -> None:
    _manage(user)
    if not (reason or "").strip():
        raise AccountingError("Give a reason for deleting the tax code.")
    if is_used(tax_code):
        raise AccountingError(f"{tax_code.code} has been used; switch it off instead.")
    if tax_code.default_for.exists():
        raise AccountingError(
            f"{tax_code.code} is the default of some accounts; change them first."
        )
    with audit_context("tax_code_deleted", reason), transaction.atomic():
        tax_code.delete()


# --- Calculation ------------------------------------------------------------------------


@dataclass
class TaxLine:
    component: TaxComponent
    rate: Decimal
    base: Decimal
    amount: Decimal


@dataclass
class TaxResult:
    net: Decimal
    lines: list[TaxLine] = field(default_factory=list)

    @property
    def tax(self) -> Decimal:
        return sum((line.amount for line in self.lines), Decimal("0"))

    @property
    def gross(self) -> Decimal:
        return self.net + self.tax


def calculate(tax_code: TaxCode, net, on_date: date) -> TaxResult:
    """The taxes of `tax_code` on a net amount, at the rates in force on `on_date`; each
    rounded half-up to the cent. Example (spec 6.1): 115,750.00 with SSCL 2.125% then VAT
    18% on the amount plus SSCL gives 2,459.69 and 21,277.74, total 139,487.43."""
    if isinstance(net, float):
        raise AccountingError("Amounts must be exact decimals, not floating point.")
    try:
        net = Decimal(str(net)).quantize(CENT, ROUND_HALF_UP)
    except InvalidOperation:
        raise AccountingError("The amount is not a number.") from None
    result = TaxResult(net=net)
    for line in tax_code.lines.select_related("component"):
        rate = rate_on(line.component, on_date).rate
        base = net + (result.tax if line.base == TaxCodeLine.Base.NET_AND_TAX else Decimal("0"))
        amount = (base * rate / Decimal("100")).quantize(CENT, ROUND_HALF_UP)
        result.lines.append(TaxLine(component=line.component, rate=rate, base=base, amount=amount))
    return result
