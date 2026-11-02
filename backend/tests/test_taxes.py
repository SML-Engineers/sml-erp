"""Taxes: components, dated rates and tax codes (backlog P0-20)."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import Account, TaxCode, TaxCodeLine, TaxComponent, TaxRate
from apps.accounting.services import AccountingError
from apps.core.models import AuditEvent

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
GO_LIVE = date(2024, 1, 1)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


def component(code):
    return TaxComponent.objects.get(code=code)


def code(value):
    return TaxCode.objects.get(code=value)


@pytest.fixture
def rates(accountant):
    """The rates the Accountant enters when setting up."""
    taxes.add_rate(accountant, component("SSCL"), effective_from=GO_LIVE, rate="2.125")
    taxes.add_rate(accountant, component("VAT"), effective_from=GO_LIVE, rate="18")


def test_starting_taxes_are_suggested_without_rates(accountant):
    assert {c.code for c in TaxComponent.objects.all()} == {
        "VAT",
        "SSCL",
        "SSCL-M",
        "SSCL-R",
        "WHT",
    }
    assert component("VAT").sales_account.system_role == "vat_payable"
    assert component("VAT").purchase_account.system_role == "vat_receivable"
    assert component("WHT").kind == "withheld"
    assert list(code("VAT-SSCL").lines.values_list("component__code", "base")) == [
        ("SSCL", "net"),
        ("VAT", "net_and_tax"),
    ]
    with pytest.raises(AccountingError, match="SSCL has no rate"):
        taxes.calculate(code("VAT-SSCL"), "100.00", TODAY)


def test_the_tax_invoice_example_is_calculated_exactly(rates):
    result = taxes.calculate(code("VAT-SSCL"), "115750.00", TODAY)
    assert [(line.component.code, line.base, line.amount) for line in result.lines] == [
        ("SSCL", Decimal("115750.00"), Decimal("2459.69")),
        ("VAT", Decimal("118209.69"), Decimal("21277.74")),
    ]
    assert (result.tax, result.gross) == (Decimal("23737.43"), Decimal("139487.43"))
    assert taxes.calculate(code("EXEMPT"), "500.00", TODAY).gross == Decimal("500.00")
    with pytest.raises(AccountingError, match="floating point"):
        taxes.calculate(code("VAT"), 100.1, TODAY)


def test_the_calculator_api(rates):
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    body = as_user(clerk).get("/api/v1/taxes/calculate/?code=vat-sscl&amount=115750").json()
    assert body["gross"] == "139487.43"
    assert [(line["code"], line["rate"], line["amount"]) for line in body["lines"]] == [
        ("SSCL", "2.125", "2459.69"),
        ("VAT", "18", "21277.74"),
    ]
    assert as_user(clerk).get("/api/v1/taxes/calculate/?code=NONE&amount=1").status_code == 400


def test_a_rate_applies_from_its_date(accountant, rates):
    tomorrow = TODAY + timedelta(days=1)
    taxes.add_rate(accountant, component("VAT"), effective_from=tomorrow, rate="20")
    assert taxes.calculate(code("VAT"), "100.00", TODAY).tax == Decimal("18.00")
    assert taxes.calculate(code("VAT"), "100.00", tomorrow).tax == Decimal("20.00")
    with pytest.raises(AccountingError, match="already has a rate"):
        taxes.add_rate(accountant, component("VAT"), effective_from=tomorrow, rate="19")
    assert AuditEvent.objects.filter(event="tax_rate_added").exists()


@pytest.mark.parametrize(
    "rate, why",
    [
        ("101", "between 0 and 100"),
        ("-1", "between 0 and 100"),
        ("18.12345", "four decimals"),
        ("abc", "percentage"),
        (18.0, "floating point"),
    ],
)
def test_a_rate_must_be_a_sensible_percentage(accountant, rate, why):
    with pytest.raises(AccountingError, match=why):
        taxes.add_rate(accountant, component("VAT"), effective_from=TODAY, rate=rate)


def test_once_used_a_tax_keeps_its_code_and_its_rates_in_force(accountant, rates):
    vat = component("VAT")
    taxes.mark_used(vat)
    with pytest.raises(AccountingError, match="cannot start before today"):
        taxes.add_rate(accountant, vat, effective_from=TODAY - timedelta(days=1), rate="17")
    in_force = TaxRate.objects.get(component=vat, effective_from=GO_LIVE)
    with pytest.raises(AccountingError, match="add a new rate instead"):
        taxes.remove_rate(accountant, in_force, reason="typo")
    with pytest.raises(DatabaseError), transaction.atomic():
        TaxRate.objects.filter(pk=in_force.pk).update(rate=Decimal("15"))
    with pytest.raises(AccountingError, match="code cannot change"):
        taxes.save_component(accountant, vat, {"code": "VAT18"})
    with pytest.raises(DatabaseError), transaction.atomic():
        TaxComponent.objects.filter(pk=vat.pk).update(code="VAT18")
    # a change now goes to the Director (Settings → Tax rates, P16-20); the name can change
    with pytest.raises(AccountingError, match="Settings → Tax rates"):
        taxes.add_rate(accountant, vat, effective_from=TODAY + timedelta(days=30), rate="18.5")
    taxes.propose_rate(
        accountant, vat, effective_from=TODAY + timedelta(days=30), rate="18.5", reason="Gazette"
    )
    taxes.save_component(accountant, vat, {"name": "Value Added Tax"})


def test_a_used_tax_code_keeps_its_make_up(accountant, rates):
    standard = code("VAT-SSCL")
    taxes.mark_used(standard)
    with pytest.raises(AccountingError, match="Make a new tax code"):
        taxes.save_code(accountant, standard, {"components": [{"component": component("VAT").pk}]})
    with pytest.raises(DatabaseError), transaction.atomic():
        TaxCodeLine.objects.filter(tax_code=standard).delete()
    with pytest.raises(AccountingError, match="switch it off instead"):
        taxes.delete_code(accountant, standard, reason="old")
    taxes.save_code(accountant, standard, {"is_active": False, "name": "Old standard rate"})


def test_the_accountant_makes_a_tax_code(accountant, rates):
    new = taxes.save_code(
        accountant,
        None,
        {
            "code": "sscl-only",
            "name": "SSCL only",
            "use": "sales",
            "components": [{"component": component("SSCL").pk, "base": "net_and_tax"}],
        },
    )
    assert new.code == "SSCL-ONLY"
    assert list(new.lines.values_list("base", flat=True)) == ["net"]  # nothing above the first
    assert taxes.calculate(new, "1000.00", TODAY).tax == Decimal("21.25")
    with pytest.raises(AccountingError, match="only once"):
        taxes.save_code(
            accountant,
            new,
            {"components": [{"component": component("VAT").pk}] * 2},
        )
    with pytest.raises(AccountingError, match="withheld from payments"):
        taxes.save_code(
            accountant,
            None,
            {"code": "W", "name": "W", "components": [{"component": component("WHT").pk}]},
        )
    with pytest.raises(AccountingError, match="already a tax code"):
        taxes.save_code(accountant, None, {"code": "VAT", "name": "Again"})
    taxes.delete_code(accountant, new, reason="made by mistake")
    assert not TaxCode.objects.filter(code="SSCL-ONLY").exists()


def test_the_sales_account_of_a_tax_is_a_balance_sheet_account(accountant):
    expense = Account.objects.get(number="6210")
    with pytest.raises(AccountingError, match="balance sheet"):
        taxes.save_component(accountant, component("SSCL"), {"sales_account": expense.pk})


def test_only_the_accountant_changes_taxes_but_everyone_can_read_them(accountant):
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    overview = as_user(clerk).get("/api/v1/taxes/").json()
    assert {c["code"] for c in overview["codes"]} >= {"VAT-SSCL", "EXEMPT"}
    url = f"/api/v1/taxes/components/{component('VAT').pk}/rates/"
    body = {"effective_from": TODAY.isoformat(), "rate": "18"}
    assert as_user(clerk).post(url, body, format="json").status_code == 403
    response = as_user(accountant).post(url, body, format="json")
    assert response.status_code == 201, response.json()
    vat = next(c for c in response.json()["components"] if c["code"] == "VAT")
    assert vat["current_rate"] == "18"
    with pytest.raises(AccountingError, match="Only the Accountant"):
        taxes.add_rate(clerk, component("VAT"), effective_from=TODAY, rate="18")


def test_each_account_can_have_a_default_tax_code(accountant):
    account = Account.objects.get(number="4010")
    client = as_user(accountant)
    url = f"/api/v1/chart-of-accounts/{account.pk}/"
    response = client.patch(url, {"default_tax_code": "vat-sscl"}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["default_tax_code"] == "VAT-SSCL"
    with pytest.raises(AccountingError, match="default of some accounts"):
        taxes.delete_code(accountant, code("VAT-SSCL"), reason="tidy")
    taxes.save_code(accountant, code("EXEMPT"), {"is_active": False})
    response = client.patch(url, {"default_tax_code": "EXEMPT"}, format="json")
    assert response.status_code == 400 and "switched off" in response.json()["detail"]
    assert client.patch(url, {"default_tax_code": "NOPE"}, format="json").status_code == 400


# --- SSCL on a share of the amount (P16-17) -------------------------------------------------


@pytest.fixture
def law_rates(accountant):
    """The SSCL rate of each kind of supply, as entered in Settings → Tax rates (P16-20),
    and VAT 18%."""
    taxes.add_rate(accountant, component("SSCL"), effective_from=GO_LIVE, rate="2.5")
    taxes.add_rate(accountant, component("SSCL-M"), effective_from=GO_LIVE, rate="2.125")
    taxes.add_rate(accountant, component("SSCL-R"), effective_from=GO_LIVE, rate="1.25")
    taxes.add_rate(accountant, component("VAT"), effective_from=GO_LIVE, rate="18")


def test_sscl_codes_for_each_kind_of_supply(law_rates):
    """Manufactured goods 2.125%, resold goods 1.25%, services 2.5%, each its own SSCL rate,
    all printed as SSCL. The tax invoice example comes out exactly as before."""
    made = taxes.calculate(code("VAT-SSCL-M"), "115750.00", TODAY)
    assert [(x.component.label, x.rate, x.amount) for x in made.lines] == [
        ("SSCL", Decimal("2.1250"), Decimal("2459.69")),
        ("VAT", Decimal("18.0000"), Decimal("21277.74")),
    ]
    assert made.gross == Decimal("139487.43")
    resold = taxes.calculate(code("VAT-SSCL-R"), "1000.00", TODAY)
    assert [x.amount for x in resold.lines] == [Decimal("12.50"), Decimal("182.25")]
    services = taxes.calculate(code("VAT-SSCL"), "1000.00", TODAY)
    assert [x.amount for x in services.lines] == [Decimal("25.00"), Decimal("184.50")]
    assert code("VAT-SSCL").name == "Services: SSCL on 100%, then VAT"
    assert {code("VAT-SSCL-M").use, code("VAT-SSCL-R").use} == {"both"}
    assert list(code("VAT-SSCL-M").lines.values_list("component__code", "portion_pct")) == [
        ("SSCL-M", Decimal("100.00")),
        ("VAT", Decimal("100.00")),
    ]


def test_the_share_is_set_on_a_tax_code_and_fixed_once_used(accountant, law_rates):
    new = taxes.save_code(
        accountant,
        None,
        {
            "code": "SSCL-30",
            "name": "SSCL on 30%",
            "components": [{"component": component("SSCL").pk, "portion_pct": "30"}],
        },
    )
    assert taxes.calculate(new, "1000.00", TODAY).tax == Decimal("7.50")
    for bad, why in (("0", "more than 0%"), ("101", "up to 100%"), ("x", "not a number")):
        with pytest.raises(AccountingError, match=why):
            taxes.save_code(
                accountant,
                new,
                {"components": [{"component": component("SSCL").pk, "portion_pct": bad}]},
            )
    taxes.mark_used(new)
    with pytest.raises(AccountingError, match="cannot change"):
        taxes.save_code(
            accountant,
            new,
            {"components": [{"component": component("SSCL").pk, "portion_pct": "40"}]},
        )
    with pytest.raises(DatabaseError):
        with transaction.atomic():
            TaxCodeLine.objects.filter(tax_code=new).update(portion_pct="40")
    listed = as_user(accountant).get("/api/v1/taxes/").json()
    mine = next(c for c in listed["codes"] if c["code"] == "SSCL-30")
    assert mine["components"][0]["portion_pct"] == "30.00"
