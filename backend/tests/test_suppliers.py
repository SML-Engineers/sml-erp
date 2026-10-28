"""Suppliers and payees (backlog P0-13, spec 4.1)."""

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.core.models import AuditEvent
from apps.masters import services, suppliers
from apps.masters.models import Supplier, SupplierBankAccount
from apps.masters.services import MastersError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", divisions=["WS"])


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def ceylon_steel(clerk):
    return suppliers.create_supplier(
        clerk, {"name": "Ceylon Steel Ltd", "vat_no": "114223344-7000", "tin": "114223344"}
    )


def account(**extra):
    return {
        "bank_name": "Commercial Bank",
        "branch": "Negombo",
        "account_name": "Ceylon Steel Ltd",
        "account_number": "1000123456",
        **extra,
    }


# --- Adding and changing payees ---------------------------------------------------------


def test_a_clerk_adds_a_payee_and_gets_the_next_code(clerk):
    first = suppliers.create_supplier(
        clerk, {"name": "Ceylon Electricity Board", "category": "utility"}
    )
    second = suppliers.create_supplier(clerk, {"name": "Lanka Hardware"})
    assert (first.code, second.code) == ("S0001", "S0002")
    assert first.category == "utility"
    assert first.currency.code == "LKR"
    assert first.payment_terms_days == 30


def test_every_payee_category_from_the_spec_is_available():
    assert dict(Supplier.Category.choices) == {
        "supplier": "Supplier",
        "utility": "Utility",
        "bank_card": "Bank or credit card",
        "government": "Government",
        "employee": "Employee",
        "other": "Other",
    }


@pytest.mark.parametrize(
    "values, why",
    [
        ({"name": " "}, "name is required"),
        ({"name": "X", "tin": "12345"}, "nine digits"),
        ({"name": "X", "category": "friend"}, "category"),
        ({"name": "X", "payment_terms_days": 400}, "0 to 365"),
        ({"name": "X", "currency": "XYZ"}, "active currency"),
    ],
)
def test_a_payee_must_be_valid(clerk, values, why):
    with pytest.raises(MastersError, match=why):
        suppliers.create_supplier(clerk, values)


def test_a_duplicate_vat_number_warns_before_saving(clerk, ceylon_steel):
    with pytest.raises(suppliers.NeedsConfirmation) as warned:
        suppliers.create_supplier(clerk, {"name": "Ceylon Steel (Pvt)", "vat_no": "114223344-7000"})
    assert warned.value.warnings == [
        "VAT number 114223344-7000 is already used by S0001 Ceylon Steel Ltd."
    ]
    assert Supplier.objects.count() == 1
    confirmed = suppliers.create_supplier(
        clerk, {"name": "Ceylon Steel (Pvt)", "vat_no": "114223344-7000"}, confirmed=True
    )
    row = AuditEvent.objects.get(object_type="masters.supplier", object_id=str(confirmed.pk))
    assert "already used" in row.reason


def test_the_api_returns_the_warning_and_saves_after_confirmation(clerk, ceylon_steel):
    data = {"name": "Another", "vat_no": "114223344-7000"}
    response = as_user(clerk).post("/api/v1/payees/", data, format="json")
    assert response.status_code == 409
    assert response.json()["needs_confirmation"] is True
    response = as_user(clerk).post(
        "/api/v1/payees/", data | {"confirm_duplicates": True}, format="json"
    )
    assert response.status_code == 201, response.json()


def test_only_the_accountant_deactivates_a_payee_with_a_reason(clerk, accountant, ceylon_steel):
    with pytest.raises(MastersError, match="Only the Accountant"):
        suppliers.update_supplier(clerk, ceylon_steel, {"is_active": False}, reason="x")
    with pytest.raises(MastersError, match="reason"):
        suppliers.update_supplier(accountant, ceylon_steel, {"is_active": False})
    suppliers.update_supplier(accountant, ceylon_steel, {"is_active": False}, reason="closed down")
    names = [p["name"] for p in as_user(clerk).get("/api/v1/payees/").json()]
    assert "Ceylon Steel Ltd" not in names
    every = as_user(clerk).get("/api/v1/payees/", {"include_inactive": "1"}).json()
    assert "Ceylon Steel Ltd" in [p["name"] for p in every]


def test_a_payee_used_on_a_voucher_keeps_its_code_and_cannot_be_deleted(ceylon_steel):
    services.mark_used(ceylon_steel)
    with pytest.raises(DatabaseError), transaction.atomic():
        Supplier.objects.filter(pk=ceylon_steel.pk).update(code="S9999")
    with pytest.raises(DatabaseError), transaction.atomic():
        Supplier.objects.filter(pk=ceylon_steel.pk).delete()


