"""Currencies and exchange rates (backlog P0-11, spec 3A.4).

A rate is LKR for one unit of a currency on a date. A document uses the rate of its date;
when that date has none, the latest earlier rate is used and the document shows it was
carried forward. Once a document has used a rate, the rate cannot change (rule 11).
"""

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from apps.core.audit import audit_context, record

from .models import Currency, ExchangeRate
from .services import MastersError

CODE = re.compile(r"^[A-Z]{3}$")
RATE_PLACES = Decimal("0.000001")
IMPORT_MAX_BYTES = 1024 * 1024
IMPORT_MAX_ROWS = 10000


# --- Currencies -------------------------------------------------------------------------


def _places(value) -> int:
    try:
        places = int(value)
    except (TypeError, ValueError):
        raise MastersError("Decimal places must be a whole number from 0 to 4.") from None
    if not 0 <= places <= 4:
        raise MastersError("Decimal places must be from 0 to 4.")
    return places


def create_currency(*, code, name, symbol="", decimal_places=2, reason="") -> Currency:
    code = (code or "").strip().upper()
    if not CODE.match(code):
        raise MastersError("The currency code must be the 3-letter ISO code, for example USD.")
    name = (name or "").strip()
    if not name:
        raise MastersError("The currency name is required.")
    with audit_context("currency_created", reason), transaction.atomic():
        if Currency.objects.filter(code=code).exists():
            raise MastersError(f"{code} is already in the list.")
        return Currency.objects.create(
            code=code,
            name=name,
            symbol=(symbol or "").strip(),
            decimal_places=_places(decimal_places),
        )


def update_currency(currency: Currency, data: dict, reason: str = "") -> Currency:
    with transaction.atomic():
        currency = Currency.objects.select_for_update().get(pk=currency.pk)
        event = "currency_changed"
        if currency.is_base and (
            data.get("is_active") is False or data.get("decimal_places") not in (None, 2)
        ):
            raise MastersError("LKR is the base currency: it stays active with 2 decimal places.")
        if "name" in data:
            name = (data["name"] or "").strip()
            if not name:
                raise MastersError("The currency name is required.")
            currency.name = name
        if "symbol" in data:
            currency.symbol = (data["symbol"] or "").strip()
        if "decimal_places" in data:
            places = _places(data["decimal_places"])
            if (
                places != currency.decimal_places
                and currency.rates.filter(first_used_at__isnull=False).exists()
            ):
                raise MastersError(
                    f"{currency.code} has been used on documents, so its decimal places cannot "
                    "change."
                )
            currency.decimal_places = places
        if "is_active" in data and bool(data["is_active"]) != currency.is_active:
            if not data["is_active"]:
                if not (reason or "").strip():
                    raise MastersError("Give a reason for switching the currency off.")
                event = "currency_switched_off"
            else:
                event = "currency_switched_on"
            currency.is_active = bool(data["is_active"])
        with audit_context(event, reason):
            currency.save()
        return currency


# --- Rates ------------------------------------------------------------------------------


def _rate(value, label="The rate") -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value).replace(",", "").strip())
    except InvalidOperation:
        raise MastersError(f"{label} must be a number, for example 299.5000.") from None
    if not amount.is_finite() or amount <= 0:
        raise MastersError(f"{label} must be more than zero.")
    if amount != amount.quantize(RATE_PLACES):
        raise MastersError(f"{label} can have at most 6 decimal places.")
    if amount >= Decimal("1e12"):
        raise MastersError(f"{label} is too large.")
    return amount


def _currency_for_rates(code: str) -> Currency:
    currency = Currency.objects.filter(code=(code or "").strip().upper()).first()
    if currency is None:
        raise MastersError(f"Unknown currency {code}.")
    if currency.is_base:
        raise MastersError("LKR is the base currency; it has no exchange rate.")
    return currency


def set_rate(
    *,
    currency: Currency,
    on_date: date,
    rate=None,
    buying=None,
    selling=None,
    user=None,
    source=ExchangeRate.Source.MANUAL,
    reason: str = "",
) -> ExchangeRate:
    """Enter or correct the rate for one currency on one date.

    `rate` is the conversion rate; if it is left empty and the bank quotes both buying and
    selling, their middle is used."""
    if currency.is_base:
        raise MastersError("LKR is the base currency; it has no exchange rate.")
    if on_date > timezone.localdate():
        raise MastersError("A rate cannot be entered for a future date.")
    buying, selling = _rate(buying, "The buying rate"), _rate(selling, "The selling rate")
    rate = _rate(rate)
    if rate is None:
        if buying is None or selling is None:
            raise MastersError("Give the rate, or both the buying and selling rates.")
        rate = ((buying + selling) / 2).quantize(RATE_PLACES, ROUND_HALF_UP)
    if buying is not None and selling is not None and buying > selling:
        raise MastersError("The buying rate cannot be above the selling rate.")

    with transaction.atomic():
        existing = (
            ExchangeRate.objects.select_for_update().filter(currency=currency, date=on_date).first()
        )
        if existing is None:
            with audit_context("exchange_rate_entered", reason):
                return ExchangeRate.objects.create(
                    currency=currency,
                    date=on_date,
                    rate=rate,
                    buying=buying,
                    selling=selling,
                    source=source,
                    created_by=user if user is not None and user.is_authenticated else None,
                )
        if (existing.rate, existing.buying, existing.selling) == (rate, buying, selling):
            return existing
        if existing.first_used_at is not None:
            raise MastersError(
                f"The {currency.code} rate of {on_date} has been used on documents and cannot "
                "change."
            )
        if not (reason or "").strip():
            raise MastersError("Give a reason for correcting an entered rate.")
        existing.rate, existing.buying, existing.selling = rate, buying, selling
        existing.source = source
        with audit_context("exchange_rate_corrected", reason):
            existing.save()
        return existing


