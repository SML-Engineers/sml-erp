"""Supplier payments and the payment lock (backlog P1-07, spec 4.4 and 4.6)."""

from datetime import date
from decimal import Decimal

import pytest
from django.db import connection, transaction
from django.db.models import Sum
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import journal, taxes
from apps.accounting import services as chart
from apps.accounting.models import Account, DetailType, JournalLine, TaxCode, TaxComponent
from apps.masters import banking
from apps.payments import services
from apps.payments.models import SupplierPayment
from apps.payments.services import PaymentError
from apps.vouchers import services as vouchers
from apps.vouchers.models import Voucher
from apps.vouchers.services import CodingInput, LineInput

from .test_access import as_user, person
from .test_voucher_amendments import approved
from .test_vouchers import attach, draft, payee, ws

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def cashier():
    return person("cashier@sml.lk", "cashier", all_divisions=True)


@pytest.fixture
def bank(accountant):
    """A current account with its ledger in the chart and a cheque book 100-150."""
    ledger = chart.create_account(
        accountant,
        name="Commercial Bank current",
        account_type="bank",
        detail_type=DetailType.objects.get(name="Current account"),
        number="1030",
    )
    account = banking.create_account(
        accountant,
        code="com-cur",
        kind="current",
        name="Commercial Bank current",
        bank_name="Commercial Bank",
        account_number="1000234567",
        ledger_account=ledger.pk,
    )
    banking.add_cheque_book(accountant, account, first=100, last=150)
    return account


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
def voucher(clerk, accountant, director):
    """Cheque Payment, LKR 1,000.00, coded to 6210 and split WS 600 / IM 400."""
    return approved(clerk, accountant, director)


def fresh(v):
    return Voucher.objects.get(pk=v.pk)


def pay(cashier, voucher, account, amount, method="cheque", **values):
    return services.record(
        cashier,
        fresh(voucher),
        account=account,
        method=method,
        amount=amount,
        payment_date=values.pop("payment_date", TODAY),
        **values,
    )


def entry_lines(payment):
    return sorted(
        (
            line.account.number,
            line.division.code if line.division else None,
            line.debit,
            line.credit,
        )
        for line in payment.journal_entry.lines.select_related("account", "division")
    )


# --- Paying ---------------------------------------------------------------------------


def test_a_full_payment_posts_a_balanced_entry_and_the_voucher_is_paid(cashier, bank, voucher):
    payment = pay(cashier, voucher, bank, "1000.00")
    assert payment.number.startswith(f"PY{TODAY:%y%m}")
    assert (payment.method, payment.reference) == ("cheque", "000100")
    assert payment.cheque.number == 100 and payment.cheque.status == "issued"
    assert entry_lines(payment) == [
        ("1030", None, Decimal("0.00"), Decimal("1000.00")),
        ("6210", "IM", Decimal("400.00"), Decimal("0.00")),
        ("6210", "WS", Decimal("600.00"), Decimal("0.00")),
    ]
    assert payment.journal_entry.source_type == "supplier_payment"
    assert fresh(voucher).status == "paid"
    with pytest.raises(PaymentError, match="paid"):
        pay(cashier, voucher, bank, "1.00")
    with pytest.raises(DatabaseError, match="paid and locked"), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(status="director_approved")


def test_part_payments_up_to_the_approved_amount(cashier, bank, voucher):
    first = pay(cashier, voucher, bank, "333.33")
    assert fresh(voucher).status == "partly_paid"
    assert services.remaining(fresh(voucher)) == Decimal("666.67")
    with pytest.raises(PaymentError, match="Only 666.67"):
        pay(cashier, voucher, bank, "666.68")
    with pytest.raises(PaymentError, match="already been used"):
        pay(cashier, voucher, bank, "10.00", cheque_number="100")  # a cheque number once only
    second = pay(cashier, voucher, bank, "666.67", cheque_date=date(2026, 12, 1))
    assert second.reference == "000101" and second.cheque_date == date(2026, 12, 1)
    assert fresh(voucher).status == "paid"
    # Together the two entries cover the voucher's coding exactly.
    totals = (
        JournalLine.objects.filter(entry__in=[first.journal_entry, second.journal_entry])
        .values_list("account__number", "division__code")
        .annotate(debit=Sum("debit"), credit=Sum("credit"))
    )
    assert sorted(totals) == [
        ("1030", None, Decimal("0.00"), Decimal("1000.00")),
        ("6210", "IM", Decimal("400.00"), Decimal("0.00")),
        ("6210", "WS", Decimal("600.00"), Decimal("0.00")),
    ]


