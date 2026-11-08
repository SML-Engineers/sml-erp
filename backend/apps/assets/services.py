"""Fixed asset register and depreciation (backlog P2-19, spec 6).

- The Accountant registers each asset: class, division (and machine), acquisition date and
  cost, the first month to depreciate, a residual value, and, for a register brought in at
  go-live, the depreciation already charged. Registering posts nothing: the cost reached the
  books through the supplier's invoice or voucher (or the opening balances).
- Each class has dated defaults (rule 11): method, annual rate and useful life (owner, 8 Nov
  2026: straight line; buildings 5% / 20 years, plant and machinery 10% / 10, computers and
  software 25% / 4, furniture and fittings 25% / 4, motor vehicles 20% / 5). The Accountant
  changes them and the Director approves ("asset_class_rate").
- Each asset has its own terms: a new asset takes its class's defaults, which the Accountant
  may change for it, and the Director approves every asset's terms ("asset_terms"); a later
  change is new terms from a later month. An asset is depreciated only with approved terms,
  and a month cannot be worked out while an asset due waits for them. A month is worked out
  with the terms in force at its end: straight line is (cost − residual) × rate
  ÷ 12; reducing balance is book value × rate ÷ 12; neither takes the book value below the
  residual value; land is not depreciated. A class with assets and no rate stops the month
  until the Accountant enters one.
- The month is a draft for the Accountant to check, then posted: Dr depreciation, Cr
  accumulated depreciation, per class and division, dated the last day of the month. Months
  are posted in order and never change.
- A disposal (sale or scrapping) posts: Dr accumulated depreciation, Dr the bank or cash the
  money went into, Cr the asset's cost, and the difference as a gain or loss on disposal. The
  months before it must be posted first; it is not depreciated in the month it goes.
"""

import calendar
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.db.models import QuerySet, Sum
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account
from apps.accounting.services import AccountingError
from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.core.numbering import NumberSeriesError, allocate
from apps.masters.models import CompanyAccount, Machine

from .models import (
    Approval,
    AssetClass,
    AssetClassRate,
    AssetTerms,
    DepreciationLine,
    DepreciationRun,
    FixedAsset,
    Method,
)

ZERO = Decimal("0")
CENT = Decimal("0.01")
TWELVE = Decimal("12")
HUNDRED = Decimal("100")


class AssetError(Exception):
    pass


