"""Customers and contacts (backlog P15-01, spec 5.4, 5.5)."""

import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from openpyxl import Workbook, load_workbook

from apps.core.models import AuditEvent
from apps.masters import customers
from apps.masters.models import Customer, CustomerContact
from apps.masters.services import MastersError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive")


@pytest.fixture
def manager():
    return person("salesmanager@sml.lk", "sales_manager")


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", divisions=["WS"])


@pytest.fixture
def unilever(executive):
    return customers.create_customer(
        executive,
        {"name": "Unilever Sri Lanka", "vat_no": "114000111-7000", "tin": "114000111"},
    )


# --- Adding and changing customers ------------------------------------------------------


def test_a_sales_executive_adds_customers_with_the_next_code(executive):
    first = customers.create_customer(executive, {"name": "Unilever Sri Lanka"})
    second = customers.create_customer(executive, {"name": "Hayleys Fabric"})
    assert (first.code, second.code) == ("C0001", "C0002")
    assert first.currency.code == "LKR"
    assert first.payment_terms_days == 30
    assert first.created_by == executive
    assert AuditEvent.objects.filter(event="customer_created").count() == 2


def test_an_export_customer_has_its_currency_country_and_delivery_term(executive):
    buyer = customers.create_customer(
        executive,
        {
            "name": "Nordic Plast AB",
            "currency": "eur",
            "is_export": True,
            "country": "Sweden",
            "incoterm": "fob",
            "port_of_destination": "Gothenburg",
        },
    )
    assert buyer.currency.code == "EUR"
    assert buyer.incoterm == "FOB"
    with pytest.raises(MastersError, match="country of an export customer"):
        customers.create_customer(executive, {"name": "Somewhere Ltd", "is_export": True})


@pytest.mark.parametrize(
    "values, why",
    [
        ({"name": ""}, "name is required"),
        ({"name": "A", "tin": "12345"}, "TIN must be nine digits"),
        ({"name": "A", "email": "not-an-email"}, "email address is not valid"),
        ({"name": "A", "payment_terms_days": 400}, "0 to 365 days"),
        ({"name": "A", "currency": "XXX"}, "active currency"),
        ({"name": "A", "credit_limit": "-1"}, "0 or more"),
        ({"name": "A", "credit_limit": "10.005"}, "at most two decimals"),
        ({"name": "A", "credit_limit": "lots"}, "must be an amount"),
        ({"name": "A", "incoterm": "XYZ"}, "Incoterm"),
    ],
)
def test_wrong_details_are_refused(executive, values, why):
    with pytest.raises(MastersError, match=why):
        customers.create_customer(executive, values)


def test_a_likely_duplicate_must_be_confirmed(executive, unilever):
    with pytest.raises(customers.NeedsConfirmation) as same_name:
        customers.create_customer(executive, {"name": "unilever sri lanka"})
    assert "already a customer called Unilever Sri Lanka (C0001)" in str(same_name.value)
    with pytest.raises(customers.NeedsConfirmation, match="VAT number 114000111-7000"):
        customers.create_customer(executive, {"name": "UL", "vat_no": "114000111-7000"})
    confirmed = customers.create_customer(executive, {"name": "Unilever Sri Lanka"}, confirmed=True)
    assert confirmed.code == "C0002"


def test_only_the_sales_manager_or_director_deactivates_with_a_reason(executive, manager, unilever):
    with pytest.raises(MastersError, match="Sales Manager or the Director"):
        customers.set_active(executive, unilever, False, reason="Closed")
    with pytest.raises(MastersError, match="Give a reason"):
        customers.set_active(manager, unilever, False)
    customers.set_active(manager, unilever, False, reason="Closed down")
    unilever.refresh_from_db()
    assert not unilever.is_active
    event = AuditEvent.objects.get(event="customer_deactivated")
    assert event.reason == "Closed down"
    director = person("director@sml.lk", "director", all_divisions=True)
    customers.set_active(director, unilever, True)
    unilever.refresh_from_db()
    assert unilever.is_active


def test_deactivating_through_the_api_needs_sales_approval(executive, manager, unilever):
    url = f"/api/v1/customers/{unilever.pk}/active/"
    body = {"is_active": False, "reason": "Closed down"}
    assert as_user(executive).post(url, body, format="json").status_code == 403
    done = as_user(manager).post(url, body, format="json")
    assert done.status_code == 200 and done.json()["is_active"] is False
    # Changing details does not deactivate, even if asked to.
    as_user(executive).patch(
        f"/api/v1/customers/{unilever.pk}/", {"is_active": True, "phone": "011"}, format="json"
    )
    unilever.refresh_from_db()
    assert not unilever.is_active and unilever.phone == "011"


def test_people_without_sales_access_cannot_add_or_change_customers(clerk, unilever):
    with pytest.raises(MastersError, match="cannot add customers"):
        customers.create_customer(clerk, {"name": "Someone"})
    with pytest.raises(MastersError, match="cannot change customers"):
        customers.update_customer(clerk, unilever, {"name": "Changed"})


