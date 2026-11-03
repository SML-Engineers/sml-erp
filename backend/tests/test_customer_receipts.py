"""Customer receipts and advance set-off (backlog P2-07, spec 5.2, 6; rules 1, 2, 3, 5, 8,
10)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting import sources, taxes
from apps.accounting.models import Account, DetailType, TaxCode, TaxComponent
from apps.core import approvals
from apps.core.models import AccessOverride, Company, Division, Notification, User
from apps.masters import banking
from apps.sales import advances, invoices, receipt, receipts
from apps.sales.models import (
    AdvanceSetOff,
    CustomerAdvance,
    CustomerReceipt,
    ReceiptAllocation,
)
from apps.sales.receipts import Allocation
from apps.sales.services import LineInput as QuoteLine
from apps.sales.services import SalesError

from . import test_tax_invoices as base
from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
D = Decimal
S = CustomerReceipt.Status
NUMBER = f"RC{TODAY:%y%m}"


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
def stores():
    return person("stores@sml.lk", "store_supervisor", all_divisions=True)


@pytest.fixture(autouse=True)
def setup(accountant):
    for code, rate in (("SSCL", "2.125"), ("VAT", "18")):
        component = TaxComponent.objects.get(code=code)
        taxes.add_rate(accountant, component, effective_from=base.GO_LIVE, rate=rate)
    Company.objects.filter(pk=1).update(name="SML Engineers (Pvt) Ltd", tin="134567890")
    Division.objects.filter(code="WS").update(tax_invoice_code="W1")


@pytest.fixture
def bank(accountant):
    return banking.create_account(
        accountant,
        code="com-cur",
        kind="current",
        name="Commercial Bank current",
        bank_name="Commercial Bank",
        account_number="1000234567",
        ledger_account=chart.create_account(
            accountant,
            name="Commercial Bank current",
            account_type="bank",
            detail_type=DetailType.objects.get(name="Current account"),
            number="1030",
        ).pk,
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


def shafts(executive, director):
    """50 shafts at 2,315.00 (the spec's example: 139,487.43 with SSCL and VAT)."""
    return base.make_order(
        executive,
        director,
        QuoteLine(
            description="Drive shaft, EN8",
            drawing_no="DS-114",
            quantity="50",
            unit_price="2315.00",
            tax_code=TaxCode.objects.get(code="VAT-SSCL"),
        ),
    )


@pytest.fixture
def order(executive, director):
    return shafts(executive, director)


@pytest.fixture
def two(order, stores, accountant):
    """Two issued invoices of one customer: 20 shafts, then 30."""
    first = base.deliver(stores, order, "20")
    base.deliver(stores, order, "30")
    one = invoices.issue(accountant, invoices.create(accountant, order, [first]))
    other = invoices.issue(accountant, invoices.create(accountant, order))
    return one, other


def pay(cashier, account, *parts, method="transfer", **extra):
    total = sum((D(amount) for _, amount in parts), D("0"))
    return receipts.record(
        cashier,
        **{
            "customer": parts[0][0].customer,
            "method": method,
            "account": account,
            "amount": f"{total:.2f}",
            "receipt_date": TODAY,
            "reference": "CEFT 99120",
            "allocations": [Allocation(invoice, amount) for invoice, amount in parts],
        }
        | extra,
    )


def lines(entry):
    return [
        (
            x.account.number,
            x.debit,
            x.credit,
            x.division.code if x.division else None,
            x.customer_id,
        )
        for x in entry.lines.order_by("line_no")
    ]


def acc(number):
    return Account.objects.get(number=number)


# --- Recording and approval ------------------------------------------------------------


def test_the_cashier_splits_a_transfer_across_two_invoices(two, cashier, accountant, bank):
    one, other = two
    made = pay(cashier, bank, (one, one.total_amount), (other, "50000.00"))
    assert made.number == f"{NUMBER}0001"
    assert (made.status, made.journal_entry, made.amount) == (
        S.AWAITING_APPROVAL,
        None,
        one.total_amount + D("50000.00"),
    )
    assert [(a.invoice, a.amount) for a in made.allocations.all()] == [
        (one, one.total_amount),
        (other, D("50000.00")),
    ]
    state = approvals.state_of("customer_receipt", made.pk)
    assert [step["role"] for step in state.route] == ["accountant"]
    assert Notification.objects.filter(user=accountant, event="approval_waiting").exists()
    # Waiting for approval, the money is already counted against the invoices.
    figures = receipts.settlement([one, other])
    assert (figures[one.pk]["pending"], figures[one.pk]["open"]) == (one.total_amount, 0)
    assert figures[other.pk]["open"] == other.total_amount - D("50000.00")


def test_approval_posts_bank_against_receivables_per_invoice(two, cashier, accountant, bank):
    one, other = two
    made = pay(cashier, bank, (one, one.total_amount), (other, "50000.00"))
    made = receipts.approve(accountant, made, "In the bank")
    assert made.status == S.POSTED and made.approved_by == accountant
    entry = made.journal_entry
    assert (entry.source_type, entry.source_id, entry.entry_date) == (
        "customer_receipt",
        made.number,
        TODAY,
    )
    customer = one.customer_id
    assert lines(entry) == [
        ("1030", made.amount, 0, "WS", None),
        ("1100", 0, one.total_amount, "WS", customer),
        ("1100", 0, D("50000.00"), "WS", customer),
    ]
    figures = receipts.settlement([one, other])
    assert (figures[one.pk]["received"], figures[one.pk]["open"]) == (one.total_amount, 0)
    assert receipts.open_invoices(accountant, one.customer) == [
        (other, figures[other.pk]),
    ]
    assert sources.paths([("customer_receipt", made.number)]) == {
        ("customer_receipt", made.number): f"/receipts/{made.pk}"
    }


def test_cash_goes_into_a_cash_account(two, cashier, accountant, cash, bank):
    one, _ = two
    with pytest.raises(SalesError, match="Cash is received into a cash account"):
        pay(cashier, bank, (one, "1000.00"), method="cash", reference="")
    made = receipts.approve(
        accountant, pay(cashier, cash, (one, "1000.00"), method="cash", reference="")
    )
    assert lines(made.journal_entry)[0][:2] == ("1010", D("1000.00"))


def test_a_cheque_waits_in_undeposited_funds(two, cashier, accountant, bank):
    one, _ = two
    made = pay(
        cashier,
        bank,
        (one, "20000.00"),
        method="cheque",
        reference="004512",
        cheque_bank="Sampath Bank",
    )
    assert (made.account, made.cheque_date) == (None, TODAY)  # no account for a cheque
    made = receipts.approve(accountant, made)
    assert lines(made.journal_entry) == [
        ("1300", D("20000.00"), 0, "WS", None),
        ("1100", 0, D("20000.00"), "WS", one.customer_id),
    ]


def test_a_post_dated_cheque_is_posted_on_its_date(two, cashier, accountant, bank):
    one, _ = two
    due = TODAY + timedelta(days=10)
    made = pay(
        cashier, None, (one, "30000.00"), method="cheque", reference="004513", cheque_date=due
    )
    made = receipts.approve(accountant, made)
    assert (made.status, made.journal_entry) == (S.POST_DATED, None)
    assert receipts.settlement([one])[one.pk]["pending"] == D("30000.00")  # still reserved
    assert receipts.post_due(TODAY) == 0
    assert receipts.post_due(due) == 1
    made.refresh_from_db()
    assert made.status == S.POSTED
    assert (made.journal_entry.entry_date, made.journal_entry.posted_by) == (due, accountant)
    assert receipts.post_due(due) == 0  # only once


def test_cheque_dates(two, cashier):
    one, _ = two
    with pytest.raises(SalesError, match="more than six months ahead"):
        pay(cashier, None, (one, "1.00"), method="cheque", cheque_date=TODAY + timedelta(200))
    with pytest.raises(SalesError, match="more than six months old"):
        pay(cashier, None, (one, "1.00"), method="cheque", cheque_date=TODAY - timedelta(200))


def test_never_more_than_is_open_on_an_invoice(two, cashier, accountant, bank, executive, director):
    one, other = two
    with pytest.raises(SalesError, match=f"Invoice {one.number} has only"):
        pay(cashier, bank, (one, one.total_amount + D("0.01")))
    first = pay(cashier, bank, (one, "40000.00"))
    with pytest.raises(SalesError, match=f"has only {one.total_amount - D('40000'):,.2f} open"):
        pay(cashier, bank, (one, "40000.00"))  # the first receipt is counted while it waits
    receipts.reject(accountant, first, "Not in the bank statement")
    assert pay(cashier, bank, (one, "40000.00")).status == S.AWAITING_APPROVAL  # open again
    stranger = shafts(executive, director)  # another customer's order
    with pytest.raises(SalesError, match="is for another customer"):
        receipts.record(
            cashier,
            customer=stranger.customer,
            method="transfer",
            account=bank,
            amount="10.00",
            receipt_date=TODAY,
            reference="X",
            allocations=[Allocation(other, "10.00")],
        )


def test_the_split_adds_up_to_the_amount(two, cashier, bank):
    one, other = two
    with pytest.raises(SalesError, match="add up to 300.00, not the 500.00 received"):
        receipts.record(
            cashier,
            customer=one.customer,
            method="transfer",
            account=bank,
            amount="500.00",
            receipt_date=TODAY,
            reference="CEFT 1",
            allocations=[Allocation(one, "100.00"), Allocation(other, "200.00")],
        )
    with pytest.raises(SalesError, match="chosen twice"):
        pay(cashier, bank, (one, "100.00"), (one, "100.00"))
    with pytest.raises(SalesError, match="Choose the invoices"):
        receipts.record(
            cashier,
            customer=one.customer,
            method="transfer",
            account=bank,
            amount="500.00",
            receipt_date=TODAY,
            reference="CEFT 1",
            allocations=[],
        )
    with pytest.raises(SalesError, match="cannot be in the future"):
        pay(cashier, bank, (one, "1.00"), receipt_date=TODAY + timedelta(days=1))
    with pytest.raises(SalesError, match="transfer, card or QR reference"):
        pay(cashier, bank, (one, "1.00"), reference="")


def test_only_issued_invoices_are_paid(order, stores, accountant, cashier, bank):
    base.deliver(stores, order, "10")
    draft = invoices.create(accountant, order)
    with pytest.raises(SalesError, match="Only issued invoices"):
        pay(cashier, bank, (draft, "1.00"))


def test_only_the_cashier_records_and_only_the_accountant_approves(
    two, cashier, accountant, director, executive, bank
):
    one, _ = two
    for nobody in (accountant, executive):
        with pytest.raises(SalesError, match="Only the Cashier"):
            pay(nobody, bank, (one, "1.00"))
    made = pay(cashier, bank, (one, "1.00"))
    for nobody in (cashier, executive):
        assert not receipts.can_approve(nobody, made)
        with pytest.raises(SalesError):
            receipts.approve(nobody, made)
    assert receipts.can_approve(accountant, made)
    with pytest.raises(SalesError, match="reason"):
        receipts.reject(accountant, made, "")
    receipts.reject(accountant, made, "Bounced")
    with pytest.raises(SalesError, match="not waiting"):
        receipts.approve(accountant, made)


# --- Database guards ------------------------------------------------------------


def test_the_database_keeps_receipts_as_recorded(two, cashier, accountant, bank):
    one, other = two
    made = receipts.approve(accountant, pay(cashier, bank, (one, "1000.00")))
    for change in (
        {"amount": D("2000.00")},
        {"reference": "CEFT 00000"},
        {"status": S.REJECTED},
        {"journal_entry": None},
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            CustomerReceipt.objects.filter(pk=made.pk).update(**change)
    with pytest.raises(DatabaseError), transaction.atomic():
        CustomerReceipt.objects.filter(pk=made.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        ReceiptAllocation.objects.filter(receipt=made).update(amount=D("5.00"))
    with pytest.raises(DatabaseError), transaction.atomic():
        ReceiptAllocation.objects.filter(receipt=made).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        ReceiptAllocation.objects.create(receipt=made, invoice=other, amount=D("1.00"))


def test_the_database_refuses_paying_more_than_is_open(two, cashier, bank):
    one, other = two
    waiting = pay(cashier, bank, (one, "1000.00"))
    with pytest.raises(DatabaseError, match="pays more than is open"), transaction.atomic():
        ReceiptAllocation.objects.create(
            receipt=waiting, invoice=other, amount=other.total_amount + D("0.01")
        )
    ReceiptAllocation.objects.create(receipt=waiting, invoice=other, amount=other.total_amount)


# --- Advances set off ------------------------------------------------------------


def advance(cashier, accountant, customer, account, amount, **against):
    made = advances.record(
        cashier,
        customer=customer,
        account=account,
        method="transfer",
        amount=amount,
        receipt_date=TODAY,
        reference="CEFT 70001",
        **against,
    )
    return advances.approve(accountant, made)


def test_issuing_the_invoice_sets_off_the_order_s_advance(order, stores, accountant, cashier, bank):
    paid = advance(cashier, accountant, order.customer, bank, "50000.00", sales_order=order)
    base.deliver(stores, order, "50")
    invoice = invoices.issue(accountant, invoices.create(accountant, order))
    set_off = AdvanceSetOff.objects.get(advance=paid)
    assert (set_off.invoice, set_off.amount, set_off.set_off_date) == (
        invoice,
        D("50000.00"),
        TODAY,
    )
    paid.refresh_from_db()
    assert (paid.set_off_lkr, advances.balance_lkr(paid)) == (D("50000.00"), 0)
    assert lines(set_off.journal_entry) == [
        ("2180", D("50000.00"), 0, "WS", None),
        ("1100", 0, D("50000.00"), "WS", invoice.customer_id),
    ]
    assert set_off.journal_entry.source_type == "customer_set_off"
    figures = receipts.settlement([invoice])[invoice.pk]
    assert (figures["set_off"], figures["open"]) == (
        D("50000.00"),
        D("139487.43") - D("50000.00"),
    )


def test_an_advance_larger_than_the_invoice_keeps_the_rest(
    order, stores, accountant, cashier, bank
):
    paid = advance(cashier, accountant, order.customer, bank, "200000.00", sales_order=order)
    base.deliver(stores, order, "50")
    invoice = invoices.issue(accountant, invoices.create(accountant, order))
    paid.refresh_from_db()
    assert paid.set_off_lkr == D("139487.43")
    assert advances.balance_lkr(paid) == D("200000.00") - D("139487.43")
    assert receipts.open_amount(invoice) == 0


def test_the_accountant_sets_off_an_advance_by_hand(two, accountant, cashier, bank):
    one, _ = two
    ws = Division.objects.get(code="WS")
    paid = advance(cashier, accountant, one.customer, bank, "25000.00", division=ws)
    assert not AdvanceSetOff.objects.exists()  # not for this order: nothing automatic
    with pytest.raises(SalesError, match="Only the Accountant"):
        receipts.set_off(cashier, paid, one, "1000.00")
    with pytest.raises(SalesError, match="has only 25,000.00 left"):
        receipts.set_off(accountant, paid, one, "25000.01")
    receipts.set_off(accountant, paid, one, "10000.00")
    paid.refresh_from_db()
    assert advances.balance_lkr(paid) == D("15000.00")
    assert receipts.settlement([one])[one.pk]["set_off"] == D("10000.00")


def test_the_database_refuses_setting_off_more_than_the_advance(two, accountant, cashier, bank):
    one, _ = two
    ws = Division.objects.get(code="WS")
    paid = advance(cashier, accountant, one.customer, bank, "500.00", division=ws)
    with pytest.raises(DatabaseError), transaction.atomic():
        AdvanceSetOff.objects.create(
            advance=paid,
            invoice=one,
            amount=D("500.01"),
            set_off_date=TODAY,
            journal_entry=one.journal_entry,
            created_by=accountant,
        )
    made = receipts.set_off(accountant, paid, one, "500.00")
    with pytest.raises(DatabaseError), transaction.atomic():
        AdvanceSetOff.objects.filter(pk=made.pk).update(amount=D("1.00"))
    with pytest.raises(DatabaseError), transaction.atomic():
        AdvanceSetOff.objects.filter(pk=made.pk).delete()
    assert CustomerAdvance.objects.get(pk=paid.pk).set_off_lkr == D("500.00")


# --- API and printing ------------------------------------------------------------


def test_the_cashier_records_through_the_api(two, cashier, accountant, executive, bank):
    one, other = two
    client = as_user(cashier)
    options = client.get("/api/v1/receipts/options/").json()
    assert options["can_record"] is True
    (customer,) = options["customers"]
    assert [i["number"] for i in customer["invoices"]] == [one.number, other.number]
    assert customer["invoices"][0]["open_amount"] == f"{one.total_amount:.2f}"
    made = client.post(
        "/api/v1/receipts/",
        {
            "customer": one.customer_id,
            "method": "transfer",
            "account": bank.pk,
            "amount": "1500.00",
            "receipt_date": TODAY.isoformat(),
            "reference": "CEFT 1",
            "allocations": [{"invoice": one.pk, "amount": "1500.00"}],
        },
        format="json",
    )
    assert made.status_code == 201, made.json()
    pk = made.json()["id"]
    too_much = client.post(
        "/api/v1/receipts/",
        {
            "customer": one.customer_id,
            "method": "transfer",
            "account": bank.pk,
            "amount": "1.00",
            "receipt_date": TODAY.isoformat(),
            "reference": "CEFT 2",
            "allocations": [{"invoice": one.pk, "amount": "2.00"}],
        },
        format="json",
    )
    assert too_much.status_code == 400 and "add up to" in too_much.json()["detail"]
    assert as_user(executive).get("/api/v1/receipts/").status_code == 403
    staff = as_user(accountant)
    assert staff.get(f"/api/v1/receipts/{pk}/").json()["can_approve"] is True
    done = staff.post(f"/api/v1/receipts/{pk}/approve/", {"comment": ""}, format="json")
    assert done.status_code == 200 and done.json()["status"] == "posted"
    detail = staff.get(f"/api/v1/tax-invoices/{one.pk}/").json()
    assert detail["settlement"]["received"] == "1500.00"
    assert detail["receipts"][0]["number"] == made.json()["number"]
    pdf = client.get(f"/api/v1/receipts/{pk}/pdf/")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_the_accountant_sets_off_through_the_api(two, accountant, cashier, bank):
    one, _ = two
    ws = Division.objects.get(code="WS")
    paid = advance(cashier, accountant, one.customer, bank, "800.00", division=ws)
    staff = as_user(accountant)
    detail = staff.get(f"/api/v1/advances/{paid.pk}/").json()
    assert detail["can_set_off"] is True
    assert one.number in [i["number"] for i in detail["open_invoices"]]
    done = staff.post(
        f"/api/v1/advances/{paid.pk}/set-off/",
        {"invoice": one.pk, "amount": "800.00"},
        format="json",
    )
    assert done.status_code == 200, done.json()
    assert done.json()["balance_lkr"] == "0.00"
    assert done.json()["set_offs"][0]["invoice"]["number"] == one.number
    refused = as_user(cashier).post(
        f"/api/v1/advances/{paid.pk}/set-off/",
        {"invoice": one.pk, "amount": "1.00"},
        format="json",
    )
    assert refused.status_code == 403


def test_the_printed_receipt_lists_the_invoices(two, cashier, bank):
    one, other = two
    made = pay(
        cashier,
        None,
        (one, "100.00"),
        (other, "200.00"),
        method="cheque",
        reference="004514",
        cheque_date=TODAY + timedelta(days=5),
    )
    pdf = receipt.render_receipt(made)
    assert pdf.startswith(b"%PDF")


# --- Owner's answers of 3 Nov 2026 ----------------------------------------------------


def grant(user, director, confirmed=True):
    """The Admin gives "approve_customer_receipts" to someone; the Director confirms it."""
    AccessOverride.objects.create(
        user=user,
        action="approve_customer_receipts",
        effect=AccessOverride.Effect.GRANT,
        reason="Approves receipts while the Accountant is on leave",
        is_sensitive=True,
        created_by=person("admin@sml.lk", "system_admin", all_divisions=True),
        confirmed_by=director if confirmed else None,
        confirmed_at=timezone.now() if confirmed else None,
    )
    return User.objects.get(pk=user.pk)  # access is worked out once per request


def test_a_person_the_admin_chooses_approves_receipts_and_advances(
    two, cashier, accountant, director, bank
):
    one, _ = two
    chief = person("chief@sml.lk", "clerk", all_divisions=True)
    made = pay(cashier, bank, (one, "1000.00"))
    assert not receipts.can_approve(chief, made)
    chief = grant(chief, director, confirmed=False)
    assert not receipts.can_approve(chief, made)  # not until the Director confirms
    AccessOverride.objects.filter(user=chief).update(
        confirmed_by=director, confirmed_at=timezone.now()
    )
    chief = User.objects.get(pk=chief.pk)
    assert receipts.approve(chief, made).status == S.POSTED
    paid = advances.record(
        cashier,
        customer=one.customer,
        account=bank,
        method="transfer",
        amount="500.00",
        receipt_date=TODAY,
        reference="CEFT 7",
        division=Division.objects.get(code="WS"),
    )
    assert advances.approve(chief, paid).status == CustomerAdvance.Status.APPROVED


def test_nobody_approves_a_receipt_they_recorded_even_with_the_right(two, cashier, director, bank):
    one, _ = two
    cashier = grant(cashier, director)
    made = pay(cashier, bank, (one, "1000.00"))
    assert not receipts.can_approve(cashier, made)
    with pytest.raises(SalesError):
        receipts.approve(cashier, made)


def test_money_on_account_is_set_off_against_the_next_invoice(
    order, stores, accountant, cashier, bank
):
    """The order's own advance goes first, then the customer's money on account (e.g. what
    was paid over the invoices of a receipt), oldest first."""
    ws = Division.objects.get(code="WS")
    on_account = advance(cashier, accountant, order.customer, bank, "200000.00", division=ws)
    for_order = advance(cashier, accountant, order.customer, bank, "40000.00", sales_order=order)
    base.deliver(stores, order, "50")
    invoice = invoices.issue(accountant, invoices.create(accountant, order))
    assert [(s.advance, s.amount) for s in AdvanceSetOff.objects.order_by("id")] == [
        (for_order, D("40000.00")),
        (on_account, invoice.total_amount - D("40000.00")),
    ]
    assert receipts.open_amount(invoice) == 0
    on_account.refresh_from_db()
    assert advances.balance_lkr(on_account) == D("200000.00") - (
        invoice.total_amount - D("40000.00")
    )
