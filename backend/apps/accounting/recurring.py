"""Recurring journals (backlog P2-02, spec 6).

- The Accountant (Accounting: Enter) keeps templates: a name, the narration, the lines (as a
  manual journal's), how often (every month, quarter or year), the day of the month (1 to 28,
  or the last day), a start and an optional end date, and whether it is an accrual reversed on
  the first day of the next month.
- Every morning the due templates each make a draft manual journal dated their day, in the
  name of the template's owner, who is told under the bell. Nothing is posted: the draft is
  checked, sent and approved by the Director like any manual journal. A month already closed
  is skipped (and the owner told).
- Changing a template changes only the journals it makes from then on.
"""

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from apps.core.audit import audit_context
from apps.core.models import User
from apps.core.notifications import notify
from apps.core.numbering import NumberSeriesError, allocate

from . import journal, manual
from .manual import LineInput
from .models import ManualJournal, ManualJournalLine, RecurringJournal, RecurringJournalLine
from .services import AccountingError

F = RecurringJournal.Frequency
STEP = {F.MONTHLY: 1, F.QUARTERLY: 3, F.YEARLY: 12}
LAST_DAY = 31


@dataclass
class Values:
    name: str
    narration: str
    frequency: str
    day_of_month: int
    start_date: date
    end_date: date | None = None
    reverse_next_month: bool = False


def visible(user: User) -> QuerySet[RecurringJournal]:
    if not manual.can_view(user):
        return RecurringJournal.objects.none()
    return RecurringJournal.objects.all()


def can_edit(user: User, template: RecurringJournal) -> bool:
    return manual.can_enter(user)


# --- Dates ----------------------------------------------------------------------------------


def _on(year: int, month: int, day: int) -> date:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, last if day == LAST_DAY else min(day, last))