def test_a_used_customer_keeps_its_code_and_is_never_deleted(unilever):
    customers.mark_used(unilever)
    with pytest.raises(DatabaseError, match="cannot be deleted"), transaction.atomic():
        Customer.objects.filter(pk=unilever.pk).delete()
    with pytest.raises(DatabaseError, match="code cannot change"), transaction.atomic():
        Customer.objects.filter(pk=unilever.pk).update(code="C9999")
    Customer.objects.filter(pk=unilever.pk).update(name="Unilever Sri Lanka Ltd")  # details: yes


def test_an_unused_customer_can_still_be_removed(unilever):
    Customer.objects.filter(pk=unilever.pk).delete()
    assert not Customer.objects.exists()


# --- Contacts ---------------------------------------------------------------------------


def test_the_first_contact_is_the_main_one_and_there_is_only_one(executive, unilever):
    nimali = customers.add_contact(executive, unilever, {"name": "Nimali", "position": "Buyer"})
    assert nimali.is_main
    kasun = customers.add_contact(executive, unilever, {"name": "Kasun", "is_main": True})
    nimali.refresh_from_db()
    assert kasun.is_main and not nimali.is_main
    customers.update_contact(executive, nimali, {"is_main": True})
    kasun.refresh_from_db()
    assert not kasun.is_main
    with pytest.raises(DatabaseError), transaction.atomic():
        CustomerContact.objects.filter(pk=kasun.pk).update(is_main=True)  # two main contacts


def test_a_contact_who_leaves_stops_being_the_main_contact(executive, unilever):
    nimali = customers.add_contact(executive, unilever, {"name": "Nimali"})
    left = customers.update_contact(executive, nimali, {"is_active": False})
    assert not left.is_main and not left.is_active
    with pytest.raises(MastersError, match="cannot be the main contact"):
        customers.update_contact(executive, left, {"is_main": True})
    with pytest.raises(MastersError, match="name is required"):
        customers.add_contact(executive, unilever, {"name": " "})


# --- API --------------------------------------------------------------------------------


def test_the_api_lists_searches_adds_and_changes_customers(executive, unilever):
    client = as_user(executive)
    customers.add_contact(executive, unilever, {"name": "Nimali Fernando"})
    found = client.get("/api/v1/customers/?q=nimali").json()
    assert [c["code"] for c in found] == ["C0001"]
    assert found[0]["main_contact"]["name"] == "Nimali Fernando"
    assert found[0]["in_use"] is False

    added = client.post("/api/v1/customers/", {"name": "Hayleys Fabric"}, format="json")
    assert added.status_code == 201
    assert (added.json()["credit_limit"], added.json()["payment_terms_days"]) == (None, 30)
    duplicate = client.post("/api/v1/customers/", {"name": "Hayleys Fabric"}, format="json")
    assert duplicate.status_code == 409 and duplicate.json()["needs_confirmation"]

    changed = client.patch(
        f"/api/v1/customers/{unilever.pk}/", {"phone": "011 2345678"}, format="json"
    )
    assert changed.status_code == 200 and changed.json()["phone"] == "011 2345678"
    contact = client.post(
        f"/api/v1/customers/{unilever.pk}/contacts/",
        {"name": "Kasun", "email": "kasun@unilever.com", "is_main": True},
        format="json",
    )
    assert contact.status_code == 201
    contacts = client.get(f"/api/v1/customers/{unilever.pk}/contacts/").json()
    assert [(c["name"], c["is_main"]) for c in contacts] == [
        ("Kasun", True),
        ("Nimali Fernando", False),
    ]


def test_the_server_refuses_people_without_sales_access(clerk, unilever):
    client = as_user(clerk)
    assert client.get("/api/v1/customers/").status_code == 403
    assert client.post("/api/v1/customers/", {"name": "X"}, format="json").status_code == 403
    assert client.get("/api/v1/customers/export/").status_code == 403


def test_the_accountant_can_look_but_not_change(unilever):
    accountant = person("accountant@sml.lk", "accountant", all_divisions=True)
    client = as_user(accountant)
    assert client.get(f"/api/v1/customers/{unilever.pk}/").status_code == 200
    refused = client.patch(f"/api/v1/customers/{unilever.pk}/", {"name": "X"}, format="json")
    assert refused.status_code == 403


# --- Excel export and import ------------------------------------------------------------


def book(*rows):
    workbook = Workbook()
    workbook.remove(workbook.active)
    sheet = workbook.create_sheet("Customers")
    sheet.append(customers.COLUMNS)
    for row in rows:
        values = dict.fromkeys(customers.COLUMNS, None) | row
        sheet.append([values[c] for c in customers.COLUMNS])
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def upload(user, content, reason="Customer list from the old system", dry_run=False):
    return as_user(user).post(
        "/api/v1/customers/import/",
        {
            "file": SimpleUploadedFile("customers.xlsx", content),
            "reason": reason,
            "dry_run": "1" if dry_run else "",
        },
        format="multipart",
    )