def test_payees_can_be_searched_by_name_code_or_vat(clerk, ceylon_steel):
    suppliers.create_supplier(clerk, {"name": "Lanka Hardware"})
    for text in ("steel", "S0001", "114223344"):
        found = as_user(clerk).get("/api/v1/payees/", {"q": text}).json()
        assert [p["code"] for p in found] == ["S0001"], text


# --- Bank details -----------------------------------------------------------------------


def test_only_someone_with_the_bank_details_permission_enters_bank_details(
    clerk, accountant, ceylon_steel
):
    with pytest.raises(MastersError, match="change bank details"):
        suppliers.add_bank_account(clerk, ceylon_steel, account())
    added = suppliers.add_bank_account(accountant, ceylon_steel, account())
    assert added.is_default  # the first account is the default
    response = as_user(clerk).post(
        f"/api/v1/payees/{ceylon_steel.pk}/bank-accounts/", account(), format="json"
    )
    assert response.status_code == 400


def test_changing_a_bank_account_writes_one_audit_row_with_old_and_new(accountant, ceylon_steel):
    added = suppliers.add_bank_account(accountant, ceylon_steel, account())
    suppliers.update_bank_account(
        accountant, added, {"account_number": "2000987654"}, reason="supplier's letter of 2 Nov"
    )
    rows = AuditEvent.objects.filter(
        object_type="masters.supplierbankaccount", object_id=str(added.pk), action="update"
    )
    [row] = rows
    assert row.changes == {"account_number": ["1000123456", "2000987654"]}
    assert row.event == "payee_bank_changed"
    assert row.reason == "supplier's letter of 2 Nov"


def test_a_bank_change_needs_a_reason(accountant, ceylon_steel):
    added = suppliers.add_bank_account(accountant, ceylon_steel, account())
    with pytest.raises(MastersError, match="reason"):
        suppliers.update_bank_account(accountant, added, {"account_number": "2000987654"}, "")


def test_a_bank_change_is_flagged_until_the_accountant_acknowledges_it(accountant, ceylon_steel):
    added = suppliers.add_bank_account(accountant, ceylon_steel, account())
    payee = Supplier.objects.get(pk=ceylon_steel.pk)
    assert payee.bank_change_pending
    assert payee.bank_changed_by == accountant
    suppliers.acknowledge_bank_change(accountant, payee)
    assert not Supplier.objects.get(pk=payee.pk).bank_change_pending
    suppliers.update_bank_account(accountant, added, {"branch": "Seeduwa"}, reason="moved")
    assert Supplier.objects.get(pk=payee.pk).bank_change_pending


def test_only_the_accountant_acknowledges_a_bank_change(clerk, accountant, ceylon_steel):
    suppliers.add_bank_account(accountant, ceylon_steel, account())
    with pytest.raises(MastersError, match="Only the Accountant"):
        suppliers.acknowledge_bank_change(clerk, ceylon_steel)


@pytest.mark.parametrize(
    "extra, why",
    [
        ({"account_number": "12"}, "4 to 34"),
        ({"swift_code": "BAD"}, "8 or 11"),
        ({"bank_name": ""}, "bank name"),
    ],
)
def test_bank_details_must_be_valid(accountant, ceylon_steel, extra, why):
    with pytest.raises(MastersError, match=why):
        suppliers.add_bank_account(accountant, ceylon_steel, account(**extra))


def test_one_default_account_per_payee(accountant, ceylon_steel):
    first = suppliers.add_bank_account(accountant, ceylon_steel, account())
    second = suppliers.add_bank_account(
        accountant, ceylon_steel, account(account_number="3000111222", is_default=True)
    )
    assert not SupplierBankAccount.objects.get(pk=first.pk).is_default
    assert SupplierBankAccount.objects.get(pk=second.pk).is_default
    with pytest.raises(MastersError, match="already has that account"):
        suppliers.add_bank_account(accountant, ceylon_steel, account(account_number="3000111222"))


def test_granting_the_bank_details_permission_needs_the_director():
    from apps.core.access_defaults import SENSITIVE_ACTIONS

    assert "change_bank_details" in SENSITIVE_ACTIONS


# --- Who can see payees -----------------------------------------------------------------


def test_people_without_payee_access_cannot_see_payees(ceylon_steel):
    admin = person("admin@sml.lk", "system_admin", all_divisions=True)
    assert as_user(admin).get("/api/v1/payees/").status_code == 403
    cashier = person("cashier@sml.lk", "cashier")
    assert as_user(cashier).get("/api/v1/payees/").status_code == 200
    assert as_user(cashier).post("/api/v1/payees/", {"name": "X"}, format="json").status_code == 403
