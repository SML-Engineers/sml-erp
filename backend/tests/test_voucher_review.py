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
    # P3-13: the job reference is a job or production order number that exists.
    with pytest.raises(
        VoucherError, match="Line 1: There is no job order or production order JOB-145"
    ):
        code(accountant, submitted, account=acc("6210"), division=div("IM"), job_ref="JOB-145")
    code(accountant, submitted, account=acc("6210"), division=div("IM"))
    line = submitted.lines.get()
    assert (line.account.number, line.division.code, line.job_ref) == ("6210", "IM", "")
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
    from datetime import date

    from apps.accounting import taxes
    from apps.accounting.models import TaxCode, TaxComponent

    vat = TaxComponent.objects.get(code="VAT")
    taxes.add_rate(accountant, vat, effective_from=date(2024, 1, 1), rate="18")
    voucher = code(
        accountant,
        submitted,
        account=acc("6210"),
        division=div("WS"),
        tax_code=TaxCode.objects.get(code="VAT"),
    )
    assert voucher.total_amount == Decimal("29500.00")
    # Owner, 18 Nov 2026: tax comes only from a tax code, never typed in.
    with pytest.raises(VoucherError, match="choose the tax code for its tax"):
        code(accountant, submitted, account=acc("6210"), division=div("WS"), tax_amount="4500.00")


def test_a_voucher_with_tax_typed_in_before_needs_its_tax_code(accountant, submitted):
    from apps.accounting.models import TaxCode

    # A voucher entered before 18 Nov 2026 may hold tax typed in without a code.
    code(accountant, submitted, account=acc("6210"), division=div("WS"))
    submitted.lines.update(tax_amount=Decimal("360.00"))
    with pytest.raises(VoucherError, match="Choose the tax code for the tax before approving"):
        services.approve(accountant, submitted)
    assert services.uncoded_lines(submitted) == [1]
    no_tax = code(
        accountant,
        submitted,
        account=acc("6210"),
        division=div("WS"),
        tax_code=TaxCode.objects.get(code="NO-TAX"),
    )
    assert no_tax.lines.get().tax_amount == Decimal("0.00")
    assert services.approve(accountant, no_tax).status == "accountant_approved"


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


def test_nobody_codes_or_approves_their_own_voucher(accountant, supplier):
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


# --- The Director sends it back to the Accountant ---------------------------------------


def test_the_director_sends_a_voucher_back_to_the_accountant(
    clerk, accountant, director, submitted
):
    from apps.core.models import Notification

    with pytest.raises(VoucherError, match="already waiting for the Accountant"):
        services.send_to_accountant(accountant, submitted, "Check the account")
    code(accountant, submitted, account=acc("6210"), division=div("WS"))
    services.approve(accountant, submitted)
    Notification.objects.all().delete()
    with pytest.raises(VoucherError, match="Say what the Accountant should check"):
        services.send_to_accountant(director, submitted, "  ")
    with pytest.raises(VoucherError):
        services.send_to_accountant(clerk, submitted, "Check the account")
    back = services.send_to_accountant(director, submitted, "Code this to repairs, not fuel")
    assert back.status == "submitted"
    assert [v.pk for v in services.waiting(accountant)] == [submitted.pk]
    assert list(services.waiting(director)) == []
    # every Accountant who can approve is told; the Clerk is not
    assert Notification.objects.filter(user=accountant).exists()
    assert not Notification.objects.filter(user=clerk).exists()
    # the Accountant approves again and it is back with the Director
    assert services.approve(accountant, back).status == "accountant_approved"
    assert [v.pk for v in services.waiting(director)] == [submitted.pk]


def test_sending_back_to_the_accountant_through_the_api(accountant, director, submitted):
    code(accountant, submitted, account=acc("6210"), division=div("WS"))
    services.approve(accountant, submitted)
    client = as_user(director)
    detail = client.get(f"/api/v1/vouchers/{submitted.pk}/").json()
    assert detail["can_send_to_accountant"] is True
    url = f"/api/v1/vouchers/{submitted.pk}/back-to-accountant/"
    assert as_user(accountant).post(url, {"reason": "x"}, format="json").status_code == 400
    assert client.post(url, {}, format="json").status_code == 400
    sent = client.post(url, {"reason": "Wrong division"}, format="json")
    assert sent.status_code == 200, sent.json()
    assert sent.json()["waiting_for"] == "Accountant"
    last = sent.json()["approvals"][-1]
    assert last["action"] == "to_accountant" and last["reason"] == "Wrong division"
    seen = as_user(accountant).get(f"/api/v1/vouchers/{submitted.pk}/").json()
    assert seen["can_act"] is True and seen["can_send_to_accountant"] is False


def test_the_only_accountant_cannot_submit_her_own_voucher(director, supplier):
    """Testing T51 (owner, 22 Nov 2026): nobody else could approve it at L2; the Clerk enters
    it instead. The voucher stays a draft."""
    kumari = person("kumari@sml.lk", "clerk", "accountant", all_divisions=True)
    voucher = draft(kumari, supplier)
    attach(kumari, voucher)
    with pytest.raises(VoucherError, match="the Accounts Clerk"):
        services.submit(kumari, voucher)
    voucher.refresh_from_db()
    assert voucher.status == "draft" and voucher.submitted_at is None