def test_the_export_can_be_edited_and_imported_again(executive, unilever):
    customers.add_contact(executive, unilever, {"name": "Nimali", "phone": "0771234567"})
    response = as_user(executive).get("/api/v1/customers/export/")
    assert response.status_code == 200
    sheet = load_workbook(io.BytesIO(response.content))["Customers"]
    header = [c.value for c in sheet[1]]
    assert header == customers.COLUMNS
    row = dict(zip(header, [c.value for c in sheet[2]], strict=True))
    assert (row["Code"], row["Main contact"], row["Active"]) == ("C0001", "Nimali", "Yes")

    row["Contact phone"] = "0777654321"
    result = upload(executive, book(row))
    assert result.status_code == 200, result.json()
    assert result.json() == {"dry_run": False, "created": 0, "updated": 1}
    unilever.refresh_from_db()
    assert unilever.contacts.get(is_main=True).phone == "0777654321"
    # Credit terms are not the salesperson's to change, in an import either.
    row["Payment terms (days)"] = 60
    refused = upload(executive, book(row))
    assert refused.status_code == 400
    assert "Only the Accountant or the Director" in refused.json()["errors"][0]


def test_an_import_adds_new_customers_and_a_check_saves_nothing():
    # Someone who may both add customers and set credit terms.
    importer = person("salesaccounts@sml.lk", "sales_executive", "accountant")
    content = book(
        {
            "Name": "Nordic Plast AB",
            "Currency": "EUR",
            "Export": "Yes",
            "Country": "Sweden",
            "Delivery term": "FOB – Free on board",
            "Credit limit": 25000.5,
            "Main contact": "Lars",
        },
        {"Name": "Hayleys Fabric", "Payment terms (days)": 45},
    )
    checked = upload(importer, content, dry_run=True)
    assert checked.json() == {"dry_run": True, "created": 2, "updated": 0}
    assert not Customer.objects.exists()

    assert upload(importer, content).status_code == 200
    nordic = Customer.objects.get(name="Nordic Plast AB")
    assert (nordic.currency.code, nordic.incoterm) == ("EUR", "FOB")
    assert nordic.credit_limit == Decimal("25000.50")  # read exactly, never as a float
    assert nordic.contacts.get().is_main


def test_an_import_with_any_wrong_row_saves_nothing_and_lists_every_problem(executive, unilever):
    content = book(
        {"Name": "Good Customer"},
        {"Name": "Unilever Sri Lanka"},
        {"Name": "Bad TIN", "TIN": "12"},
        {"Code": "C0999", "Name": "Nobody"},
    )
    result = upload(executive, content)
    assert result.status_code == 400
    errors = result.json()["errors"]
    assert len(errors) == 3
    assert errors[0].startswith("Row 3: There is already a customer called Unilever")
    assert "Put the existing code in the Code column" in errors[0]
    assert errors[1] == "Row 4: The TIN must be nine digits."
    assert errors[2].startswith("Row 5: There is no customer C0999")
    assert not Customer.objects.filter(name="Good Customer").exists()


def test_an_import_needs_a_reason_and_sales_access(executive, clerk):
    assert upload(executive, book({"Name": "A"}), reason="").json()["errors"] == [
        "Give a reason for the import."
    ]
    assert upload(clerk, book({"Name": "A"})).status_code == 403


# --- Credit terms (owner, 3 Nov 2026) ----------------------------------------------------


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant")


def test_only_the_accountant_or_director_changes_credit_terms(executive, accountant, unilever):
    with pytest.raises(MastersError, match="Only the Accountant or the Director"):
        customers.create_customer(executive, {"name": "Abans PLC", "credit_limit": "500000"})
    with pytest.raises(MastersError, match="Only the Accountant or the Director"):
        customers.update_customer(executive, unilever, {"payment_terms_days": 60})
    # Saving the form with the same terms is fine.
    customers.update_customer(executive, unilever, {"payment_terms_days": 30, "phone": "011"})
    with pytest.raises(MastersError, match="Only the Accountant or the Director"):
        customers.set_credit_terms(
            executive, unilever, credit_limit="1", payment_terms_days=30, reason="x"
        )
    with pytest.raises(MastersError, match="reason"):
        customers.set_credit_terms(
            accountant, unilever, credit_limit="1", payment_terms_days=30, reason=" "
        )
    changed = customers.set_credit_terms(
        accountant, unilever, credit_limit="750000", payment_terms_days=45, reason="Agreed"
    )
    assert (changed.credit_limit, changed.payment_terms_days) == (Decimal("750000.00"), 45)
    assert AuditEvent.objects.filter(event="customer_credit_terms_changed").exists()


def test_the_credit_terms_api(executive, accountant, unilever):
    path = f"/api/v1/customers/{unilever.pk}/credit-terms/"
    body = {"credit_limit": "250000", "payment_terms_days": 60, "reason": "Board decision"}
    refused = as_user(executive).post(path, body, format="json")
    assert refused.status_code == 400
    done = as_user(accountant).post(path, body, format="json")
    assert done.status_code == 200, done.json()
    assert (done.json()["credit_limit"], done.json()["payment_terms_days"]) == ("250000.00", 60)
    cleared = as_user(accountant).post(
        path, {"credit_limit": "", "payment_terms_days": 60, "reason": "No limit"}, format="json"
    )
    assert cleared.json()["credit_limit"] is None
