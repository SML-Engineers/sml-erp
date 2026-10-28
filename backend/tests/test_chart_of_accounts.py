"""Chart of accounts, QuickBooks style (backlog P0-15, spec 3)."""

import io
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError, IntegrityError
from openpyxl import Workbook, load_workbook

from apps.accounting import excel, services
from apps.accounting.catalogue import SYSTEM_ROLES, TYPES
from apps.accounting.models import Account, DetailType
from apps.accounting.services import AccountingError
from apps.core.models import AuditEvent, Division
from apps.masters import banking
from apps.masters.services import MastersError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

URL = "/api/v1/chart-of-accounts/"


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


def acc(number):
    return Account.objects.get(number=number)


def detail(account_type, name):
    return DetailType.objects.get(account_type=account_type, name=name)


def new(user, name, account_type="expense", detail_name="Repairs and maintenance", **extra):
    return services.create_account(
        user,
        name=name,
        account_type=account_type,
        detail_type=detail(account_type, detail_name),
        **extra,
    )


# --- Starter chart ----------------------------------------------------------------------


def test_the_starter_chart_and_system_accounts_are_loaded():
    roles = dict(Account.objects.exclude(system_role="").values_list("system_role", "account_type"))
    assert set(roles) == set(SYSTEM_ROLES)
    assert roles["accounts_payable"] == "accounts_payable"
    assert roles["accounts_receivable"] == "accounts_receivable"
    assert roles["retained_earnings"] == roles["opening_balance_equity"] == "equity"
    assert Account.objects.filter(number="6210", parent__number="6200").exists()
    # every type has detail types to choose from
    assert set(DetailType.objects.values_list("account_type", flat=True)) == set(TYPES)


def test_the_chart_lists_accounts_by_type_then_number_as_a_tree(accountant):
    rows = as_user(accountant).get(URL).json()
    types = [r["account_type"] for r in rows]
    order = list(TYPES)
    assert types == sorted(types, key=order.index)
    repairs = next(i for i, r in enumerate(rows) if r["number"] == "6200")
    assert rows[repairs + 1]["full_name"] == "Repairs and maintenance:Machine repairs"
    assert rows[repairs + 1]["depth"] == 1
    payable = next(r for r in rows if r["number"] == "2000")
    assert payable["system_role"] == "accounts_payable"
    assert payable["section"] == "liabilities"


# --- Adding and changing accounts -------------------------------------------------------


def test_the_accountant_adds_accounts_and_sub_accounts_to_any_depth(accountant):
    cnc = new(accountant, "CNC machines", parent=acc("6210"), number="6211")
    deeper = new(accountant, "Spindle repairs", parent=cnc)
    assert services.full_name(deeper) == (
        "Repairs and maintenance:Machine repairs:CNC machines:Spindle repairs"
    )
    assert deeper.number == ""  # numbers are optional
    assert AuditEvent.objects.filter(event="account_created").exists()


def test_a_sub_account_must_have_the_type_of_its_parent(accountant):
    with pytest.raises(AccountingError, match="same type as its parent"):
        new(accountant, "Bank repairs", parent=acc("1010"))  # expense under a bank account
    machine_repairs = acc("6210")
    with pytest.raises(AccountingError, match="same type as its parent"):
        services.update_account(
            accountant,
            machine_repairs,
            {
                "account_type": "other_expense",
                "detail_type": detail("other_expense", "Interest paid"),
            },
        )
    response = as_user(accountant).post(
        URL,
        {
            "name": "Bank repairs",
            "account_type": "expense",
            "detail_type": detail("expense", "Repairs and maintenance").pk,
            "parent": acc("1010").pk,
        },
        format="json",
    )
    assert response.status_code == 400
    assert "same type" in response.json()["detail"]


def test_names_are_unique_within_the_same_parent(accountant):
    with pytest.raises(AccountingError, match="already an account called"):
        new(accountant, "machine REPAIRS", parent=acc("6200"))
    # the same name elsewhere is fine
    assert new(accountant, "Machine repairs").parent is None
    with pytest.raises(AccountingError, match="already an account called"):
        new(accountant, "Machine Repairs")


