"""Document numbers (backlog P0-08, spec 3 Number series; rule 10).

Every document gets its number from `allocate()`, called inside the transaction that saves
the document. The running number is taken with one INSERT ... ON CONFLICT DO UPDATE, which
locks that counter until the saving transaction ends: concurrent saves queue up and receive
consecutive numbers, and a save that fails gives its number back with everything else.

A number once given is never given again: every issued number is kept for good (an
insert-only table), counters can only go up, and if a format or reset change would ever
produce a number given before, that number is skipped.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from .audit import audited
from .models import Division, IssuedNumber, NumberCounter, NumberSeries
from .organisation import mark_division_used

TOKEN = re.compile(r"\{([^{}]*)\}")
LITERAL = re.compile(r"^[A-Za-z0-9\-/._]*$")
DATE_TOKENS = {"YY", "YYYY", "MM", "MMM", "DD"}
DIVISION_TOKENS = {"PP", "IC"}
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
IC_WIDTH = 15
NO_TAX_INVOICE_CODE = "(no tax invoice code yet)"
MAX_WIDTH = 9
MAX_LENGTH = 40  # the longest tax invoice serial number allowed (Gazette 2481/22)
MAX_SKIPS = 1000

# What a format must show so that numbers cannot repeat after the running number restarts.
RESET_NEEDS = {
    NumberSeries.Reset.DAILY: ("year", "MM", "DD"),
    NumberSeries.Reset.MONTHLY: ("year", "MM"),
    NumberSeries.Reset.YEARLY: ("year",),
    NumberSeries.Reset.NEVER: (),
}
RESET_LABEL = {
    NumberSeries.Reset.DAILY: "every day",
    NumberSeries.Reset.MONTHLY: "every month",
    NumberSeries.Reset.YEARLY: "every year",
}
NEED_LABEL = {
    "year": "the year ({YY} or {YYYY})",
    "MM": "the month ({MM} or {MMM})",
    "DD": "the day ({DD})",
}


class NumberSeriesError(Exception):
    pass


@dataclass
class ParsedFormat:
    parts: list[tuple[str, str]] = field(default_factory=list)  # ("text"|"token", value)
    width: int = 0
    tokens: set[str] = field(default_factory=set)

    @property
    def has_division(self) -> bool:
        """The number shows the division, so each division has its own running number."""
        return bool(DIVISION_TOKENS & self.tokens)

    def shows(self, need: str) -> bool:
        if need == "year":
            return bool({"YY", "YYYY"} & self.tokens)
        if need == "MM":
            return bool({"MM", "MMM"} & self.tokens)
        return need in self.tokens


def parse_format(number_format: str) -> ParsedFormat:
    number_format = (number_format or "").strip()
    if not number_format:
        raise NumberSeriesError("The number format is required.")
    parsed = ParsedFormat()
    position = 0
    for match in TOKEN.finditer(number_format):
        _add_text(parsed, number_format[position : match.start()])
        _add_token(parsed, match.group(1).strip().upper())
        position = match.end()
    _add_text(parsed, number_format[position:])
    if not parsed.width:
        raise NumberSeriesError("The format needs one running number, for example {XXX}.")
    if {"YY", "YYYY"} <= parsed.tokens:
        raise NumberSeriesError("Use either {YY} or {YYYY}, not both.")
    if {"MM", "MMM"} <= parsed.tokens:
        raise NumberSeriesError("Use either {MM} or {MMM}, not both.")
    if _length(parsed) > MAX_LENGTH:
        raise NumberSeriesError(f"Numbers in this format would be longer than {MAX_LENGTH}.")
    return parsed


def _add_text(parsed: ParsedFormat, text: str) -> None:
    if not text:
        return
    if not LITERAL.match(text):
        raise NumberSeriesError(
            f"“{text}” is not allowed: outside the tokens use only letters, digits and - / . _"
        )
    parsed.parts.append(("text", text))


def _add_token(parsed: ParsedFormat, token: str) -> None:
    if token and set(token) in ({"X"}, {"N"}):
        if parsed.width:
            raise NumberSeriesError("The format can have only one running number.")
        if len(token) > MAX_WIDTH:
            raise NumberSeriesError(f"The running number can have at most {MAX_WIDTH} digits.")
        parsed.width = len(token)
        parsed.parts.append(("token", "RUN"))
        return
    if token not in DATE_TOKENS | DIVISION_TOKENS:
        raise NumberSeriesError(
            f"Unknown token {{{token}}}. Use {{PP}}, {{IC}}, {{YY}}, {{YYYY}}, {{MM}}, {{MMM}}, "
            "{DD}, and one running number such as {XXX}."
        )
    if token in parsed.tokens:
        raise NumberSeriesError(f"{{{token}}} appears twice.")
    parsed.tokens.add(token)
    parsed.parts.append(("token", token))


def _length(parsed: ParsedFormat) -> int:
    sizes = {"PP": 2, "IC": IC_WIDTH, "YY": 2, "YYYY": 4, "MM": 2, "MMM": 3, "DD": 2}
    sizes["RUN"] = parsed.width
    return sum(len(v) if kind == "text" else sizes[v] for kind, v in parsed.parts)


def check(number_format: str, reset_period: str) -> ParsedFormat:
    """Validate a format with its reset period: the format must show the date parts the
    reset depends on, or the same number would come round again."""
    if reset_period not in NumberSeries.Reset.values:
        raise NumberSeriesError("Choose when the running number restarts.")
    parsed = parse_format(number_format)
    missing = [NEED_LABEL[n] for n in RESET_NEEDS[reset_period] if not parsed.shows(n)]
    if missing:
        raise NumberSeriesError(
            f"The running number restarts {RESET_LABEL[reset_period]}, so the format must "
            f"show {' and '.join(missing)}; otherwise numbers would repeat."
        )
    return parsed


def period_key(reset_period: str, on_date: date) -> str:
    return {
        NumberSeries.Reset.DAILY: on_date.isoformat(),
        NumberSeries.Reset.MONTHLY: on_date.strftime("%Y-%m"),
        NumberSeries.Reset.YEARLY: on_date.strftime("%Y"),
        NumberSeries.Reset.NEVER: "all",
    }[reset_period]


def render(parsed: ParsedFormat, division: Division | None, on_date: date, running: int) -> str:
    values = {
        "PP": division.code if division else "",
        "IC": division.tax_invoice_code if division else "",
        "YY": on_date.strftime("%y"),
        "YYYY": on_date.strftime("%Y"),
        "MM": on_date.strftime("%m"),
        "MMM": MONTHS[on_date.month - 1],  # fixed English letters, whatever the server locale
        "DD": on_date.strftime("%d"),
        "RUN": str(running).zfill(parsed.width),
    }
    return "".join(v if kind == "text" else values[v] for kind, v in parsed.parts)


def _limit(parsed: ParsedFormat) -> int:
    return 10**parsed.width - 1


def _series(document_type: str) -> NumberSeries:
    try:
        return NumberSeries.objects.get(document_type=document_type)
    except NumberSeries.DoesNotExist:
        raise NumberSeriesError(f"There is no number series for {document_type}.") from None


def _counter_division(parsed: ParsedFormat, division: Division | None) -> Division | None:
    if parsed.has_division and division is None:
        raise NumberSeriesError("This document needs a division: its number shows it.")
    if "IC" in parsed.tokens and not division.tax_invoice_code:
        raise NumberSeriesError(
            f"Division {division.code} has no tax invoice code yet. The Admin sets it in "
            "Settings → Divisions."
        )
    # Without {PP} in the number, all divisions share one running number, or they would clash.
    return division if parsed.has_division else None


_NEXT_SQL = """
INSERT INTO core_numbercounter (series_id, division_id, period, last_number)
VALUES (%s, %s, %s, 1)
ON CONFLICT ON CONSTRAINT core_numbercounter_unique
DO UPDATE SET last_number = core_numbercounter.last_number + 1
RETURNING last_number
"""


def allocate(document_type: str, *, division: Division | None = None, on_date=None) -> str:
    """Give the next number. Call it inside the transaction that saves the document."""
    if not connection.in_atomic_block:
        raise NumberSeriesError("Numbers are given only inside the saving transaction.")
    series = _series(document_type)
    parsed = parse_format(series.format)
    counter_division = _counter_division(parsed, division)
    if division is not None and not division.is_active:
        raise NumberSeriesError(
            f"Division {division.code} is deactivated and cannot be used on new documents."
        )
    on_date = on_date or timezone.localdate()
    period = period_key(series.reset_period, on_date)
    limit = _limit(parsed)

    # A savepoint: if the number is refused, the counter is left exactly as it was.
    with transaction.atomic():
        for _ in range(MAX_SKIPS):
            with connection.cursor() as cursor:
                cursor.execute(
                    _NEXT_SQL,
                    [series.pk, counter_division.pk if counter_division else None, period],
                )
                running = cursor.fetchone()[0]
            if running > limit and series.when_full == NumberSeries.WhenFull.STOP:
                raise NumberSeriesError(_full_message(series, parsed, division, period, limit))
            number = render(parsed, division, on_date, running)
            try:
                with transaction.atomic():
                    IssuedNumber.objects.create(series=series, number=number, division=division)
            except IntegrityError:
                continue  # given before under an earlier format or reset: skip it, never reuse
            if division is not None:
                mark_division_used(division)
            return number
    raise NumberSeriesError("No unused number is left in this period. Widen the running number.")


def _full_message(series, parsed, division, period, limit) -> str:
    where = f" for division {division.code}" if parsed.has_division and division else ""
    when = "" if period == "all" else f" in {period}"
    wider = "X" * (parsed.width + 1)
    return (
        f"{series.name}: all {limit:,} numbers{where}{when} have been used. The Admin can widen "
        f"the running number (for example to {{{wider}}}) in Settings → Number series."
    )


def preview(
    series: NumberSeries,
    *,
    division: Division | None = None,
    on_date=None,
    number_format: str | None = None,
    reset_period: str | None = None,
) -> str:
    """The number the next document would get, without giving it."""
    number_format = series.format if number_format is None else number_format
    reset_period = series.reset_period if reset_period is None else reset_period
    parsed = check(number_format, reset_period)
    on_date = on_date or timezone.localdate()
    if "IC" in parsed.tokens and division is not None and not division.tax_invoice_code:
        return NO_TAX_INVOICE_CODE
    counter_division = _counter_division(parsed, division)
    last = (
        NumberCounter.objects.filter(
            series=series,
            division=counter_division,
            period=period_key(reset_period, on_date),
        )
        .values_list("last_number", flat=True)
        .first()
    ) or 0
    running = last + 1
    if running > _limit(parsed) and series.when_full == NumberSeries.WhenFull.STOP:
        return "—"
    return render(parsed, division, on_date, running)


@audited("number_series_changed", reason_arg="reason")
@transaction.atomic
def update_series(
    series: NumberSeries,
    *,
    number_format: str,
    reset_period: str,
    reason: str,
    when_full: str | None = None,
) -> NumberSeries:
    if not (reason or "").strip():
        raise NumberSeriesError("Give a reason for changing the number format.")
    check(number_format, reset_period)
    series = NumberSeries.objects.select_for_update().get(pk=series.pk)
    series.format = number_format.strip()
    series.reset_period = reset_period
    if when_full is not None:
        if when_full not in NumberSeries.WhenFull.values:
            raise NumberSeriesError("Choose what happens when the running number is full.")
        series.when_full = when_full
    series.save()
    return series
