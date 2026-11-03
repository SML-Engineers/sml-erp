# ruff: noqa: F811 - the fixtures of test_payments are imported and used by name
"""Payment follow-ups (backlog P2-11): cancelling a payment with the Director's approval (the
reversing entry, the cheque spoiled, the voucher open to pay again), and payments in the
supplier's currency with the realised exchange difference (IAS 21)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting.models import Account, DetailType
from apps.core.models import Notification
from apps.masters import banking, currencies
from apps.masters.models import ChequeLeaf, Currency, Supplier
from apps.payments import cancellations, services
from apps.payments.models import PaymentCancellation, SupplierPayment
from apps.payments.services import PaymentError
from apps.vouchers import services as vouchers
from apps.vouchers.models import Voucher

from . import test_invoice_vouchers as po
from .test_access import as_user
from .test_payments import (  # noqa: F401 - fixtures used by name
    accountant,
    bank,
    cashier,
    clerk,
    director,
    entry_lines,
    fresh,
    memory_storage,
    pay,
    voucher,
)

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()
D = Decimal


def cancel(cashier, director, payment, reason="Cheque written for the wrong amount"):
    request = cancellations.request(cashier, payment, reason)
    return cancellations.approve(director, request, "OK")


# --- Cancelling a payment --------------------------------------------------------------------


def test_a_cancelled_cheque_payment_is_reversed_and_the_voucher_paid_again(
    cashier,
    director,
    bank,
    voucher,
):
    payment = pay(cashier, voucher, bank, "1000.00")  # cheque 000100
    request = cancellations.request(cashier, payment, "Cheque torn while printing")
    payment.refresh_from_db()
    assert (request.status, payment.cancelled, fresh(voucher).status) == ("pending", False, "paid")
    assert Notification.objects.filter(user=director, event="approval_waiting").exists()

    done = cancellations.approve(director, request, "OK")
    payment.refresh_from_db()
    assert (done.status, payment.cancelled) == ("approved", True)
    reversal = done.reversal_entry
    assert (reversal.reversal_of, reversal.entry_date) == (payment.journal_entry, TODAY)
    assert sorted((x.account.number, x.debit, x.credit) for x in reversal.lines.all()) == [
        ("1030", D("1000.00"), 0),
        ("6210", 0, D("400.00")),
        ("6210", 0, D("600.00")),
    ]
    leaf = ChequeLeaf.objects.get(number=100)
    assert leaf.status == "spoiled" and "Cheque torn" in leaf.reason
    assert (fresh(voucher).status, services.paid_on(voucher)) == ("director_approved", 0)
    again = pay(cashier, voucher, bank, "1000.00")  # the next cheque, 000101
    assert (again.reference, fresh(voucher).status) == ("000101", "paid")


def test_cancelling_one_of_two_payments_leaves_the_voucher_part_paid(
    cashier,
    director,
    bank,
    voucher,
):
    pay(cashier, voucher, bank, "400.00")
    second = pay(cashier, voucher, bank, "600.00")
    cancel(cashier, director, second)
    assert (fresh(voucher).status, services.paid_on(voucher)) == ("partly_paid", D("400.00"))


def test_who_asks_and_who_decides(clerk, accountant, cashier, director, bank, voucher):
    payment = pay(cashier, voucher, bank, "1000.00")
    with pytest.raises(PaymentError, match="Cashier or the Accountant"):
        cancellations.request(clerk, payment, "x")
    with pytest.raises(PaymentError, match="reason"):
        cancellations.request(accountant, payment, " ")
    request = cancellations.request(accountant, payment, "Transfer bounced")
    with pytest.raises(PaymentError, match="already waiting"):
        cancellations.request(cashier, payment, "again")
    for nobody in (cashier, accountant):
        assert not cancellations.can_decide(nobody, request)
        with pytest.raises(PaymentError):
            cancellations.approve(nobody, request)
    rejected = cancellations.reject(director, request, "The cheque was presented already")
    payment.refresh_from_db()
    assert (rejected.status, payment.cancelled, fresh(voucher).status) == (
        "rejected",
        False,
        "paid",
    )
    assert cancellations.request(cashier, payment, "Asked again with the bank's letter")


def test_the_database_cancels_a_payment_only_with_an_approved_request(
    cashier,
    director,
    bank,
    voucher,
):
    payment = pay(cashier, voucher, bank, "1000.00")
    with (
        pytest.raises(DatabaseError, match="only once the Director approves"),
        transaction.atomic(),
    ):
        SupplierPayment.objects.filter(pk=payment.pk).update(cancelled=True)
    with pytest.raises(DatabaseError), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(status="director_approved")  # paid: locked
    with pytest.raises(DatabaseError), transaction.atomic():
        ChequeLeaf.objects.filter(pk=payment.cheque_id).update(status="spoiled")
    done = cancel(cashier, director, payment)
    with pytest.raises(DatabaseError), transaction.atomic():
        SupplierPayment.objects.filter(pk=payment.pk).update(amount=D("1.00"))
    with pytest.raises(DatabaseError), transaction.atomic():
        SupplierPayment.objects.filter(pk=payment.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        PaymentCancellation.objects.filter(pk=done.pk).update(reason="changed")
    with pytest.raises(DatabaseError), transaction.atomic():
        PaymentCancellation.objects.filter(pk=done.pk).delete()
    with pytest.raises(PaymentError, match="already cancelled"):
        cancellations.request(cashier, payment, "twice")


def test_the_screens_api(cashier, director, bank, voucher):
    payment = pay(cashier, voucher, bank, "1000.00")
    till = as_user(cashier)
    row = till.get(f"/api/v1/payments/?voucher={voucher.pk}").json()[0]
    assert (row["can_cancel"], row["currency"], row["paid_amount"]) == (True, "LKR", "1000.00")
    asked = till.post(
        f"/api/v1/payments/{payment.pk}/cancel/", {"reason": "Cheque lost"}, format="json"
    )
    assert asked.status_code == 200 and asked.json()["cancellation"]["status"] == "pending"
    assert asked.json()["can_cancel"] is False
    boss = as_user(director)
    detail = boss.get(f"/api/v1/vouchers/{voucher.pk}/").json()
    pending = detail["payments"][0]["cancellation"]
    assert pending["can_decide"] is True
    done = boss.post(f"/api/v1/payment-cancellations/{pending['id']}/approve/", {}, format="json")
    assert done.status_code == 200 and done.json()["cancelled"] is True
    assert done.json()["cancellation"]["reversal_entry"]


# --- Paying in the supplier's currency -----------------------------------------------------------


def usd():
    return Currency.objects.get(code="USD")


@pytest.fixture
def usd_bank(accountant):
    account = banking.create_account(
        accountant,
        code="com-usd",
        kind="current",
        name="Commercial Bank USD",
        bank_name="Commercial Bank",
        account_number="1000999999",
        currency="USD",
        ledger_account=chart.create_account(
            accountant,
            name="Commercial Bank USD",
            account_type="bank",
            detail_type=DetailType.objects.get(name="Current account"),
            number="1040",
        ).pk,
    )
    banking.add_cheque_book(accountant, account, first=500, last=510)
    return account


@pytest.fixture
def usd_voucher(clerk, accountant, director):
    """A USD supplier's invoice, 1,000 x USD 12.50 = USD 12,500.00 booked at 300.00 (LKR
    3,750,000.00), on a voucher approved by the Director. Today the rate is 310.00."""
    currencies.set_rate(currency=usd(), on_date=TODAY - timedelta(days=30), rate="300.00")
    seller = Supplier.objects.create(
        code="S0050", name="Shenzhen Moulds Co", currency=usd(), payment_terms_days=30
    )
    invoice = po.posted_invoice(clerk, director, seller, no="SZ-001")
    assert (invoice.total_amount, invoice.total_lkr) == (D("12500.00"), D("3750000.00"))
    currencies.set_rate(currency=usd(), on_date=TODAY, rate="310.00")
    v = po.voucher_for(clerk, seller, po.pays(invoice, "3750000.00"))
    vouchers.submit(clerk, v)
    vouchers.approve(accountant, v, "checked")
    return vouchers.approve(director, Voucher.objects.get(pk=v.pk))


def ap():
    return Account.objects.get(system_role="accounts_payable").number


def loss():
    return Account.objects.get(system_role="exchange_loss").number


def test_paying_dollars_at_a_higher_rate_posts_an_exchange_loss(cashier, usd_bank, usd_voucher):
    assert services.foreign_basis(usd_voucher) == (usd(), D("12500.00"))
    first = pay(cashier, usd_voucher, usd_bank, "5000.00")
    assert (first.amount, first.currency.code, first.paid_amount, first.exchange_rate) == (
        D("1500000.00"),
        "USD",
        D("5000.00"),
        D("310.000000"),
    )
    assert entry_lines(first) == [
        ("1040", None, 0, D("1550000.00")),
        (ap(), "IM", D("1500000.00"), 0),
        (loss(), "IM", D("50000.00"), 0),
    ]
    assert services.foreign_left(fresh(usd_voucher), D("12500.00")) == D("7500.00")
    with pytest.raises(PaymentError, match="Only USD 7,500.00"):
        pay(cashier, usd_voucher, usd_bank, "7500.01")
    last = pay(cashier, usd_voucher, usd_bank, "7500.00")
    assert last.amount == D("2250000.00")  # exactly what was left in LKR
    assert fresh(usd_voucher).status == "paid"


def test_only_a_voucher_of_dollar_invoices_is_paid_in_dollars(cashier, usd_bank, voucher):
    with pytest.raises(PaymentError, match="is paid from an LKR account"):
        pay(cashier, voucher, usd_bank, "10.00")


def test_a_dollar_payment_is_cancelled_with_its_exchange_difference(
    cashier, director, usd_bank, usd_voucher
):
    payment = pay(cashier, usd_voucher, usd_bank, "12500.00")
    done = cancel(cashier, director, payment)
    assert sorted(
        (x.account.number, x.debit, x.credit) for x in done.reversal_entry.lines.all()
    ) == [
        ("1040", D("3875000.00"), 0),
        (ap(), 0, D("3750000.00")),
        (loss(), 0, D("125000.00")),
    ]
    assert fresh(usd_voucher).status == "director_approved"
