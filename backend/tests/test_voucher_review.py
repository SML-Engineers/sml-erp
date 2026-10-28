"""The Accountant's review: coding, splits, approve / return / reject (backlog P1-03)."""

from decimal import Decimal

import pytest

from apps.accounting.models import Account
from apps.core.models import Division
from apps.masters.models import CompanyAccount, Currency
from apps.vouchers import services
from apps.vouchers.models import Voucher, VoucherType
from apps.vouchers.services import CodingInput, LineInput, SplitInput, VoucherError

from .test_access import as_user, person
from .test_vouchers import attach, draft, payee

pytestmark = pytest.mark.django_db


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
def supplier():
    return payee()


def acc(number):
    return Account.objects.get(number=number)


def div(code):
    return Division.objects.get(code=code)


@pytest.fixture
def submitted(clerk, supplier):
    voucher = draft(clerk, supplier)
    attach(clerk, voucher)
    return services.submit(clerk, voucher)


def code(user, voucher, **values):
    values.setdefault("line_no", 1)
    return services.code_lines(user, voucher, [CodingInput(**values)])


# --- The queue and the coding -----------------------------------------------------------


def test_the_accountant_sees_the_queue_and_must_code_before_approving(
    accountant, director, submitted
):
    assert list(services.waiting(accountant)) == [submitted]
    assert list(services.waiting(director)) == []
    submitted.lines.update(division=None)
    with pytest.raises(VoucherError, match="account and division before approving: line 1"):
        services.approve(accountant, submitted)
    code(accountant, submitted, account=acc("6210"), division=div("IM"), job_ref="JOB-145")
    line = submitted.lines.get()
    assert (line.account.number, line.division.code, line.job_ref) == ("6210", "IM", "JOB-145")
    voucher = services.approve(accountant, submitted, comment="coded")
    assert voucher.status == "accountant_approved"
    assert list(services.waiting(director)) == [voucher]


@pytest.mark.parametrize(
    "number, why",
    [
        ("1010", "cannot be the account"),
        ("2000", "cannot be the account"),
        ("1100", "cannot be the account"),
    ],
)
def test_a_payment_is_not_coded_to_bank_payables_or_receivables(accountant, submitted, number, why):
    with pytest.raises(VoucherError, match=why):
        code(accountant, submitted, account=acc(number), division=div("WS"))


def test_an_internal_transfer_is_coded_to_a_bank_account(clerk, accountant):
    cash = CompanyAccount.objects.create(
        code="CASH", kind="cash", name="Cash", currency=Currency.objects.get(code="LKR")
    )
    voucher = services.save(
        clerk,
        None,
        voucher_type=VoucherType.objects.get(code="INT"),
        division=div("WS"),
        transfer_to=cash,
        lines=[LineInput(amount="1000.00")],
    )
    services.submit(clerk, voucher)
    with pytest.raises(VoucherError, match="Bank-type"):
        code(accountant, voucher, account=acc("6210"), division=div("WS"))
    code(accountant, voucher, account=acc("1010"), division=div("WS"))


def test_the_accountant_changes_the_tax_and_the_total_follows(accountant, submitted):
    voucher = code(
        accountant, submitted, account=acc("6210"), division=div("WS"), tax_amount="4500.00"
    )
    assert voucher.total_amount == Decimal("29500.00")
    with pytest.raises(VoucherError, match="negative"):
        code(accountant, submitted, account=acc("6210"), division=div("WS"), tax_amount="-1")


# --- Splitting a shared bill ------------------------------------------------------------


def test_a_line_is_split_across_divisions_by_amount(accountant, submitted):
    code(
        accountant,
        submitted,
        account=acc("6100"),
        splits=[SplitInput(div("WS"), amount="15000.00"), SplitInput(div("IM"), amount="10000.00")],
    )
    line = submitted.lines.get()
    assert line.division is None
    assert [(s.division.code, s.amount) for s in line.splits.all()] == [
        ("WS", Decimal("15000.00")),
        ("IM", Decimal("10000.00")),
    ]
    assert services.uncoded_lines(submitted) == []
    assert services.approve(accountant, submitted).status == "accountant_approved"