def delete_rate(rate: ExchangeRate, reason: str) -> None:
    if not (reason or "").strip():
        raise MastersError("Give a reason for removing the rate.")
    if rate.first_used_at is not None:
        raise MastersError("This rate has been used on documents and cannot be removed.")
    with audit_context("exchange_rate_removed", reason), transaction.atomic():
        rate.delete()


@dataclass
class RateLookup:
    currency: str
    asked_for: date
    rate: Decimal
    rate_date: date | None  # None for LKR
    rate_id: int | None

    @property
    def carried_forward(self) -> bool:
        """No rate for the day itself: the latest earlier rate is used, and documents say so."""
        return self.rate_date is not None and self.rate_date != self.asked_for


def rate_on(currency: Currency | str, on_date: date) -> RateLookup:
    if isinstance(currency, str):
        currency = Currency.objects.filter(code=currency.strip().upper()).first()
        if currency is None:
            raise MastersError("Unknown currency.")
    if currency.is_base:
        return RateLookup(currency.code, on_date, Decimal("1"), None, None)
    found = (
        ExchangeRate.objects.filter(currency=currency, date__lte=on_date).order_by("-date").first()
    )
    if found is None:
        raise MastersError(
            f"There is no {currency.code} rate on or before {on_date}. The Accountant enters it "
            "in Settings → Currencies and exchange rates."
        )
    return RateLookup(currency.code, on_date, found.rate, found.date, found.pk)


def to_lkr(amount: Decimal, lookup: RateLookup) -> Decimal:
    """An amount in the currency, converted to LKR and rounded half-up to the cent."""
    return (Decimal(amount) * lookup.rate).quantize(Decimal("0.01"), ROUND_HALF_UP)


@transaction.atomic
def mark_rate_used(lookup: RateLookup) -> None:
    """Record that a document used this rate (called by later phases). From then on the
    rate cannot change."""
    if lookup.rate_id is None:
        return
    now = timezone.now()
    if ExchangeRate.objects.filter(pk=lookup.rate_id, first_used_at__isnull=True).update(
        first_used_at=now
    ):
        rate = ExchangeRate.objects.get(pk=lookup.rate_id)
        record("update", rate, {"first_used_at": [None, now.isoformat()]}, event="first_used")


# --- CSV import -------------------------------------------------------------------------


class ImportRefused(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _date(text: str) -> date:
    text = (text or "").strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise MastersError(f"Date {text!r} must be written as YYYY-MM-DD.") from None


def import_rates(content: bytes, *, user, reason: str, dry_run: bool) -> dict:
    """Columns: date, currency, rate, and optionally buying and selling. All or nothing:
    one refused row means nothing is saved, and every refusal is listed."""
    if not (reason or "").strip():
        raise ImportRefused(["Give a reason for the import."])
    if len(content) > IMPORT_MAX_BYTES:
        raise ImportRefused(["The file must be 1 MB or smaller."])
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ImportRefused(["The file must be a CSV saved as UTF-8."]) from None
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip().lower() for h in (reader.fieldnames or [])]
    missing = [c for c in ("date", "currency") if c not in header]
    if missing or not ({"rate", "buying", "selling"} & set(header)):
        raise ImportRefused(
            ["The first line must name the columns: date, currency, rate (or buying, selling)."]
        )
    counts = {"added": 0, "corrected": 0, "unchanged": 0}
    errors = []
    with transaction.atomic():
        for number, raw in enumerate(reader, start=2):
            if number - 1 > IMPORT_MAX_ROWS:
                errors.append(f"More than {IMPORT_MAX_ROWS} rows.")
                break
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items()}
            if not any(row.values()):
                continue
            try:
                with transaction.atomic():
                    currency = _currency_for_rates(row.get("currency", ""))
                    on_date = _date(row.get("date", ""))
                    before = ExchangeRate.objects.filter(currency=currency, date=on_date).first()
                    saved = set_rate(
                        currency=currency,
                        on_date=on_date,
                        rate=row.get("rate"),
                        buying=row.get("buying"),
                        selling=row.get("selling"),
                        user=user,
                        source=ExchangeRate.Source.IMPORT,
                        reason=reason,
                    )
            except MastersError as error:
                errors.append(f"Line {number}: {error}")
                continue
            if before is None:
                counts["added"] += 1
            elif before.rate == saved.rate and (before.buying, before.selling) == (
                saved.buying,
                saved.selling,
            ):
                counts["unchanged"] += 1
            else:
                counts["corrected"] += 1
        if errors or dry_run:
            transaction.set_rollback(True)
    if errors:
        raise ImportRefused(errors)
    return {"dry_run": dry_run, **counts}
