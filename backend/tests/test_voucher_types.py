"""Voucher types (backlog P1-01, spec 4.1)."""

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.core import approvals
from apps.core.models import AuditEvent
from apps.masters.services import mark_used
from apps.vouchers import services
from apps.vouchers.models import VoucherType
from apps.vouchers.services import VoucherError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

URL = "/api/v1/voucher-types/"


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


def vt(code):
    return VoucherType.objects.get(code=code)


def test_the_six_starting_types_are_loaded():
    assert list(VoucherType.objects.values_list("code", flat=True)) == [
        "CHQ",
        "ONL",
        "PCH",
        "INT",
        "ADV",
        "RMB",
    ]
    assert vt("INT").needs_payee is False and vt("INT").payment_method == "internal"
    assert vt("RMB").payee_category == "employee"
    assert vt("ADV").is_advance and vt("ADV").payee_category == "supplier"


def test_every_type_goes_to_the_accountant_and_the_director():
    for code in VoucherType.objects.values_list("code", flat=True):
        route = approvals.route_for("voucher", amount="10.00", subtype=code)
        assert [step["role"] for step in route] == ["accountant", "director"], code


def test_the_admin_adds_a_type_and_everyone_can_list_them(admin):
    body = {
        "code": "ccp",
        "name": "Credit Card Payment",
        "payment_method": "transfer",
        "payee_category": "bank_card",
    }
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(clerk).post(URL, body, format="json").status_code == 403
    response = as_user(admin).post(URL, body, format="json")
    assert response.status_code == 201, response.json()
    assert response.json()["code"] == "CCP"
    codes = [row["code"] for row in as_user(clerk).get(URL).json()]
    assert "CCP" in codes and codes[0] == "CHQ"
    assert AuditEvent.objects.filter(event="voucher_type_created").exists()


@pytest.mark.parametrize(
    "values, why",
    [
        ({"code": "1X", "name": "Bad", "payment_method": "cash"}, "starting with a letter"),
        ({"code": "CHQ", "name": "Cheque again", "payment_method": "cheque"}, "already used"),
        (
            {"code": "CQ2", "name": "cheque payment", "payment_method": "cheque"},
            "already a voucher type",
        ),
        ({"code": "XX", "name": "X", "payment_method": "bitcoin"}, "how this type is paid"),
        (
            {"code": "XX", "name": "X", "payment_method": "cash", "payee_category": "friend"},
            "payee category",
        ),
        (
            {"code": "XX", "name": "X", "payment_method": "cash", "needs_payee": False},
            "own accounts",
        ),
    ],
)
def test_a_type_must_make_sense(admin, values, why):
    with pytest.raises(VoucherError, match=why):
        services.create_type(admin, **values)


def test_a_used_type_keeps_its_code_and_payment_method(admin):
    cheque = vt("CHQ")
    mark_used(cheque)
    with pytest.raises(VoucherError, match="code is fixed"):
        services.update_type(admin, cheque, {"code": "CHEQ"})
    with pytest.raises(DatabaseError), transaction.atomic():
        VoucherType.objects.filter(pk=cheque.pk).update(code="CHEQ")
    with pytest.raises(VoucherError, match="cannot change"):
        services.update_type(admin, cheque, {"payment_method": "transfer"})
    with pytest.raises(VoucherError, match="switch it off instead"):
        services.delete_type(admin, cheque, reason="old")
    with pytest.raises(VoucherError, match="reason"):
        services.update_type(admin, cheque, {"is_active": False})
    services.update_type(admin, cheque, {"name": "Cheque", "is_active": False}, reason="use ONL")
    assert vt("CHQ").name == "Cheque" and not vt("CHQ").is_active
    assert "CHQ" not in [row["code"] for row in as_user(admin).get(URL).json()]
    assert "CHQ" in [row["code"] for row in as_user(admin).get(f"{URL}?include_inactive=1").json()]


def test_an_unused_type_added_by_mistake_is_deleted(admin):
    extra = services.create_type(admin, code="TMP", name="Temporary", payment_method="cash")
    response = as_user(admin).delete(f"{URL}{extra.pk}/", {"reason": "typo"}, format="json")
    assert response.status_code == 204
    assert not VoucherType.objects.filter(code="TMP").exists()


def test_at_least_one_type_stays_in_use(admin):
    last = vt("CHQ")
    for other in VoucherType.objects.exclude(pk=last.pk):
        services.update_type(admin, other, {"is_active": False}, reason="test")
    with pytest.raises(VoucherError, match="At least one"):
        services.update_type(admin, last, {"is_active": False}, reason="test")