def _add_months(day: date, months: int, day_of_month: int) -> date:
    index = day.year * 12 + day.month - 1 + months
    return _on(index // 12, index % 12 + 1, day_of_month)


def first_on_or_after(template: RecurringJournal, earliest: date) -> date:
    """The first date of the schedule (from the start date, every step) on or after
    `earliest`."""
    when = _on(template.start_date.year, template.start_date.month, template.day_of_month)
    if when < template.start_date:
        when = _add_months(when, STEP[template.frequency], template.day_of_month)
    while when < earliest:
        when = _add_months(when, STEP[template.frequency], template.day_of_month)
    return when


# --- Keeping templates ------------------------------------------------------------------------


def _check(values: Values) -> None:
    if not " ".join((values.name or "").split()):
        raise AccountingError("Give the recurring journal a name.")
    if not " ".join((values.narration or "").split()):
        raise AccountingError("The narration is required: say what the journal is for.")
    if values.frequency not in STEP:
        raise AccountingError("Choose how often: every month, quarter or year.")
    if not (1 <= values.day_of_month <= 28 or values.day_of_month == LAST_DAY):
        raise AccountingError("The day of the month is 1 to 28, or the last day.")
    if not isinstance(values.start_date, date):
        raise AccountingError("Give the start date.")
    if values.end_date is not None and values.end_date < values.start_date:
        raise AccountingError("The end date cannot be before the start date.")


def _lines(template: RecurringJournal, given: list[LineInput], user: User) -> None:
    if not given:
        raise AccountingError("Add the journal's lines.")
    if len(given) > manual.MAX_LINES:
        raise AccountingError(f"A journal can have at most {manual.MAX_LINES} lines.")
    rows = [manual._line(n, g, user) for n, g in enumerate(given, start=1)]
    if manual._locked(rows):
        raise AccountingError(manual.LOCK_MESSAGE)
    debits = sum((r.debit for r in rows), Decimal("0"))
    credits = sum((r.credit for r in rows), Decimal("0"))
    if debits != credits:
        raise AccountingError(
            f"The journal does not balance: debits {debits:,.2f}, credits {credits:,.2f}."
        )
    template.lines.all().delete()
    for row in rows:
        RecurringJournalLine.objects.create(
            recurring=template,
            line_no=row.line_no,
            account=row.account,
            division=row.division,
            supplier=row.supplier,
            description=row.description,
            debit=row.debit,
            credit=row.credit,
        )


def save(
    user: User, template: RecurringJournal | None, values: Values, lines: list[LineInput]
) -> RecurringJournal:
    if not manual.can_enter(user):
        raise AccountingError("Only the Accountant keeps recurring journals.")
    _check(values)
    event = "recurring_journal_changed" if template else "recurring_journal_created"
    with audit_context(event), transaction.atomic():
        if template is None:
            template = RecurringJournal(created_by=user)
        else:
            template = RecurringJournal.objects.select_for_update().get(pk=template.pk)
        template.name = " ".join(values.name.split())[:100]
        template.narration = " ".join(values.narration.split())[:400]
        template.frequency = values.frequency
        template.day_of_month = values.day_of_month
        template.start_date = values.start_date
        template.end_date = values.end_date
        template.reverse_next_month = bool(values.reverse_next_month)
        template.next_date = first_on_or_after(template, timezone.localdate())
        template.updated_at = timezone.now()
        template.save()
        _lines(template, lines, user)
        return template


def set_active(user: User, template: RecurringJournal, active: bool) -> RecurringJournal:
    if not manual.can_enter(user):
        raise AccountingError("Only the Accountant keeps recurring journals.")
    with audit_context("recurring_journal_switched"), transaction.atomic():
        template = RecurringJournal.objects.select_for_update().get(pk=template.pk)
        template.is_active = bool(active)
        if template.is_active:
            template.next_date = first_on_or_after(template, timezone.localdate())
        template.updated_at = timezone.now()
        template.save()
        return template


# --- Making the drafts ------------------------------------------------------------------------


def _make(template: RecurringJournal, when: date) -> ManualJournal | None:
    owner = template.created_by
    if journal.is_closed(when):
        notify(
            [owner],
            "journal_ready",
            title=f"Recurring journal {template.name} was not made for {when:%d %b %Y}",
            body="That month is closed. Enter the journal by hand in an open month if needed.",
            link="/journals/recurring",
        )
        return None
    try:
        number = allocate(manual.DOC, on_date=timezone.localdate())
    except NumberSeriesError as error:
        raise AccountingError(str(error)) from None
    mj = ManualJournal.objects.create(
        number=number,
        entry_date=when,
        narration=f"{template.narration} ({when:%b %Y})"[:500],
        created_by=owner,
        recurring=template,
        reverse_on=manual.first_of_next_month(when) if template.reverse_next_month else None,
    )
    for line in template.lines.all():
        ManualJournalLine.objects.create(
            journal=mj,
            line_no=line.line_no,
            account=line.account,
            division=line.division,
            supplier=line.supplier,
            description=line.description,
            debit=line.debit,
            credit=line.credit,
        )
    notify(
        [owner],
        "journal_ready",
        title=f"Journal {mj.number} ({template.name}) is ready to check and send",
        link=f"/journals/manual/{mj.pk}",
        document_type=manual.DOC,
        document_id=mj.pk,
    )
    return mj


def make_due(today: date | None = None) -> int:
    """Every morning: each active template makes the drafts that have come due (one for each
    date missed, if the job did not run), then moves to its next date."""
    today = today or timezone.localdate()
    made = 0
    for pk in RecurringJournal.objects.filter(is_active=True, next_date__lte=today).values_list(
        "pk", flat=True
    ):
        with audit_context("recurring_journal_made"), transaction.atomic():
            template = RecurringJournal.objects.select_for_update().get(pk=pk)
            while template.is_active and template.next_date <= today:
                when = template.next_date
                if template.end_date is not None and when > template.end_date:
                    template.is_active = False
                    break
                if _make(template, when) is not None:
                    made += 1
                template.next_date = _add_months(
                    when, STEP[template.frequency], template.day_of_month
                )
            template.save(update_fields=["next_date", "is_active"])
    return made
