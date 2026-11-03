# ruff: noqa: F811 - the fixtures of test_bank_statements are imported and used by name
"""Bank reconciliation (backlog P2-16)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account, JournalEntry
from apps.banking import reconcile, statements
from apps.banking.models import BankRule, BankStatementLine, StatementMatch, StatementTemplate
from apps.banking.services import BankingError
from apps.core.models import Division

from .test_access import as_user
from .test_bank_statements import accountant, bank  # noqa: F401 - fixtures used by name

pytestmark = pytest.mark.django_db
D = Decimal
TODAY = timezone.localdate()
END = reconcile.month_end(TODAY.replace(day=1) - timedelta(days=1))  # last month


def day(n):
    return END.replace(day=n)


def ws():
    return Division.objects.get(code="WS")


def income():
    return Account.objects.filter(account_type="income", is_active=True).first()


def expense():
    return Account.objects.get(number="6210")


def book(user, on, amount, source_id="", text="entry"):
    """An entry through the bank: + money in, − money out."""
    bank_ledger = Account.objects.get(number="1030")
    other = income() if amount > 0 else expense()
    value = abs(D(amount))
    lines = [
        journal.Line(
            account=bank_ledger, debit=value if amount > 0 else 0, credit=value if amount < 0 else 0
        ),
        journal.Line(
            account=other,
            debit=value if amount < 0 else 0,
            credit=value if amount > 0 else 0,
            division=ws(),
        ),
    ]
    return journal.post(
        user,
        entry_date=on,
        narration=text,
        lines=lines,
        source_type="test",
        source_id=source_id,
    )


def statement(user, account, rows, opening="0"):
    template = StatementTemplate.objects.filter(code="CSV").first() or statements.save_template(
        user, None, {"code": "csv", "bank_name": "Test", "file_kind": "csv"}
    )
    text = "Date,Description,Debit,Credit,Balance\n" + "".join(
        f"{d:%d/%m/%Y},{desc},{out},{inn},{bal}\n" for d, desc, out, inn, bal in rows
    )
    return statements.import_file(
        user,
        account=account,
        template=template,
        content=text.encode(),
        file_name="s.csv",
        opening=opening,
    )


@pytest.fixture
def month(accountant, bank):
    """The books and the bank for last month (see the module's figures)."""
    entries = {
        "deposit": book(accountant, day(4), 20000, "DP-000777", "Deposit"),
        "cheque": book(accountant, day(6), -1000, "000100", "Cheque 000100"),
        "other": book(accountant, day(7), -1000, "", "Another 1,000"),
        "late": book(accountant, day(20), -500, "000101", "Cheque not presented"),
    }
    s = statement(
        accountant,
        bank,
        [
            (day(5), "CHQ DEP 000777", "", "20000.00", "20000.00"),
            (day(8), "CHQ 000100", "1000.00", "", "19000.00"),
            (day(10), "SERVICE CHARGE", "250.00", "", "18750.00"),
        ],
    )
    return entries, {line.description: line for line in s.lines.all()}


def test_suggestions_prefer_the_reference_on_the_line(month, bank):
    entries, lines = month
    items = reconcile.book_items(bank)
    assert (
        reconcile.suggestion(lines["CHQ DEP 000777"], items)["entry"]["id"] == entries["deposit"].pk
    )
    found = reconcile.candidates(lines["CHQ 000100"], items)
    assert [c["entry"]["id"] for c in found] == [entries["cheque"].pk, entries["other"].pk]
    assert reconcile.suggestion(lines["CHQ 000100"], items)["entry"]["id"] == entries["cheque"].pk
    assert reconcile.suggestion(lines["SERVICE CHARGE"], items) is None


def test_the_month_is_reconciled_and_locked(month, accountant, bank):
    entries, lines = month
    assert reconcile.accept_suggestions(accountant, bank, END) == 2
    with pytest.raises(BankingError, match="not in the books"):
        reconcile.finish(accountant, bank, END)
    BankRule.objects.create(
        text="service charge", ledger=expense(), division=ws(), created_by=accountant
    )
    coding = reconcile.coding_for(lines["SERVICE CHARGE"])
    assert (coding["ledger"]["number"], coding["division"], coding["from"]) == (
        "6210",
        "WS",
        "rule",
    )
    reconcile.post_line(accountant, lines["SERVICE CHARGE"], account=expense(), division=ws())
    figures = reconcile.summary(bank, END)
    assert (figures["bank_balance"], figures["book_balance"]) == (D("18750.00"), D("17250.00"))
    assert figures["unpresented_total"] == D("-1500.00")  # the other 1,000 and cheque 000101
    assert figures["difference"] == D("0")
    reconcile.finish(accountant, bank, END, "October done")
    with pytest.raises(BankingError, match="locked"):
        reconcile.unmatch(accountant, lines["CHQ 000100"])
    with pytest.raises(DatabaseError, match="locked"), transaction.atomic():
        StatementMatch.objects.filter(line=lines["CHQ 000100"]).delete()
    with pytest.raises(BankingError, match="already reconciled"):
        reconcile.finish(accountant, bank, END)


def test_a_match_must_move_the_same_money(month, accountant):
    entries, lines = month
    with pytest.raises(BankingError, match="does not move 1,000.00 out of"):
        reconcile.match(accountant, lines["CHQ 000100"], entries["late"])
    reconcile.match(accountant, lines["CHQ 000100"], entries["other"])
    with pytest.raises(BankingError, match="already matched"):
        reconcile.match(accountant, lines["CHQ 000100"], entries["cheque"])
    reconcile.unmatch(accountant, lines["CHQ 000100"])
    assert not StatementMatch.objects.exists()


def test_a_line_posted_before_teaches_the_next(month, accountant, bank):
    _, lines = month
    reconcile.post_line(accountant, lines["SERVICE CHARGE"], account=expense(), division=ws())
    later = statement(
        accountant,
        bank,
        [(day(28), "SERVICE CHARGE 12", "100.00", "", "18650.00")],
        opening="18750.00",
    )
    line = later.lines.get()
    assert reconcile.coding_for(line)["from"] == "earlier"


def test_bank_and_customer_accounts_are_not_posted_from_a_line(month, accountant):
    _, lines = month
    with pytest.raises(BankingError, match="not posted from a statement line"):
        reconcile.post_line(
            accountant, lines["SERVICE CHARGE"], account=Account.objects.get(number="1100")
        )


def test_the_reconciliation_page_through_the_api(month, accountant, bank):
    client = as_user(accountant)
    url = f"/api/v1/reconciliation/?account={bank.pk}&period_end={END}"
    body = client.get(url).json()
    assert len(body["lines"]) == 3
    assert body["lines"][0]["suggestion"]["source_id"] == "DP-000777"
    accepted = client.post(
        "/api/v1/reconciliation/accept/",
        {"account": bank.pk, "period_end": str(END)},
        format="json",
    )
    assert accepted.json() == {"matched": 2}
    charge = BankStatementLine.objects.get(description="SERVICE CHARGE")
    posted = client.post(
        "/api/v1/reconciliation/post/",
        {"line": charge.pk, "account": expense().pk, "division": "WS"},
        format="json",
    )
    assert posted.status_code == 201, posted.content
    done = client.post(
        "/api/v1/reconciliation/finish/",
        {"account": bank.pk, "period_end": str(END)},
        format="json",
    )
    assert done.status_code == 201, done.content
    assert JournalEntry.objects.filter(source_type="bank_line").count() == 1