def test_recoverable_vat_goes_to_vat_receivable(clerk, accountant, director, cashier, bank):
    vat = TaxComponent.objects.get(code="VAT")
    taxes.add_rate(accountant, vat, effective_from=date(2020, 1, 1), rate="18")
    v = draft(
        clerk,
        payee(code="S0005"),
        LineInput(amount="1000.00", invoice_no="T-1", tax_code=TaxCode.objects.get(code="VAT")),
        code="ONL",
    )
    attach(clerk, v, content=b"%PDF-1.7 vat")
    vouchers.submit(clerk, v)
    vouchers.code_lines(
        accountant,
        v,
        [
            CodingInput(
                line_no=1,
                account=Account.objects.get(number="6210"),
                division=ws(),
                tax_code=TaxCode.objects.get(code="VAT"),
            )
        ],
    )
    vouchers.approve(accountant, fresh(v))
    vouchers.approve(director, fresh(v))
    with pytest.raises(PaymentError, match="reference"):
        pay(cashier, v, bank, "590.00", method="transfer")
    half = pay(cashier, v, bank, "590.00", method="transfer", reference="CEFT 778812")
    assert entry_lines(half) == [
        ("1030", None, Decimal("0.00"), Decimal("590.00")),
        ("1340", None, Decimal("90.00"), Decimal("0.00")),
        ("6210", "WS", Decimal("500.00"), Decimal("0.00")),
    ]
    rest = pay(cashier, v, bank, "590.00", method="qr", reference="LQR-55")
    assert rest.get_method_display() == "QR code (LankaQR)"


# --- The payment lock -----------------------------------------------------------------


def test_only_approved_vouchers_are_paid(clerk, accountant, cashier, bank):
    v = draft(clerk, payee(code="S0007"), LineInput(amount="100.00"))
    attach(clerk, v, content=b"%PDF-1.7 seven")
    vouchers.submit(clerk, v)
    with pytest.raises(PaymentError, match="only a voucher approved by the Director"):
        pay(cashier, v, bank, "100.00")
    assert services.why_not_payable(fresh(v)) is not None
    assert not services.to_pay(cashier).filter(pk=v.pk).exists()