def test_numbers_are_optional_unique_and_well_formed(accountant):
    with pytest.raises(AccountingError, match="already used by Machine repairs"):
        new(accountant, "Mould repairs", number="6210")
    with pytest.raises(AccountingError, match="1 to 20 letters"):
        new(accountant, "Mould repairs", number="62 10")
    with pytest.raises(AccountingError, match="colon"):
        new(accountant, "Repairs:moulds")
    assert new(accountant, "Mould repairs", number="6240a").number == "6240A"


def test_the_detail_type_must_belong_to_the_account_type(accountant):
    with pytest.raises(AccountingError, match="not a detail type of Expense"):
        services.create_account(
            accountant,
            name="Generator",
            account_type="expense",
            detail_type=detail("fixed_asset", "Machinery and equipment"),
        )


def test_the_type_changes_while_the_account_stays_consistent(accountant):
    account = new(accountant, "Generator hire")
    services.update_account(
        accountant,
        account,
        {
            "account_type": "cost_of_goods_sold",
            "detail_type": detail("cost_of_goods_sold", "Factory overheads"),
        },
    )
    assert Account.objects.get(pk=account.pk).account_type == "cost_of_goods_sold"
    with pytest.raises(AccountingError, match="has sub-accounts"):
        services.update_account(
            accountant,
            acc("6200"),
            {
                "account_type": "other_expense",
                "detail_type": detail("other_expense", "Interest paid"),
            },
        )


def test_a_sub_account_moves_and_cannot_become_its_own_ancestor(accountant):
    machine_repairs = acc("6210")
    cnc = new(accountant, "CNC machines", parent=machine_repairs)
    with pytest.raises(AccountingError, match="itself or its own sub-account"):
        services.update_account(accountant, machine_repairs, {"parent": cnc})
    services.update_account(accountant, cnc, {"parent": acc("6200")})
    assert Account.objects.get(pk=cnc.pk).parent.number == "6200"


def test_only_the_accountant_changes_the_chart():
    director = person("director@sml.lk", "director", all_divisions=True)
    admin = person("admin@sml.lk", "system_admin", all_divisions=True)
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert as_user(director).get(URL).status_code == 200
    body = {"name": "X", "account_type": "expense", "detail_type": 1}
    assert as_user(director).post(URL, body, format="json").status_code == 403
    assert as_user(admin).get(URL).status_code == 403
    assert as_user(clerk).get(URL).status_code == 403
    with pytest.raises(AccountingError, match="Only the Accountant"):
        new(director, "Anything")


# --- Inactive, delete -------------------------------------------------------------------


def test_an_unused_account_set_up_by_mistake_can_be_deleted(accountant):
    account = new(accountant, "Mistake")
    with pytest.raises(AccountingError, match="reason"):
        services.delete_account(accountant, account, "")
    response = as_user(accountant).delete(
        f"{URL}{account.pk}/", {"reason": "typed twice"}, format="json"
    )
    assert response.status_code == 204
    assert not Account.objects.filter(pk=account.pk).exists()


def test_an_account_with_transactions_cannot_be_deleted_only_made_inactive(accountant):
    account = new(accountant, "Generator repairs", parent=acc("6210"))
    services.mark_used(account)
    with pytest.raises(AccountingError, match="make it inactive instead"):
        services.delete_account(accountant, account, "no longer needed")
    with pytest.raises(DatabaseError), transaction.atomic():
        Account.objects.filter(pk=account.pk).delete()
    services.update_account(accountant, account, {"is_active": False}, "no longer needed")
    assert not Account.objects.get(pk=account.pk).is_active


def test_a_used_account_keeps_its_number(accountant):
    account = new(accountant, "Generator repairs", number="6240")
    services.mark_used(account)
    with pytest.raises(AccountingError, match="number 6240 cannot change"):
        services.update_account(accountant, account, {"number": "6250"})
    with pytest.raises(DatabaseError), transaction.atomic():
        Account.objects.filter(pk=account.pk).update(number="6250")
    services.update_account(accountant, account, {"name": "Generator and pump repairs"})
    unnumbered = new(accountant, "Pump repairs")
    services.mark_used(unnumbered)
    services.update_account(accountant, unnumbered, {"number": "6260"})  # a first number


