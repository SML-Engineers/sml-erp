"""Customer advances (backlog P15-09, spec 5.2, rules 1, 2, 3, 5, 10, 11)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting.models import Account, DetailType
from apps.core import approvals
from apps.core.access import effective_access
from apps.core.access_defaults import ROLE_ACTIONS_V2
from apps.core.models import Division, Notification
from apps.masters import banking, currencies, customers
from apps.masters.models import Currency
from apps.sales import advances, services, workflow
from apps.sales.models import CustomerAdvance
from apps.sales.services import LineInput, SalesError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
S = CustomerAdvance.Status


@pytest.fixture
def cashier():
    return person("cashier@sml.lk", "cashier", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def unilever(executive):
    return customers.create_customer(executive, {"name": "Unilever Sri Lanka"})


def ledger(accountant, number, name):
    return chart.create_account(
        accountant,
        name=name,
        account_type="bank",
        detail_type=DetailType.objects.get(name="Current account"),
        number=number,
    )


@pytest.fixture
def bank(accountant):
    return banking.create_account(
        accountant,
        code="com-cur",
        kind="current",
        name="Commercial Bank current",
        bank_name="Commercial Bank",
        account_number="1000234567",
        ledger_account=ledger(accountant, "1030", "Commercial Bank current").pk,
    )


@pytest.fixture
def cash(accountant):
    return banking.create_account(
        accountant,
        code="cash",
        kind="cash",
        name="Cash on hand",
        ledger_account=Account.objects.get(number="1010").pk,
    )


@pytest.fixture
def quotation(executive, director, unilever):
    """An IM quotation approved by the Director."""
    q = services.save(
        executive,
        None,
        customer=unilever,
        division=Division.objects.get(code="IM"),
        lines=[LineInput(description="Caps", quantity="10000", unit_price="15")],
    )
    workflow.submit(executive, q)
    return workflow.approve(director, q)


def receive(user, customer, account, **extra):
    return advances.record(
        user,
        **{
            "customer": customer,
            "account": account,
            "method": "transfer",
            "amount": "75000.00",
            "receipt_date": TODAY,
            "reference": "CEFT 88812",
        }
        | extra,
    )


@pytest.fixture
def received(cashier, unilever, bank, quotation):
    return receive(cashier, unilever, bank, quotation=quotation)


# --- Recording ------------------------------------------------------------------------


def test_the_cashier_records_an_advance_for_the_accountant(received, accountant, quotation):
    assert received.number == f"RC{TODAY:%y%m}0001"
    assert (received.status, received.division, received.quotation) == (
        S.AWAITING_APPROVAL,
        quotation.division,
        quotation,
    )
    assert received.amount_lkr == Decimal("75000.00") and received.journal_entry is None
    state = approvals.state_of("customer_advance", received.pk)
    assert [step["role"] for step in state.route] == ["accountant"]
    assert Notification.objects.filter(user=accountant, event="approval_waiting").exists()


def test_only_the_cashier_records_receipts(executive, accountant, unilever, bank):
    for user in (executive, accountant):
        with pytest.raises(SalesError, match="Only the Cashier"):
            receive(user, unilever, bank, division=Division.objects.get(code="WS"))
    assert ROLE_ACTIONS_V2 == {"cashier": ["record_receipt"]}
    holders = person("c2@sml.lk", "cashier")
    assert effective_access(holders).can("record_receipt")


@pytest.mark.parametrize(
    "change, why",
    [
        ({"amount": "0"}, "more than zero"),
        ({"amount": "10.005"}, "to the cent"),
        ({"receipt_date": TODAY + timedelta(days=1)}, "cannot be in the future"),
        ({"reference": ""}, "transfer, card or QR reference"),
        ({"method": "barter"}, "how the money was received"),
        ({"quotation": None}, "Choose the division"),
    ],
)
def test_wrong_receipts_are_refused(cashier, unilever, bank, quotation, change, why):
    with pytest.raises(SalesError, match=why):
        receive(cashier, unilever, bank, **({"quotation": quotation} | change))


def test_cash_goes_into_a_cash_account(cashier, unilever, bank, cash):
    ws = Division.objects.get(code="WS")
    with pytest.raises(SalesError, match="Cash is received into a cash account"):
        receive(cashier, unilever, bank, method="cash", division=ws)
    with pytest.raises(SalesError, match="goes into a bank account"):
        receive(cashier, unilever, cash, division=ws)
    taken = receive(cashier, unilever, cash, method="cash", reference="", division=ws)
    assert taken.method == "cash"


def test_the_quotation_must_be_the_customers_and_approved(
    cashier, executive, unilever, bank, quotation
):
    other = customers.create_customer(executive, {"name": "Nestle Lanka"})
    with pytest.raises(SalesError, match="for another customer"):
        receive(cashier, other, bank, quotation=quotation)
    draft = services.save(
        executive,
        None,
        customer=unilever,
        division=Division.objects.get(code="WS"),
        lines=[LineInput(description="Shaft", quantity="1", unit_price="100")],
    )
    with pytest.raises(SalesError, match="against an approved quotation"):
        receive(cashier, unilever, bank, quotation=draft)


def test_a_foreign_currency_advance_carries_its_rate(cashier, accountant, unilever):
    euro = Currency.objects.get(code="EUR")
    currencies.set_rate(currency=euro, on_date=TODAY, rate="325.40")
    eur_bank = banking.create_account(
        accountant,
        code="com-eur",
        kind="current",
        name="Commercial Bank EUR",
        bank_name="Commercial Bank",
        account_number="1000999999",
        currency="EUR",
        ledger_account=ledger(accountant, "1040", "Commercial Bank EUR").pk,
    )
    taken = receive(
        cashier, unilever, eur_bank, amount="1000.00", division=Division.objects.get(code="IM")
    )
    assert (taken.currency.code, taken.exchange_rate) == ("EUR", Decimal("325.400000"))
    assert taken.amount_lkr == Decimal("325400.00")


# --- Approval by the Accountant and the journal -----------------------------------------


def test_the_accountants_approval_posts_the_entry(received, accountant, bank):
    advance = advances.approve(accountant, received, "Seen on the bank statement")
    assert advance.status == S.APPROVED and advance.approved_at is not None
    entry = advance.journal_entry
    lines = {(line.account.number, line.debit, line.credit) for line in entry.lines.all()}
    assert lines == {
        ("1030", Decimal("75000.00"), Decimal("0.00")),
        ("2180", Decimal("0.00"), Decimal("75000.00")),  # Customer advances, a liability
    }
    assert entry.entry_date == TODAY and entry.source_type == "customer_advance"
    assert advances.balance_lkr(advance) == Decimal("75000.00")


def test_a_rejected_receipt_posts_nothing(received, accountant):
    with pytest.raises(SalesError, match="Give a reason"):
        advances.reject(accountant, received, "")
    advance = advances.reject(accountant, received, "Not on the bank statement")
    assert (advance.status, advance.journal_entry) == (S.REJECTED, None)
    with pytest.raises(SalesError, match="not waiting for approval"):
        advances.approve(accountant, advance)


def test_only_the_accountant_approves_and_never_their_own(received, director, unilever, bank):
    with pytest.raises(SalesError, match="approved by the Accountant"):
        advances.approve(director, received)
    both = person("both@sml.lk", "cashier", "accountant", all_divisions=True)
    own = receive(both, unilever, bank, division=Division.objects.get(code="WS"))
    assert not advances.can_approve(both, own)
    with pytest.raises(SalesError, match="cannot approve a document you created"):
        advances.approve(both, own)


def test_a_posted_advance_never_changes(received, accountant):
    advance = advances.approve(accountant, received)
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        CustomerAdvance.objects.filter(pk=advance.pk).update(amount=Decimal("1.00"))
    with pytest.raises(DatabaseError, match="cannot be deleted"), transaction.atomic():
        CustomerAdvance.objects.filter(pk=advance.pk).delete()
    # Only the set-off moves on (Phase 2), never above the amount.
    CustomerAdvance.objects.filter(pk=advance.pk).update(set_off_lkr=Decimal("25000.00"))
    advance.refresh_from_db()
    assert advances.balance_lkr(advance) == Decimal("50000.00")


# --- Through the API ------------------------------------------------------------------


def test_the_api_records_approves_and_prints(
    cashier, accountant, director, unilever, bank, quotation
):
    desk = as_user(cashier)
    options = desk.get("/api/v1/advances/options/").json()
    assert options["can_record"] is True
    customer = next(c for c in options["customers"] if c["id"] == unilever.pk)
    assert [q["label"] for q in customer["quotations"]] == [quotation.label]
    assert [a["code"] for a in options["accounts"]] == ["COM-CUR"]
    made = desk.post(
        "/api/v1/advances/",
        {
            "customer": unilever.pk,
            "quotation": quotation.pk,
            "account": bank.pk,
            "method": "cheque",
            "amount": "50000.00",
            "receipt_date": str(TODAY),
            "reference": "HNB 004512",
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    advance = made.json()
    assert advance["status"] == "awaiting_approval" and advance["can_approve"] is False

    books = as_user(accountant)
    waiting = books.get("/api/v1/advances/?waiting=me").json()
    assert [row["id"] for row in waiting] == [advance["id"]]
    url = f"/api/v1/advances/{advance['id']}/"
    assert as_user(director).post(f"{url}approve/", {}, format="json").status_code == 400
    done = books.post(f"{url}approve/", {"comment": "OK"}, format="json").json()
    assert done["status"] == "approved" and done["journal_entry"]["number"]
    assert [h["action"] for h in done["history"]] == ["submit", "approve"]
    pdf = desk.get(f"{url}receipt/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_sales_staff_do_not_reach_the_cashiers_pages(executive):
    assert as_user(executive).get("/api/v1/advances/").status_code == 403
    assert as_user(executive).post("/api/v1/advances/", {}, format="json").status_code == 403
