# ruff: noqa: F811 - the fixtures of test_payments are imported and used by name
"""Our own cheques in the register: issued, cleared, spoiled (backlog P2-14)."""

import pytest
from django.utils import timezone

from apps.banking import services
from apps.banking.services import BankingError
from apps.payments import cancellations

from .test_access import as_user
from .test_payments import (  # noqa: F401 - fixtures used by name
    accountant,
    bank,
    cashier,
    clerk,
    director,
    memory_storage,
    pay,
    voucher,
)

pytestmark = pytest.mark.django_db
TODAY = timezone.localdate()


def test_an_issued_cheque_is_marked_cleared(cashier, bank, voucher):
    payment = pay(cashier, voucher, bank, "1000.00")
    leaf = payment.cheque
    assert services.issued_status(leaf) == "issued"
    services.clear_issued(cashier, leaf, TODAY)
    leaf.refresh_from_db()
    assert services.issued_status(leaf) == "cleared"
    with pytest.raises(BankingError, match="already marked cleared"):
        services.clear_issued(cashier, leaf, TODAY)


def test_a_spoiled_cheque_does_not_clear(cashier, director, bank, voucher):
    payment = pay(cashier, voucher, bank, "1000.00")
    request = cancellations.request(cashier, payment, "Cheque torn")
    cancellations.approve(director, request, "OK")
    leaf = payment.cheque
    leaf.refresh_from_db()
    assert services.issued_status(leaf) == "spoiled"
    with pytest.raises(BankingError, match="not an issued cheque"):
        services.clear_issued(cashier, leaf, TODAY)


def test_the_register_lists_our_cheques(cashier, bank, voucher):
    payment = pay(cashier, voucher, bank, "1000.00")
    rows = as_user(cashier).get("/api/v1/cheques/issued/").json()
    assert [(r["number"], r["status"], r["payment"]["amount"]) for r in rows] == [
        ("000100", "issued", "1000.00")
    ]
    response = as_user(cashier).post(
        f"/api/v1/cheques/issued/{payment.cheque_id}/clear/", {"on": str(TODAY)}, format="json"
    )
    assert response.status_code == 200 and response.json()["status"] == "cleared"