def test_making_an_account_inactive_needs_a_reason_and_includes_its_sub_accounts(accountant):
    parent = acc("6200")
    with pytest.raises(AccountingError, match="reason"):
        services.update_account(accountant, parent, {"is_active": False})
    services.update_account(accountant, parent, {"is_active": False}, "restructured")
    assert not Account.objects.filter(parent=parent, is_active=True).exists()
    with pytest.raises(AccountingError, match="parent account Repairs and maintenance"):
        services.update_account(accountant, acc("6210"), {"is_active": True})
    services.update_account(accountant, parent, {"is_active": True})
    services.update_account(accountant, acc("6210"), {"is_active": True})
    assert AuditEvent.objects.filter(event="account_made_inactive").exists()
    active = [r["number"] for r in as_user(accountant).get(URL).json()]
    assert "6210" in active and "6220" not in active


def test_system_accounts_cannot_be_removed_or_retyped(accountant):
    payable = Account.objects.get(system_role="accounts_payable")
    with pytest.raises(AccountingError, match="needed by the system"):
        services.delete_account(accountant, payable, "tidy up")
    with pytest.raises(AccountingError, match="needed by the system"):
        services.update_account(accountant, payable, {"is_active": False}, "tidy up")
    with pytest.raises(AccountingError, match="keeps its type"):
        services.update_account(
            accountant,
            payable,
            {
                "account_type": "other_current_liability",
                "detail_type": detail("other_current_liability", "Accrued expenses"),
            },
        )
    services.update_account(accountant, payable, {"name": "Trade creditors"})  # renaming is fine
    for change in ({"is_active": False}, {"system_role": ""}, {"account_type": "equity"}):
        with pytest.raises(DatabaseError), transaction.atomic():
            Account.objects.filter(pk=payable.pk).update(**change)
    with pytest.raises(DatabaseError), transaction.atomic():
        Account.objects.filter(pk=payable.pk).delete()


def test_a_parent_holding_a_system_account_cannot_be_made_inactive(accountant):
    taxes = new(
        accountant,
        "Taxes payable",
        account_type="other_current_liability",
        detail_name="Other current liability",
    )
    vat = Account.objects.get(system_role="vat_payable")
    services.update_account(accountant, vat, {"parent": taxes})
    with pytest.raises(AccountingError, match="VAT payable is needed by the system"):
        services.update_account(accountant, taxes, {"is_active": False}, "x")


# --- Merging ----------------------------------------------------------------------------