def raw_insert(voucher, account, amount, user):
    """A payment written straight into the database, past the service."""
    entry = journal.post(
        user,
        entry_date=TODAY,
        narration="test entry",
        lines=[
            journal.Line(account=Account.objects.get(number="1010"), debit="1.00"),
            journal.Line(account=Account.objects.get(number="1020"), credit="1.00"),
        ],
    )
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO payments_supplierpayment
              (number, voucher_id, account_id, method, reference, payment_date, amount, notes,
               journal_entry_id, cancelled, created_by_id, created_at, currency_id,
               paid_amount, exchange_rate)
            VALUES (%s, %s, %s, 'transfer', 'X', %s, %s, '', %s, false, %s, now(), %s, %s, 1)
            """,
            [
                f"RAW{entry.pk}",
                voucher.pk,
                account.pk,
                TODAY,
                amount,
                entry.pk,
                user.pk,
                account.currency_id,
                amount,
            ],
        )


def test_the_database_refuses_payment_of_an_unapproved_voucher(clerk, cashier, bank):
    v = draft(clerk, payee(code="S0008"), LineInput(amount="100.00"))
    with pytest.raises(DatabaseError, match="not approved by the Director"), transaction.atomic():
        raw_insert(v, bank, "100.00", cashier)


def test_the_database_refuses_paying_more_than_approved(cashier, bank, voucher):
    pay(cashier, voucher, bank, "900.00")
    with pytest.raises(DatabaseError, match="exceeds the approved amount"), transaction.atomic():
        raw_insert(voucher, bank, "100.01", cashier)
    raw_insert(voucher, bank, "100.00", cashier)  # exactly up to the approved amount is fine
    with pytest.raises(DatabaseError), transaction.atomic():
        SupplierPayment.objects.filter(voucher=voucher).update(amount=Decimal("1.00"))
    with pytest.raises(DatabaseError), transaction.atomic():
        SupplierPayment.objects.filter(voucher=voucher).delete()


def test_no_payment_while_a_cancellation_waits(accountant, cashier, bank, voucher):
    vouchers.request_cancellation(accountant, voucher, "Supplier will not deliver")
    with pytest.raises(PaymentError, match="cancellation"):
        pay(cashier, voucher, bank, "100.00")
    with pytest.raises(DatabaseError, match="cancellation"), transaction.atomic():
        raw_insert(voucher, bank, "100.00", cashier)
    assert "pay" not in vouchers.actions(cashier, fresh(voucher))


def test_a_voucher_with_payments_is_never_deleted_or_cancelled(director, cashier, bank, voucher):
    pay(cashier, voucher, bank, "100.00")
    with pytest.raises(DatabaseError, match="has payments"), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(
            status="deleted", deleted_at=timezone.now(), deleted_by=director
        )
    with pytest.raises(DatabaseError, match="has payments"), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(status="cancelled")
    with pytest.raises(DatabaseError, match="not fully paid"), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(status="paid")


def test_methods_accounts_and_people(accountant, cashier, bank, cash, voucher):
    with pytest.raises(PaymentError, match="Only the Cashier"):
        pay(accountant, voucher, bank, "10.00")
    with pytest.raises(PaymentError, match="not paid by cash"):
        pay(cashier, voucher, cash, "10.00", method="cash")  # a Cheque Payment voucher
    assert services.methods_for(voucher) == ["cheque"]
    with pytest.raises(PaymentError, match="cannot be in the future"):
        pay(cashier, voucher, bank, "10.00", payment_date=date(2099, 1, 1))
    with pytest.raises(PaymentError, match="more than zero"):
        pay(cashier, voucher, bank, "0")


# --- Through the API --------------------------------------------------------------------


def test_the_cashier_pays_through_the_api(accountant, cashier, bank, voucher):
    client = as_user(cashier)
    queue = client.get("/api/v1/payments/to-pay/").json()
    assert [(r["number"], r["remaining"], r["methods"]) for r in queue] == [
        (voucher.number, "1000.00", ["cheque"])
    ]
    accounts = client.get("/api/v1/payments/accounts/").json()
    assert {(a["code"], a["next_cheque"]) for a in accounts} >= {("COM-CUR", "000100")}
    assert "pay" in vouchers.actions(cashier, fresh(voucher))

    body = {"voucher": voucher.pk, "account": bank.pk, "method": "cheque", "amount": "400.00"}
    assert as_user(accountant).post("/api/v1/payments/", body, format="json").status_code == 403
    made = client.post("/api/v1/payments/", body, format="json")
    assert made.status_code == 201, made.json()
    assert made.json()["reference"] == "000100" and made.json()["amount"] == "400.00"
    too_much = client.post("/api/v1/payments/", {**body, "amount": "600.01"}, format="json")
    assert too_much.status_code == 400

    shown = client.get(f"/api/v1/vouchers/{voucher.pk}/").json()
    assert (shown["status"], shown["paid"], shown["remaining"]) == (
        "partly_paid",
        "400.00",
        "600.00",
    )
    assert [p["number"] for p in shown["payments"]] == [made.json()["number"]]
    assert client.get(f"/api/v1/payments/?voucher={voucher.pk}").json()[0]["journal_entry"]
    assert client.get(f"/api/v1/vouchers/{voucher.pk}/print/").status_code == 200