def test_a_split_by_percent_takes_the_rounding_on_the_last_part(clerk, accountant, supplier):
    voucher = draft(clerk, supplier, LineInput(amount="100.00", invoice_no="E-1"))
    attach(clerk, voucher)
    services.submit(clerk, voucher)
    code(
        accountant,
        voucher,
        account=acc("6100"),
        splits=[
            SplitInput(div("WS"), percent="33.3333"),
            SplitInput(div("IM"), percent="33.3333"),
            SplitInput(div("HO"), percent="33.3334"),
        ],
    )
    assert [s.amount for s in voucher.lines.get().splits.all()] == [
        Decimal("33.33"),
        Decimal("33.33"),
        Decimal("33.34"),
    ]


@pytest.mark.parametrize(
    "splits, why",
    [
        (
            [("WS", "15000.00", None), ("IM", "9000.00", None)],
            "adds up to 24,000.00, not the line total 25,000.00",
        ),
        ([("WS", None, "60"), ("IM", None, "30")], "add up to 90, not 100"),
        ([("WS", "15000.00", None), ("IM", None, "40")], "not both"),
        ([("WS", None, "100")], "at least two divisions"),
        ([("WS", None, "50"), ("WS", None, "50")], "appear once"),
    ],
)
def test_a_split_must_add_up(accountant, submitted, splits, why):
    with pytest.raises(VoucherError, match=why):
        code(
            accountant,
            submitted,
            account=acc("6100"),
            splits=[SplitInput(div(d), amount=a, percent=p) for d, a, p in splits],
        )


# --- Return and reject ------------------------------------------------------------------


def test_return_and_reject_need_a_reason(accountant, submitted):
    with pytest.raises(VoucherError, match="reason"):
        services.send_back(accountant, submitted, "")
    assert (
        services.send_back(accountant, submitted, "Attach the delivery note").status == "returned"
    )


def test_a_rejected_voucher_is_final(accountant, submitted):
    with pytest.raises(VoucherError, match="reason"):
        services.reject(accountant, submitted, " ")
    assert services.reject(accountant, submitted, "Duplicate of WS261028004").status == "rejected"
    with pytest.raises(VoucherError, match="not waiting"):
        services.approve(accountant, Voucher.objects.get(pk=submitted.pk))


def test_nobody_codes_or_approves_their_own_voucher(supplier):
    maker = person("maker@sml.lk", "clerk", "accountant", all_divisions=True)
    voucher = draft(maker, supplier)
    attach(maker, voucher)
    services.submit(maker, voucher)
    with pytest.raises(VoucherError, match="created or submitted"):
        code(maker, voucher, account=acc("6210"), division=div("WS"))
    with pytest.raises(VoucherError, match="created or submitted"):
        services.approve(maker, voucher)


# --- Through the API --------------------------------------------------------------------


def test_the_review_through_the_api(clerk, accountant, submitted):
    client = as_user(accountant)
    queue = client.get("/api/v1/vouchers/waiting/").json()
    assert [row["number"] for row in queue] == [submitted.number]
    assert queue[0]["waiting_level"] == 2
    detail = client.get(f"/api/v1/vouchers/{submitted.pk}/").json()
    assert detail["can_act"] is True and detail["waiting_for"] == "Accountant"
    assert as_user(clerk).get(f"/api/v1/vouchers/{submitted.pk}/").json()["can_act"] is False
    body = {
        "lines": [
            {
                "line_no": 1,
                "account": acc("6100").pk,
                "splits": [
                    {"division": "WS", "percent": "60"},
                    {"division": "IM", "percent": "40"},
                ],
            }
        ]
    }
    coded = client.patch(f"/api/v1/vouchers/{submitted.pk}/coding/", body, format="json")
    assert coded.status_code == 200, coded.json()
    assert [s["amount"] for s in coded.json()["lines"][0]["splits"]] == ["15000.00", "10000.00"]
    assert (
        as_user(clerk)
        .post(f"/api/v1/vouchers/{submitted.pk}/approve/", {}, format="json")
        .status_code
        == 403
    )
    approved = client.post(
        f"/api/v1/vouchers/{submitted.pk}/approve/", {"comment": "ok"}, format="json"
    )
    assert approved.status_code == 200, approved.json()
    assert approved.json()["status"] == "accountant_approved"
    assert approved.json()["waiting_for"] == "Director"
    refused = client.post(f"/api/v1/vouchers/{submitted.pk}/return/", {}, format="json")
    assert refused.status_code == 400  # it waits for the Director now