def test_merging_moves_the_history_and_keeps_the_totals(accountant):
    duplicate = new(accountant, "Machine maintenance", number="6215")
    services.mark_used(duplicate)
    cnc = new(accountant, "CNC", parent=duplicate)
    target = acc("6210")
    response = as_user(accountant).post(
        f"{URL}{duplicate.pk}/merge/",
        {"into": target.pk, "reason": "same thing entered twice"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    duplicate.refresh_from_db()
    assert duplicate.merged_into == target and not duplicate.is_active
    assert Account.objects.get(pk=cnc.pk).parent == target  # sub-accounts move too
    assert Account.objects.get(pk=target.pk).first_used_at is not None
    assert services.surviving(duplicate.pk) == target.pk
    # Posted entries are never rewritten (rule 3); reports count them under the target.
    other = acc("6220")
    totals = {
        duplicate.pk: Decimal("1500.00"),
        target.pk: Decimal("250.50"),
        other.pk: Decimal("10"),
    }
    rolled = services.roll_up(totals)
    assert rolled == {target.pk: Decimal("1750.50"), other.pk: Decimal("10")}
    assert sum(rolled.values()) == sum(totals.values())
    assert AuditEvent.objects.filter(event="account_merged").exists()


def test_a_merge_cannot_be_undone(accountant):
    duplicate = new(accountant, "Machine maintenance")
    services.merge_accounts(accountant, duplicate, acc("6210"), "duplicate")
    with pytest.raises((DatabaseError, IntegrityError)), transaction.atomic():
        Account.objects.filter(pk=duplicate.pk).update(merged_into=None, merged_at=None)
    with pytest.raises(DatabaseError), transaction.atomic():
        Account.objects.filter(pk=duplicate.pk).update(is_active=True)
    with pytest.raises(AccountingError, match="was merged"):
        services.update_account(accountant, duplicate, {"name": "Back"})
    with pytest.raises(AccountingError, match="already merged"):
        services.merge_accounts(accountant, duplicate, acc("6220"), "again")


@pytest.mark.parametrize(
    "source, target, why",
    [
        ("6210", "6210", "two different"),
        ("6210", "1010", "same type"),
        ("6200", "6210", "sub-account of Repairs"),
        ("2000", "2170", "needed by the system"),
    ],
)
def test_a_merge_must_make_sense(accountant, source, target, why):
    with pytest.raises(AccountingError, match=why):
        services.merge_accounts(accountant, acc(source), acc(target), "test")


def test_a_merge_needs_a_reason_and_no_clashing_sub_accounts(accountant):
    with pytest.raises(AccountingError, match="reason"):
        services.merge_accounts(accountant, acc("6230"), acc("6220"), "")
    vehicles = new(accountant, "Vehicle upkeep")
    new(accountant, "Tyres", parent=vehicles)
    new(accountant, "Tyres", parent=acc("6230"))
    with pytest.raises(AccountingError, match="already has sub-accounts called Tyres"):
        services.merge_accounts(accountant, vehicles, acc("6230"), "duplicate")


# --- Detail types -----------------------------------------------------------------------


def test_the_detail_type_list_is_editable(accountant):
    client = as_user(accountant)
    response = client.post(
        f"{URL}detail-types/", {"account_type": "expense", "name": "Mould polishing"}, format="json"
    )
    assert response.status_code == 201, response.json()
    pk = response.json()["id"]
    duplicate = client.post(
        f"{URL}detail-types/", {"account_type": "expense", "name": "mould POLISHING"}, format="json"
    )
    assert duplicate.status_code == 400
    assert (
        client.patch(f"{URL}detail-types/{pk}/", {"name": "Mould care"}, format="json").json()[
            "name"
        ]
        == "Mould care"
    )
    assert client.delete(f"{URL}detail-types/{pk}/").status_code == 204
    used = detail("expense", "Electricity")
    response = client.delete(f"{URL}detail-types/{used.pk}/")
    assert response.status_code == 400 and "make it inactive" in response.json()["detail"]
    client.patch(f"{URL}detail-types/{used.pk}/", {"is_active": False}, format="json")
    with pytest.raises(AccountingError, match="inactive"):
        new(accountant, "Generator power", detail_name="Electricity")
    types = client.get(f"{URL}types/").json()
    assert [t["code"] for t in types] == list(TYPES)
    assert types[0]["section_label"] == "Balance sheet: assets"


# --- Excel ------------------------------------------------------------------------------


def _workbook(rows) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Accounts"
    sheet.append(excel.COLUMNS)
    for row in rows:
        sheet.append(row)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def test_the_chart_exports_and_imports_unchanged(accountant):
    response = as_user(accountant).get(f"{URL}export/")
    assert response.status_code == 200
    content = response.content
    sheet = load_workbook(io.BytesIO(content))["Accounts"]
    rows = list(sheet.iter_rows(values_only=True))
    assert list(rows[0]) == excel.COLUMNS
    assert ("6210", "Machine repairs", "Repairs and maintenance") == rows[1:][
        [r[0] for r in rows[1:]].index("6210")
    ][:3]
    counts = excel.import_workbook(content, reason="round trip", user=accountant, dry_run=False)
    assert counts["created"] == counts["updated"] == counts["detail_types_created"] == 0
    assert counts["unchanged"] == Account.objects.count()


def test_an_existing_chart_is_loaded_from_excel_in_one_step(accountant):
    content = _workbook(
        [
            # sub-accounts may come before their parents
            [
                "6211",
                "CNC machines",
                "Repairs and maintenance:Machine repairs and servicing",
                "Expense",
                "Repairs and maintenance",
                "",
                "WS",
                "Yes",
            ],
            ["1030", "Sampath current", "", "Bank", "Current account", "", "", "Yes"],
            ["9000", "Suspense", "", "Other current asset", "Suspense account", "", "", "No"],
            [
                "6210",
                "Machine repairs and servicing",
                "Repairs and maintenance",
                "Expense",
                "Repairs and maintenance",
                "",
                "",
                "Yes",
            ],
        ]
    )
    before = Account.objects.count()
    checked = excel.import_workbook(content, reason="load", user=accountant, dry_run=True)
    assert checked["created"] == 3 and Account.objects.count() == before
    counts = excel.import_workbook(content, reason="load", user=accountant, dry_run=False)
    assert counts == {"created": 3, "updated": 1, "unchanged": 0, "detail_types_created": 1}
    cnc = acc("6211")
    assert cnc.parent == acc("6210") and cnc.default_division == Division.objects.get(code="WS")
    assert acc("6210").name == "Machine repairs and servicing"
    assert not acc("9000").is_active


def test_an_import_with_any_refused_row_saves_nothing(accountant):
    content = _workbook(
        [
            ["1031", "HNB current", "", "Bank", "Current account", "", "", "Yes"],
            [
                "6290",
                "Bank repairs",
                "Cash on hand",
                "Expense",
                "Repairs and maintenance",
                "",
                "",
                "Yes",
            ],
            ["6291", "Loans", "", "Loan", "x", "", "", "Yes"],
            ["6292", "Ghost", "Nowhere", "Expense", "Rent", "", "", "Yes"],
        ]
    )
    before = Account.objects.count()
    with pytest.raises(excel.ImportRefused) as refused:
        excel.import_workbook(content, reason="load", user=accountant, dry_run=False)
    assert Account.objects.count() == before
    text = " | ".join(refused.value.errors)
    assert "Row 3:" in text and "same type" in text
    assert "Row 4:" in text and "Type must be one of" in text
    assert "Row 5:" in text and "Unknown parent account Nowhere" in text


def test_the_import_page_refuses_without_a_file_or_reason(accountant):
    client = as_user(accountant)
    assert client.post(f"{URL}import/", {}, format="multipart").status_code == 400
    upload = io.BytesIO(
        _workbook([["1032", "BOC current", "", "Bank", "Current account", "", "", ""]])
    )
    upload.name = "chart.xlsx"
    response = client.post(f"{URL}import/", {"file": upload}, format="multipart")
    assert response.status_code == 400 and "reason" in str(response.json())


# --- Links to other records -------------------------------------------------------------


def test_a_company_bank_account_is_linked_to_a_bank_ledger(accountant):
    ledger = new(
        accountant, "Commercial Bank current", account_type="bank", detail_name="Current account"
    )
    with pytest.raises(MastersError, match="type Bank"):
        banking.create_account(
            accountant, code="CASH", kind="cash", name="Cash", ledger_account=acc("6210").pk
        )
    current = banking.create_account(
        accountant,
        code="COM-CUR",
        kind="current",
        name="Commercial Bank current",
        bank_name="Commercial Bank",
        account_number="1000234567",
        ledger_account=ledger.pk,
    )
    assert current.ledger_account == ledger
    with pytest.raises(MastersError, match="already belongs to COM-CUR"):
        banking.create_account(
            accountant, code="CASH", kind="cash", name="Cash", ledger_account=ledger.pk
        )
    with pytest.raises(AccountingError, match="close it first"):
        services.update_account(accountant, ledger, {"is_active": False}, "x")
    with pytest.raises(AccountingError, match="stays a Bank account"):
        services.update_account(
            accountant,
            ledger,
            {
                "account_type": "other_current_asset",
                "detail_type": detail("other_current_asset", "Other current asset"),
            },
        )
    rows = as_user(accountant).get("/api/v1/company-accounts/ledgers/").json()
    assert {"id": ledger.pk, "number": "", "name": ledger.name, "linked_to": "COM-CUR"} in rows
    listed = as_user(accountant).get("/api/v1/company-accounts/").json()
    assert listed[0]["ledger_account"]["name"] == "Commercial Bank current"
    # merging the ledger into another bank ledger carries the link along
    services.merge_accounts(accountant, ledger, acc("1010"), "one ledger for the bank")
    current.refresh_from_db()
    assert current.ledger_account == acc("1010")


def test_a_division_used_as_an_account_default_cannot_be_deleted(accountant):
    from apps.core import organisation

    tool_shop = Division.objects.create(code="TS", name="Tool Shop")
    new(accountant, "Tool shop repairs", default_division=tool_shop)
    with pytest.raises(organisation.OrganisationError, match="linked to"):
        organisation.delete_division(tool_shop, reason="set up by mistake")