def can_manage(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def _accountant(user: User) -> None:
    if not can_manage(user):
        raise AssetError("Only the Accountant keeps the fixed asset register.")


def month_end(day: date) -> date:
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def month_start(day: date) -> date:
    return day.replace(day=1)


def _money(value, what: str, *, zero_ok: bool = True) -> Decimal:
    if isinstance(value, float):
        raise AssetError(f"The {what} must be an exact amount.")
    try:
        amount = Decimal(str(value if value not in (None, "") else "0").replace(",", ""))
    except InvalidOperation:
        raise AssetError(f"The {what} is not a number.") from None
    if not amount.is_finite() or amount < 0 or (amount == 0 and not zero_ok):
        raise AssetError(f"The {what} must be {'0 or ' if zero_ok else ''}more than 0.")
    if amount != amount.quantize(CENT):
        raise AssetError(f"The {what} is to the cent.")
    return amount


# --- Classes and rates -----------------------------------------------------------------------


def rate_on(asset_class: AssetClass, day: date) -> AssetClassRate | None:
    """The class's approved defaults in force on the day."""
    return (
        asset_class.rates.filter(effective_from__lte=day, status=Approval.APPROVED)
        .order_by("-effective_from")
        .first()
    )


def _terms(method: str, rate, life_years) -> tuple[str, Decimal, int | None]:
    """Check a method, annual rate and useful life together. For straight line the rate is
    100 ÷ the life; either may be given and the other is worked out."""
    if method not in Method.values:
        raise AssetError("Choose the method: straight line, reducing balance or none.")
    text = str(rate if rate is not None else "").replace("%", "").strip()
    try:
        rate = Decimal(text) if text else None
    except InvalidOperation:
        raise AssetError("The rate is not a number.") from None
    if rate is not None and (
        not rate.is_finite()
        or rate < 0
        or rate > HUNDRED
        or rate != rate.quantize(Decimal("0.0001"))
    ):
        raise AssetError("The rate is a percentage a year, from 0 to 100.")
    life_text = str(life_years if life_years is not None else "").strip()
    try:
        life = int(life_text) if life_text else None
    except ValueError:
        raise AssetError("The useful life is a whole number of years.") from None
    if life is not None and not 1 <= life <= 100:
        raise AssetError("The useful life is 1 to 100 years.")
    if method == Method.NONE:
        return method, ZERO, None
    if method == Method.STRAIGHT_LINE:
        if rate is None and life is None:
            raise AssetError("Give the useful life in years (or the rate a year).")
        if rate is None:
            rate = (HUNDRED / life).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        elif life is None and rate and (HUNDRED / rate) == (HUNDRED / rate).to_integral_value():
            life = int(HUNDRED / rate)
        elif life is not None and abs(rate * life - HUNDRED) > Decimal("0.01") * life:
            raise AssetError(
                f"For straight line the rate is 100 ÷ the useful life: {life} years is "
                f"{(HUNDRED / life).quantize(Decimal('0.01'))}% a year."
            )
    if not rate:
        raise AssetError("Give the rate (a percentage a year).")
    return method, rate, life


def _last_posted() -> DepreciationRun | None:
    return DepreciationRun.objects.filter(status=DepreciationRun.Status.POSTED).first()


def add_rate(
    user: User,
    asset_class: AssetClass,
    *,
    effective_from: date,
    method: str,
    rate=None,
    reason="",
    life_years=None,
) -> AssetClassRate:
    """New defaults for a class from a date, for the Director to approve; a posted month
    keeps the one it used, and assets already registered keep their own terms."""
    _accountant(user)
    method, rate, life = _terms(method, rate, life_years)
    effective_from = month_start(effective_from)
    last = _last_posted()
    if last is not None and effective_from <= last.month_end:
        raise AssetError(
            f"Depreciation is posted to {last.month_end:%d/%m/%Y}; a new rate starts after it."
        )
    with audit_context("asset_rate_added", reason), transaction.atomic():
        if (
            AssetClassRate.objects.filter(asset_class=asset_class, effective_from=effective_from)
            .exclude(status=Approval.REJECTED)
            .exists()
        ):
            raise AssetError(f"{asset_class.name} already has a rate from {effective_from}.")
        made = AssetClassRate.objects.create(
            asset_class=asset_class,
            effective_from=effective_from,
            method=method,
            rate=rate,
            life_years=life,
            status=Approval.AWAITING,
            reason=(reason or "").strip()[:2000],
            set_by=user,
        )
        _submit(
            user,
            "asset_class_rate",
            made.pk,
            f"{asset_class.name} defaults from {effective_from:%d/%m/%Y}: {_label(made)}",
            reason,
        )
        return made


def _label(x) -> str:
    if x.method == Method.NONE:
        return "not depreciated"
    life = f", {x.life_years} years" if x.life_years else ""
    return f"{Method(x.method).label.split(' (')[0].lower()} {x.rate.normalize():f}%{life}"


def _submit(user: User, document_type: str, pk: int, title: str, comment: str = "") -> None:
    try:
        approvals.submit(
            user,
            document_type,
            pk,
            created_by=user,
            title=title[:200],
            link="/fixed-assets",
            comment=(comment or "").strip()[:500],
        )
    except ApprovalError as error:
        raise AssetError(str(error)) from None


def _decide(user, document_type: str, pk: int, action: str, reason: str) -> str:
    """Approve or reject through the approval engine; the new status, or "" if more levels
    are still to approve."""
    try:
        if action == "approve":
            state = approvals.approve(user, document_type, pk, reason)
            return Approval.APPROVED if state.status == state.Status.APPROVED else ""
        if action == "reject":
            approvals.reject(user, document_type, pk, reason)
            return Approval.REJECTED
    except ApprovalError as error:
        raise AssetError(str(error)) from None
    raise AssetError("Approve or reject.")


def decide_rate(user: User, rate: AssetClassRate, action: str, reason: str = "") -> AssetClassRate:
    with audit_context("asset_rate_decided", reason), transaction.atomic():
        rate = AssetClassRate.objects.select_for_update().get(pk=rate.pk)
        if rate.status != Approval.AWAITING:
            raise AssetError("These defaults are not waiting for approval.")
        status = _decide(user, "asset_class_rate", rate.pk, action, reason)
        if status:
            rate.status = status
            rate.save(update_fields=["status"])
        return rate


# --- Each asset's terms ------------------------------------------------------------------------


def terms_on(asset: FixedAsset, day: date) -> AssetTerms | None:
    """The asset's approved terms in force on the day."""
    return (
        asset.terms.filter(effective_from__lte=day, status=Approval.APPROVED)
        .order_by("-effective_from")
        .first()
    )


def propose_terms(
    user: User,
    asset: FixedAsset,
    *,
    effective_from: date | None = None,
    method: str = "",
    rate=None,
    life_years=None,
    reason: str = "",
) -> AssetTerms:
    """The asset's method, rate and life from a month, for the Director to approve: its
    class's defaults unless the Accountant gives others."""
    _accountant(user)
    if asset.status != FixedAsset.Status.ACTIVE:
        raise AssetError(f"{asset.code} is disposed.")
    first = not asset.terms.exclude(status=Approval.REJECTED).exists()
    start = month_start(effective_from or asset.depreciation_from)
    if start < asset.depreciation_from:
        raise AssetError("The terms start in or after the month depreciation starts.")
    last = _last_posted()
    if not first and last is not None and start <= last.month_end:
        raise AssetError(
            f"Depreciation is posted to {last.month_end:%d/%m/%Y}; new terms start after it."
        )
    if not method:
        default = rate_on(asset.asset_class, start)
        if default is None:
            raise AssetError(
                f"{asset.asset_class.name} has no approved defaults: give the method and rate."
            )
        method, rate, life_years = default.method, default.rate, default.life_years
    method, rate, life = _terms(method, rate, life_years)
    with audit_context("asset_terms_proposed", reason), transaction.atomic():
        if asset.terms.filter(status=Approval.AWAITING).exists():
            raise AssetError(f"{asset.code} already has terms waiting for the Director.")
        if asset.terms.filter(effective_from=start).exclude(status=Approval.REJECTED).exists():
            raise AssetError(f"{asset.code} already has terms from {start:%d/%m/%Y}.")
        made = AssetTerms.objects.create(
            asset=asset,
            effective_from=start,
            method=method,
            rate=rate,
            life_years=life,
            reason=(reason or "").strip()[:2000],
            created_by=user,
        )
        _submit(
            user,
            "asset_terms",
            made.pk,
            f"{asset.code} {asset.name}: {_label(made)} from {start:%m/%Y}",
            reason,
        )
        return made


def decide_terms(user: User, terms: AssetTerms, action: str, reason: str = "") -> AssetTerms:
    with audit_context("asset_terms_decided", reason), transaction.atomic():
        terms = AssetTerms.objects.select_for_update().get(pk=terms.pk)
        if terms.status != Approval.AWAITING:
            raise AssetError("These terms are not waiting for approval.")
        status = _decide(user, "asset_terms", terms.pk, action, reason)
        if status:
            terms.status = status
            terms.decided_at = timezone.now()
            terms.save(update_fields=["status", "decided_at"])
        return terms


def send_all(user: User) -> int:
    """Assets registered before terms existed get their class's defaults, sent to the
    Director (owner's default of 8 Nov 2026: they keep their values, approved once)."""
    _accountant(user)
    sent = 0
    for asset in (
        visible(user)
        .filter(status=FixedAsset.Status.ACTIVE)
        .exclude(terms__status__in=[Approval.APPROVED, Approval.AWAITING])
        .select_related("asset_class")
        .distinct()
    ):
        if rate_on(asset.asset_class, asset.depreciation_from) is not None:
            propose_terms(user, asset, reason="Class defaults")
            sent += 1
    return sent


# --- The register ------------------------------------------------------------------------


def visible(user: User) -> QuerySet[FixedAsset]:
    if not effective_access(user).has("accounting", "view"):
        return FixedAsset.objects.none()
    return FixedAsset.objects.filter(division__in=division_scope(user))


def posted_depreciation(asset: FixedAsset, upto: date | None = None) -> Decimal:
    rows = DepreciationLine.objects.filter(asset=asset, run__status=DepreciationRun.Status.POSTED)
    if upto is not None:
        rows = rows.filter(run__month_end__lte=upto)
    return rows.aggregate(t=Sum("amount"))["t"] or ZERO


def accumulated(asset: FixedAsset, upto: date | None = None) -> Decimal:
    return asset.opening_accumulated + posted_depreciation(asset, upto)


def book_value(asset: FixedAsset, upto: date | None = None) -> Decimal:
    return asset.cost - accumulated(asset, upto)


FIELDS = ("name", "serial_no", "supplier", "notes")


def register(
    user: User,
    *,
    asset_class: AssetClass,
    division: Division,
    name: str,
    acquisition_date: date,
    cost,
    depreciation_from: date | None = None,
    residual_value=0,
    opening_accumulated=0,
    machine: Machine | None = None,
    serial_no: str = "",
    supplier: str = "",
    notes: str = "",
    method: str = "",
    rate=None,
    life_years=None,
    terms_reason: str = "",
) -> FixedAsset:
    """Register an asset and send its depreciation terms (the class's defaults, or the method,
    rate and life given) to the Director."""
    _accountant(user)
    if not isinstance(asset_class, AssetClass) or not asset_class.is_active:
        raise AssetError("Choose the asset class.")
    if not isinstance(division, Division):
        raise AssetError("Choose the division.")
    if not division_scope(user).filter(pk=division.pk).exists():
        raise AssetError(f"You do not work in division {division.code}.")
    name = (name or "").strip()[:200]
    if not name:
        raise AssetError("Give the asset's name.")
    if not isinstance(acquisition_date, date) or acquisition_date > timezone.localdate():
        raise AssetError("Give the date it was bought (not in the future).")
    cost = _money(cost, "cost", zero_ok=False)
    residual = _money(residual_value, "residual value")
    opening = _money(opening_accumulated, "depreciation already charged")
    if residual + opening > cost:
        raise AssetError("The residual value and the depreciation already charged exceed the cost.")
    start = month_start(depreciation_from or acquisition_date)
    if start < month_start(acquisition_date):
        raise AssetError("Depreciation starts in or after the month it was bought.")
    last = DepreciationRun.objects.filter(status=DepreciationRun.Status.POSTED).first()
    if last is not None and start <= last.month_end and not opening:
        raise AssetError(
            f"Depreciation is posted to {last.month_end:%d/%m/%Y}: start this asset after it, "
            "or give the depreciation already charged."
        )
    if machine is not None and machine.section.division_id != division.pk:
        raise AssetError(f"Machine {machine.code} is in another division.")
    with audit_context("fixed_asset_registered"), transaction.atomic():
        try:
            code = allocate("fixed_asset", on_date=timezone.localdate())
        except NumberSeriesError as error:
            raise AssetError(str(error)) from None
        asset = FixedAsset.objects.create(
            code=code,
            name=name,
            asset_class=asset_class,
            division=division,
            machine=machine,
            serial_no=(serial_no or "").strip()[:100],
            supplier=(supplier or "").strip()[:200],
            acquisition_date=acquisition_date,
            depreciation_from=start,
            cost=cost,
            residual_value=residual,
            opening_accumulated=opening,
            notes=(notes or "").strip(),
            created_by=user,
        )
        propose_terms(
            user,
            asset,
            method=method,
            rate=rate,
            life_years=life_years,
            reason=terms_reason or "Class defaults",
        )
        return asset


def update(user: User, asset: FixedAsset, values: dict) -> FixedAsset:
    """Name, serial number, supplier and notes; the rest is fixed once depreciated."""
    _accountant(user)
    with audit_context("fixed_asset_changed"), transaction.atomic():
        asset = FixedAsset.objects.select_for_update().get(pk=asset.pk)
        for field in FIELDS:
            if field in values:
                setattr(asset, field, str(values[field] or "").strip())
        if not asset.name:
            raise AssetError("Give the asset's name.")
        asset.save(update_fields=list(FIELDS))
        return asset


# --- Monthly depreciation ---------------------------------------------------------------------


def amount_for(asset: FixedAsset, end: date, book: Decimal, rate) -> Decimal:
    """One month's depreciation of the asset, its book value before it being `book`."""
    if rate.method == Method.NONE or end < asset.depreciation_from:
        return ZERO
    if asset.disposed_on is not None and asset.disposed_on <= end:
        return ZERO
    room = book - asset.residual_value
    if room <= 0:
        return ZERO
    if rate.method == Method.STRAIGHT_LINE:
        base = asset.cost - asset.residual_value
    else:
        base = book
    month = (base * rate.rate / HUNDRED / TWELVE).quantize(CENT, ROUND_HALF_UP)
    return min(month, room)


def next_month() -> date | None:
    """The month to work out next: the one after the last posted, or the earliest month an
    asset starts in."""
    last = DepreciationRun.objects.filter(status=DepreciationRun.Status.POSTED).first()
    if last is not None:
        return month_end(last.month_end + timedelta(days=1))
    first = (
        FixedAsset.objects.filter(status=FixedAsset.Status.ACTIVE)
        .order_by("depreciation_from")
        .first()
    )
    return month_end(first.depreciation_from) if first else None


def prepare(user: User, end: date) -> DepreciationRun:
    """Work the month out as a draft for the Accountant to check (again, if it was)."""
    _accountant(user)
    end = month_end(end)
    if end > month_end(timezone.localdate()):
        raise AssetError("That month has not come yet.")
    wanted = next_month()
    if (
        wanted is not None
        and end != wanted
        and DepreciationRun.objects.filter(status=DepreciationRun.Status.POSTED).exists()
    ):
        raise AssetError(f"The next month to depreciate is {wanted:%B %Y}.")
    assets = (
        FixedAsset.objects.filter(depreciation_from__lte=end)
        .exclude(status=FixedAsset.Status.DISPOSED, disposed_on__lte=end)
        .select_related("asset_class")
        .order_by("code")
    )
    waiting = [a.code for a in assets if terms_on(a, end) is None]
    if waiting:
        raise AssetError(
            "No approved depreciation terms for: " + ", ".join(waiting) + ". The Director "
            "approves each asset's method, rate and life (Fixed assets → Waiting for approval)."
        )
    with audit_context("depreciation_prepared"), transaction.atomic():
        run = DepreciationRun.objects.select_for_update().filter(month_end=end).first()
        if run is not None and run.status == DepreciationRun.Status.POSTED:
            raise AssetError(f"Depreciation for {end:%B %Y} is posted already.")
        if run is None:
            run = DepreciationRun.objects.create(month_end=end, prepared_by=user)
        else:
            run.lines.all().delete()
        total = ZERO
        for asset in assets:
            rate = terms_on(asset, end)
            book = book_value(asset)
            amount = amount_for(asset, end, book, rate)
            if amount <= 0:
                continue
            DepreciationLine.objects.create(
                run=run,
                asset=asset,
                method=rate.method,
                rate=rate.rate,
                book_value_before=book,
                amount=amount,
            )
            total += amount
        run.total = total
        run.prepared_by = user
        run.prepared_at = timezone.now()
        run.save(update_fields=["total", "prepared_by", "prepared_at"])
        return run


def post(user: User, run: DepreciationRun) -> DepreciationRun:
    """The Accountant has checked the month: post it."""
    _accountant(user)
    with audit_context("depreciation_posted"), transaction.atomic():
        run = DepreciationRun.objects.select_for_update().get(pk=run.pk)
        if run.status != DepreciationRun.Status.DRAFT:
            raise AssetError("This month is posted already.")
        wanted = next_month()
        if (
            wanted is not None
            and run.month_end != wanted
            and DepreciationRun.objects.filter(status=DepreciationRun.Status.POSTED).exists()
        ):
            raise AssetError(f"Post {wanted:%B %Y} first.")
        lines = list(run.lines.select_related("asset__asset_class", "asset__division"))
        if not lines:
            raise AssetError("There is nothing to depreciate this month.")
        debits: dict[tuple, Decimal] = {}
        credits: dict[tuple, Decimal] = {}
        for line in lines:
            c = line.asset.asset_class
            key_d = (c.expense_account_id, line.asset.division_id)
            key_c = (c.accumulated_account_id, line.asset.division_id)
            debits[key_d] = debits.get(key_d, ZERO) + line.amount
            credits[key_c] = credits.get(key_c, ZERO) + line.amount
        accounts = Account.objects.in_bulk({k[0] for k in [*debits, *credits]})
        divisions = Division.objects.in_bulk({k[1] for k in [*debits, *credits]})
        text = f"Depreciation {run.month_end:%B %Y}"
        entry_lines = [
            journal.Line(account=accounts[a], debit=v, division=divisions[d], description=text)
            for (a, d), v in debits.items()
        ] + [
            journal.Line(account=accounts[a], credit=v, division=divisions[d], description=text)
            for (a, d), v in credits.items()
        ]
        try:
            entry = journal.post(
                user,
                entry_date=run.month_end,
                narration=f"{text}: {len(lines)} asset(s)",
                lines=entry_lines,
                source_type="depreciation",
                source_id=f"{run.month_end:%Y-%m}",
            )
        except AccountingError as error:
            raise AssetError(str(error)) from None
        run.status = DepreciationRun.Status.POSTED
        run.journal_entry = entry
        run.posted_by = user
        run.posted_at = timezone.now()
        run.save(update_fields=["status", "journal_entry", "posted_by", "posted_at"])
        return run


def discard(user: User, run: DepreciationRun) -> None:
    _accountant(user)
    if run.status != DepreciationRun.Status.DRAFT:
        raise AssetError("A posted month is never removed.")
    with audit_context("depreciation_discarded"):
        run.delete()


# --- Disposal ------------------------------------------------------------------------------


def dispose(
    user: User,
    asset: FixedAsset,
    *,
    disposed_on: date,
    proceeds=0,
    account: CompanyAccount | None = None,
    reason: str = "",
) -> FixedAsset:
    """Sold or scrapped: the asset leaves the books with the gain or loss on disposal."""
    _accountant(user)
    reason = (reason or "").strip()
    if not reason:
        raise AssetError("Say why the asset is disposed of (sold, scrapped…).")
    if not isinstance(disposed_on, date) or disposed_on > timezone.localdate():
        raise AssetError("Give the date of disposal (not in the future).")
    proceeds = _money(proceeds, "amount received")
    if proceeds and (account is None or account.ledger_account_id is None):
        raise AssetError("Choose the bank or cash account the money went into.")
    with audit_context("fixed_asset_disposed", reason), transaction.atomic():
        asset = (
            FixedAsset.objects.select_for_update().select_related("asset_class").get(pk=asset.pk)
        )
        if asset.status != FixedAsset.Status.ACTIVE:
            raise AssetError(f"{asset.code} is disposed of already.")
        if disposed_on < asset.acquisition_date:
            raise AssetError("An asset is disposed of after it was bought.")
        last = DepreciationRun.objects.filter(status=DepreciationRun.Status.POSTED).first()
        if last is not None and last.month_end >= month_start(disposed_on):
            raise AssetError(
                f"Depreciation is posted to {last.month_end:%d/%m/%Y}, after this date; the "
                "disposal is dated after it."
            )
        before = month_start(disposed_on) - timedelta(days=1)
        rate = rate_on(asset.asset_class, before)
        needs_months = (
            rate is not None and rate.method != Method.NONE and asset.depreciation_from <= before
        )
        if needs_months and (last is None or last.month_end < before):
            raise AssetError(f"Post the depreciation up to {before:%B %Y} first.")
        c = asset.asset_class
        charged = accumulated(asset)
        left = asset.cost - charged
        difference = proceeds - left
        text = f"Disposal of {asset.code} {asset.name}"
        lines = [
            journal.Line(
                account=c.cost_account, credit=asset.cost, division=asset.division, description=text
            )
        ]
        if charged:
            lines.append(
                journal.Line(
                    account=c.accumulated_account,
                    debit=charged,
                    division=asset.division,
                    description=text,
                )
            )
        if proceeds:
            lines.append(
                journal.Line(account=account.ledger_account, debit=proceeds, description=text)
            )
        if difference > 0:
            lines.append(
                journal.Line(
                    account=c.gain_account,
                    credit=difference,
                    division=asset.division,
                    description=text,
                )
            )
        elif difference < 0:
            lines.append(
                journal.Line(
                    account=c.loss_account,
                    debit=-difference,
                    division=asset.division,
                    description=text,
                )
            )
        try:
            entry = journal.post(
                user,
                entry_date=disposed_on,
                narration=f"{text}: {reason}"[:500],
                lines=lines,
                source_type="asset_disposal",
                source_id=asset.code,
            )
        except AccountingError as error:
            raise AssetError(str(error)) from None
        asset.status = FixedAsset.Status.DISPOSED
        asset.disposed_on = disposed_on
        asset.proceeds = proceeds
        asset.disposal_reason = reason[:2000]
        asset.disposal_entry = entry
        asset.save(
            update_fields=["status", "disposed_on", "proceeds", "disposal_reason", "disposal_entry"]
        )
        return asset
