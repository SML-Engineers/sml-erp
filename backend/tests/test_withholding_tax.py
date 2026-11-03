# ruff: noqa: F811 - the fixtures of test_payments are imported and used by name
"""Withholding tax on supplier payments (backlog P2-12): built switched off, the Accountant
codes WHT on a line once its rate is confirmed, the payment keeps it back, credits the WHT
payable account and gives the payee a numbered certificate."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import Account, TaxComponent
from apps.core.models import Division
from apps.payments import cancellations, services
from apps.payments.models import SupplierPayment
from apps.payments.services import PaymentError
from apps.vouchers import services as vouchers
from apps.vouchers.models import Voucher
from apps.vouchers.services import CodingInput, LineInput, VoucherError

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
)
from .test_vouchers import attach, draft, payee

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()
D = Decimal


def wht():
    return TaxComponent.objects.get(code="WHT")


@pytest.fixture
def wht_on(accountant):
    """WHT switched on: a 5% rate from a year ago."""
    taxes.add_rate(accountant, wht(), effective_from=TODAY - timedelta(days=365), rate="5")
    return wht()


def coded(clerk, accountant, amount="1000.00", component=None, code="S0101"):
    voucher = draft(clerk, payee(code=code), LineInput(amount=amount, invoice_no=f"F-{code}"))
    attach(clerk, voucher, content=b"%PDF-1.7 " + code.encode())
    vouchers.submit(clerk, voucher)
    return vouchers.code_lines(
        accountant,
        voucher,
        [
            CodingInput(
                line_no=1,
                account=Account.objects.get(number="6210"),
                division=Division.objects.get(code="WS"),
                wht_component=component,
            )
        ],
    )


def approved(clerk, accountant, director, **values):
    voucher = coded(clerk, accountant, **values)
    vouchers.approve(accountant, voucher, "coded")
    return vouchers.approve(director, fresh(voucher))


# --- Switched off until a rate is confirmed --------------------------------------------------


def test_without_a_rate_no_withholding_tax_can_be_chosen(clerk, accountant):
    assert vouchers.wht_choices(TODAY) == []
    with pytest.raises(VoucherError, match="WHT has no rate"):
        coded(clerk, accountant, component=wht())


def test_a_charged_tax_is_not_a_withholding_tax(clerk, accountant, wht_on):
    with pytest.raises(VoucherError, match="not an active withholding tax"):
        coded(clerk, accountant, component=TaxComponent.objects.get(code="VAT"))


def test_once_the_rate_is_set_the_accountant_codes_wht_on_a_line(clerk, accountant, wht_on):
    assert vouchers.wht_choices(TODAY) == [wht_on]
    voucher = coded(clerk, accountant, component=wht_on)
    line = voucher.lines.get()
    assert (line.wht_component, line.wht_rate, line.wht_amount) == (wht_on, D("5"), D("50.00"))
    assert (voucher.total_amount, voucher.wht_total, vouchers.payable(voucher)) == (
        D("1000.00"),
        D("50.00"),
        D("950.00"),
    )
    # Coding again without it takes it off.
    voucher = vouchers.code_lines(
        accountant,
        voucher,
        [CodingInput(line_no=1, account=Account.objects.get(number="6210"))],
    )
    assert (voucher.wht_total, voucher.lines.get().wht_amount) == (D("0.00"), D("0.00"))


def test_wht_rounds_half_up_on_the_amount_before_vat(clerk, accountant, wht_on):
    voucher = coded(clerk, accountant, amount="1234.50", component=wht_on)
    assert voucher.wht_total == D("61.73")  # 61.725


# --- Paying -----------------------------------------------------------------------------------


def test_a_full_payment_keeps_the_wht_and_gives_a_certificate(
    clerk, accountant, director, cashier, bank, wht_on
):
    voucher = approved(clerk, accountant, director, component=wht_on)
    assert services.to_receive(voucher) == D("950.00")
    with pytest.raises(PaymentError, match="Only 950.00 is left to pay the payee"):
        pay(cashier, voucher, bank, "1000.00")
    payment = pay(cashier, voucher, bank, "950.00")
    assert (payment.amount, payment.paid_amount, payment.wht_amount) == (
        D("1000.00"),
        D("950.00"),
        D("50.00"),
    )
    assert payment.wht_certificate.startswith(f"WHT{payment.payment_date:%y%m}")
    assert entry_lines(payment) == [
        ("1030", None, D("0"), D("950.00")),
        ("2120", "WS", D("0"), D("50.00")),
        ("6210", "WS", D("1000.00"), D("0")),
    ]
    assert fresh(voucher).status == Voucher.Status.PAID
    assert services.to_receive(fresh(voucher)) == D("0.00")


def test_part_payments_keep_their_share_and_the_last_keeps_what_is_left(
    clerk, accountant, director, cashier, bank, wht_on
):
    voucher = approved(clerk, accountant, director, component=wht_on)
    first = pay(cashier, voucher, bank, "300.00")
    assert (first.amount, first.wht_amount) == (D("315.79"), D("15.79"))
    assert fresh(voucher).status == Voucher.Status.PARTLY_PAID
    assert services.to_receive(fresh(voucher)) == D("650.00")
    second = pay(cashier, voucher, bank, "650.00")
    assert (second.amount, second.wht_amount) == (D("684.21"), D("34.21"))
    assert second.wht_certificate != first.wht_certificate
    assert fresh(voucher).status == Voucher.Status.PAID


def test_a_voucher_without_wht_is_paid_as_before(clerk, accountant, director, cashier, bank):
    voucher = approved(clerk, accountant, director)
    payment = pay(cashier, voucher, bank, "1000.00")
    assert (payment.wht_amount, payment.wht_certificate) == (D("0"), "")


def test_cancelling_a_payment_gives_the_wht_back_to_pay_again(
    clerk, accountant, director, cashier, bank, wht_on
):
    voucher = approved(clerk, accountant, director, component=wht_on)
    payment = pay(cashier, voucher, bank, "950.00")
    request = cancellations.request(cashier, payment, "Cheque written wrongly")
    cancellations.approve(director, request, "OK")
    assert services.wht_kept(fresh(voucher)) == D("0.00")
    assert services.to_receive(fresh(voucher)) == D("950.00")
    again = pay(cashier, voucher, bank, "950.00")
    assert again.wht_amount == D("50.00") and again.wht_certificate != payment.wht_certificate


# --- Locked in the database -------------------------------------------------------------------


def test_the_database_keeps_the_wht_of_an_approved_voucher(clerk, accountant, director, wht_on):
    voucher = approved(clerk, accountant, director, component=wht_on)
    with pytest.raises(DatabaseError, match="approved"), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(wht_total=D("0"))


def test_the_database_keeps_the_wht_of_a_payment(
    clerk, accountant, director, cashier, bank, wht_on
):
    voucher = approved(clerk, accountant, director, component=wht_on)
    payment = pay(cashier, voucher, bank, "950.00")
    with pytest.raises(DatabaseError, match="never changes"), transaction.atomic():
        SupplierPayment.objects.filter(pk=payment.pk).update(wht_amount=D("0"))
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute(
            "UPDATE payments_supplierpayment SET wht_certificate = 'X' WHERE id = %s",
            [payment.pk],
        )


def test_an_amendment_keeps_the_wht(clerk, accountant, director, wht_on):
    voucher = approved(clerk, accountant, director, component=wht_on)
    amendment = vouchers.amend(clerk, voucher, "Supplier sent a corrected invoice")
    assert amendment.wht_total == D("50.00")
    assert amendment.lines.get().wht_amount == D("50.00")


# --- The API and the certificate --------------------------------------------------------------


def test_the_accountant_chooses_wht_through_the_api(clerk, accountant, wht_on):
    voucher = coded(clerk, accountant)
    client = as_user(accountant)
    detail = client.get(f"/api/v1/vouchers/{voucher.pk}/").json()
    assert detail["wht_choices"] == [{"code": "WHT", "name": wht_on.name, "rate": "5"}]
    response = client.patch(
        f"/api/v1/vouchers/{voucher.pk}/coding/",
        {
            "lines": [
                {
                    "line_no": 1,
                    "account": Account.objects.get(number="6210").pk,
                    "division": "WS",
                    "wht_component": "WHT",
                }
            ]
        },
        format="json",
    )
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["wht_total"], body["payable"]) == ("50.00", "950.00")
    assert body["lines"][0]["wht_amount"] == "50.00"


def test_the_cashier_prints_the_certificate(clerk, accountant, director, cashier, bank, wht_on):
    voucher = approved(clerk, accountant, director, component=wht_on)
    payment = pay(cashier, voucher, bank, "950.00")
    client = as_user(cashier)
    rows = client.get("/api/v1/payments/to-pay/").json()
    assert rows == []
    response = client.get(f"/api/v1/payments/{payment.pk}/wht-certificate/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


def test_the_to_pay_list_shows_what_the_payee_receives(
    clerk, accountant, director, cashier, wht_on
):
    approved(clerk, accountant, director, component=wht_on)
    rows = as_user(cashier).get("/api/v1/payments/to-pay/").json()
    assert (rows[0]["remaining"], rows[0]["wht_total"], rows[0]["to_receive"]) == (
        "1000.00",
        "50.00",
        "950.00",
    )


def test_no_certificate_for_a_payment_without_wht(clerk, accountant, director, cashier, bank):
    voucher = approved(clerk, accountant, director)
    payment = pay(cashier, voucher, bank, "1000.00")
    response = as_user(cashier).get(f"/api/v1/payments/{payment.pk}/wht-certificate/")
    assert response.status_code == 400
