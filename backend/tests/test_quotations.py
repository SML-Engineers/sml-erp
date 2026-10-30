"""Quotation entry (backlog P15-03, spec 5.1, 5.5)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode, TaxComponent
from apps.core.models import AuditEvent, Division
from apps.masters import currencies, customers
from apps.masters.models import Currency, Customer
from apps.sales import services
from apps.sales.models import Quotation
from apps.sales.services import BreakInput, LineInput, SalesError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
PDF = b"%PDF-1.4 drawing"


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def other_executive():
    return person("sales2@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def manager():
    return person("salesmanager@sml.lk", "sales_manager", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def unilever(executive):
    customer = customers.create_customer(executive, {"name": "Unilever Sri Lanka"})
    customers.add_contact(executive, customer, {"name": "Nimali", "email": "nimali@ul.lk"})
    return customer


@pytest.fixture
def vat(accountant):
    """VAT 18% and SSCL 2.5% in force, as the Accountant enters them."""
    start = TODAY - timedelta(days=30)
    for code, rate in (("VAT", "18"), ("SSCL", "2.5")):
        taxes.add_rate(
            accountant, TaxComponent.objects.get(code=code), effective_from=start, rate=rate
        )
    return TaxCode.objects.get(code="VAT")


def division(code):
    return Division.objects.get(code=code)


def line(**extra):
    return LineInput(
        **{"description": "Shaft, EN8, turned and ground", "quantity": "10", "unit_price": "1500"}
        | extra
    )


def draft(user, customer, *lines, **values):
    return services.save(
        user,
        None,
        customer=customer,
        division=division("WS"),
        lines=list(lines) or [line()],
        **values,
    )


# --- Making a quotation -----------------------------------------------------------------


def test_a_draft_gets_its_number_and_the_customers_defaults(executive, unilever):
    q = draft(executive, unilever)
    assert q.number == f"QL{TODAY:%y%m%d}01"
    assert (q.revision, q.status) == (0, "draft")
    assert q.currency.code == "LKR" and q.exchange_rate == Decimal("1")
    assert q.contact.name == "Nimali"  # the main contact
    assert q.valid_until == TODAY + timedelta(days=7)
    assert q.payment_terms == "30 days"
    second = draft(executive, unilever)
    assert second.number == f"QL{TODAY:%y%m%d}02"
    assert AuditEvent.objects.filter(event="quotation_created").exists()


def test_amounts_and_taxes_are_exact(executive, unilever, vat):
    q = draft(
        executive,
        unilever,
        line(quantity="3", unit_price="1234.57", tax_code=vat),  # 3,703.71 + VAT 666.67
        line(description="Setting up the job", quantity="1", unit_price="2500.00"),
    )
    first, second = q.lines.all()
    assert first.amount == Decimal("3703.71")
    assert first.tax_amount == Decimal("666.67")
    assert second.tax_amount == Decimal("0.00")
    assert q.subtotal == Decimal("6203.71")
    assert q.tax_total == Decimal("666.67")
    assert q.total_amount == q.total_lkr == Decimal("6870.38")


def test_vat_and_sscl_follow_the_tax_code(executive, unilever, vat):
    both = TaxCode.objects.get(code="VAT-SSCL")
    q = draft(executive, unilever, line(quantity="1", unit_price="115750.00", tax_code=both))
    # spec 6.1: SSCL 2.5% = 2,893.75; VAT 18% on 118,643.75 = 21,355.88
    assert q.tax_total == Decimal("24249.63")


def test_an_export_quotation_keeps_the_exchange_rate_of_its_date(executive, unilever):
    euro = Currency.objects.get(code="EUR")
    currencies.set_rate(currency=euro, on_date=TODAY - timedelta(days=2), rate="325.40")
    q = draft(executive, unilever, line(quantity="100", unit_price="2.35"), currency="EUR")
    assert (q.currency.code, q.exchange_rate) == ("EUR", Decimal("325.400000"))
    assert q.rate_date == TODAY - timedelta(days=2)
    assert q.total_amount == Decimal("235.00")
    assert q.total_lkr == Decimal("76469.00")
    with pytest.raises(SalesError, match="no USD rate"):
        draft(executive, unilever, currency="USD")


def test_quantity_breaks_and_minimum_order_are_kept(executive, unilever):
    q = draft(
        executive,
        unilever,
        line(
            min_order_qty="10",
            breaks=[BreakInput("100", "1350.00"), BreakInput("50", "1420")],
        ),
    )
    row = q.lines.get()
    assert row.min_order_qty == Decimal("10.000")
    assert [(b.quantity, b.unit_price) for b in row.breaks.all()] == [
        (Decimal("50.000"), Decimal("1420.00")),
        (Decimal("100.000"), Decimal("1350.00")),
    ]


@pytest.mark.parametrize(
    "bad, why",
    [
        ({"description": " "}, "Line 1: the description is required"),
        ({"quantity": "0"}, "quantity must be more than 0"),
        ({"quantity": "1.2345"}, "at most 3 decimal places"),
        ({"unit_price": "-5"}, "unit price cannot be negative"),
        ({"unit_price": "10.005"}, "at most 2 decimal places"),
        ({"unit_price": 10.5}, "exact number"),
        ({"breaks": [BreakInput("50", "1"), BreakInput("50", "2")]}, "different quantity"),
    ],
)
def test_wrong_lines_are_refused(executive, unilever, bad, why):
    with pytest.raises(SalesError, match=why):
        draft(executive, unilever, line(**bad))


def test_a_purchase_only_tax_code_cannot_be_used(executive, unilever, accountant):
    code = TaxCode.objects.get(code="VAT")
    TaxCode.objects.filter(pk=code.pk).update(use=TaxCode.Use.PURCHASES)
    code.refresh_from_db()
    with pytest.raises(SalesError, match="cannot be used on sales"):
        draft(executive, unilever, line(tax_code=code))


def test_the_header_is_checked(executive, unilever):
    with pytest.raises(SalesError, match="production division"):
        services.save(executive, None, customer=unilever, division=division("HO"), lines=[line()])
    with pytest.raises(SalesError, match="at least one line"):
        services.save(executive, None, customer=unilever, division=division("WS"), lines=[])
    other = customers.create_customer(executive, {"name": "Hayleys"})
    stranger = customers.add_contact(executive, other, {"name": "Someone"})
    with pytest.raises(SalesError, match="customer's current contacts"):
        draft(executive, unilever, contact=stranger)
    with pytest.raises(SalesError, match="valid until its own date"):
        draft(executive, unilever, valid_until=TODAY - timedelta(days=1))
    Customer.objects.filter(pk=unilever.pk).update(is_active=False)
    unilever.refresh_from_db()
    with pytest.raises(SalesError, match="inactive"):
        draft(executive, unilever)


def test_only_divisions_the_user_works_in(unilever):
    moulding = person("im.sales@sml.lk", "sales_executive", divisions=["IM"])
    with pytest.raises(SalesError, match="do not work in division WS"):
        draft(moulding, unilever)


def test_the_customer_is_now_in_use_and_keeps_its_code(executive, unilever):
    draft(executive, unilever)
    unilever.refresh_from_db()
    assert unilever.first_used_at is not None
    with pytest.raises(DatabaseError, match="cannot be deleted"), transaction.atomic():
        Customer.objects.filter(pk=unilever.pk).delete()


# --- Changing a draft -------------------------------------------------------------------


def test_the_creator_changes_the_draft_and_its_lines(executive, unilever):
    q = draft(executive, unilever, line(), line(description="Second"))
    changed = services.save(
        executive, q, lines=[line(quantity="20")], notes="Price held for 30 days"
    )
    assert changed.number == q.number
    assert [r.quantity for r in changed.lines.all()] == [Decimal("20.000")]
    assert changed.total_amount == Decimal("30000.00")
    assert changed.notes == "Price held for 30 days"


def test_nobody_else_changes_a_draft_and_only_drafts_change(
    executive, other_executive, manager, unilever
):
    q = draft(executive, unilever)
    with pytest.raises(SalesError, match="Only the person who made"):
        services.save(other_executive, q, lines=[line()])
    with pytest.raises(SalesError, match="cannot make quotations"):
        services.save(manager, q, lines=[line()])  # approves, does not enter
    Quotation.objects.filter(pk=q.pk).update(status=Quotation.Status.SENT)
    q.refresh_from_db()
    with pytest.raises(SalesError, match="Only a draft"):
        services.save(executive, q, lines=[line()])


def test_the_division_of_a_quotation_does_not_change(executive, unilever):
    q = draft(executive, unilever)
    with pytest.raises(SalesError, match="division of a quotation cannot change"):
        services.save(executive, q, division=division("IM"), lines=[line()])


# --- Who sees what ----------------------------------------------------------------------


def test_sales_executives_see_their_own_and_managers_see_all(
    executive, other_executive, manager, accountant, unilever
):
    mine = draft(executive, unilever)
    theirs = draft(other_executive, unilever)
    assert list(services.visible(executive)) == [mine]
    assert set(services.visible(manager)) == {mine, theirs}
    assert set(services.visible(accountant)) == {mine, theirs}
    assert as_user(other_executive).get(f"/api/v1/quotations/{mine.pk}/").status_code == 404


def test_people_without_sales_access_are_refused(unilever, executive):
    clerk = person("clerk@sml.lk", "clerk", divisions=["WS"])
    assert as_user(clerk).get("/api/v1/quotations/").status_code == 403
    q = draft(executive, unilever)
    assert as_user(clerk).get(f"/api/v1/quotations/{q.pk}/").status_code == 403


# --- API --------------------------------------------------------------------------------


def body(customer, **extra):
    return {
        "customer": customer.pk,
        "division": "WS",
        "lines": [
            {
                "description": "Bush, phosphor bronze",
                "drawing_no": "UL-2210",
                "drawing_rev": "C",
                "quantity": "50",
                "unit_price": "820.00",
                "tax_code": "VAT",
                "breaks": [{"quantity": "100", "unit_price": "780.00"}],
            }
        ],
        **extra,
    }


def test_the_api_creates_lists_and_changes_quotations(executive, unilever, vat):
    client = as_user(executive)
    made = client.post("/api/v1/quotations/", body(unilever), format="json")
    assert made.status_code == 201, made.json()
    q = made.json()
    assert q["total_amount"] == "48380.00"  # 41,000.00 + VAT 7,380.00
    assert q["lines"][0]["breaks"] == [{"quantity": "100.000", "unit_price": "780.00"}]
    assert q["can_edit"] is True
    listed = client.get("/api/v1/quotations/?q=UL-2210").json()
    assert [x["number"] for x in listed] == [q["number"]]
    changed = client.put(
        f"/api/v1/quotations/{q['id']}/", body(unilever, enquiry_ref="RFQ-118"), format="json"
    )
    assert changed.status_code == 200 and changed.json()["enquiry_ref"] == "RFQ-118"
    unknown = client.post(
        "/api/v1/quotations/",
        body(unilever) | {"lines": [body(unilever)["lines"][0] | {"tax_code": "XYZ"}]},
        format="json",
    )
    assert unknown.status_code == 400 and "no tax code XYZ" in unknown.json()["detail"]


def test_drawings_are_attached_to_a_line(executive, other_executive, unilever):
    client = as_user(executive)
    q = draft(executive, unilever)
    url = f"/api/v1/quotations/{q.pk}/files/"
    added = client.post(
        url, {"file": SimpleUploadedFile("UL-2210.pdf", PDF), "line_no": "1"}, format="multipart"
    )
    assert added.status_code == 201
    stored = added.json()["files"][0]
    assert (stored["line_no"], stored["content_type"]) == (1, "application/pdf")
    assert client.get(f"{url}{stored['id']}/").status_code == 200
    wrong_line = client.post(
        url, {"file": SimpleUploadedFile("x.pdf", PDF), "line_no": "5"}, format="multipart"
    )
    assert "no line 5" in wrong_line.json()["detail"]
    not_pdf = client.post(
        url, {"file": SimpleUploadedFile("x.exe", b"MZ\x90\x00")}, format="multipart"
    )
    assert "Only PDF, JPG and PNG" in not_pdf.json()["detail"]
    removed = client.delete(f"{url}{stored['id']}/")
    assert removed.status_code == 200 and removed.json()["files"] == []
