"""The Director's approval page: several decisions confirmed together (backlog P1-04)."""

import pytest

from apps.accounting.models import Account
from apps.core.models import Division
from apps.vouchers import services
from apps.vouchers.models import Voucher
from apps.vouchers.services import BulkRefused, CodingInput, Decision, LineInput

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


def at_director(clerk, accountant, amount="1000.00", code="S0001", comment="ok"):
    """A voucher submitted, coded and approved by the Accountant: waiting at L3."""
    voucher = draft(clerk, payee(code=code), LineInput(amount=amount, invoice_no=f"I-{code}"))
    attach(clerk, voucher, content=b"%PDF-1.7 " + code.encode())
    services.submit(clerk, voucher)
    services.code_lines(
        accountant,
        voucher,
        [
            CodingInput(
                line_no=1,
                account=Account.objects.get(number="6210"),
                division=Division.objects.get(code="WS"),
            )
        ],
    )
    return services.approve(accountant, voucher, comment)


def test_the_director_approves_and_rejects_several_at_once(clerk, accountant, director):
    first = at_director(clerk, accountant, code="S0001")
    second = at_director(clerk, accountant, code="S0002")
    third = at_director(clerk, accountant, code="S0003")
    done = services.decide_many(
        director,
        [
            Decision(first.pk, "approve"),
            Decision(second.pk, "approve", "fine"),
            Decision(third.pk, "reject", "Supplier already paid in cash"),
        ],
    )
    statuses = {v.pk: Voucher.objects.get(pk=v.pk).status for v in done}
    assert statuses == {
        first.pk: "director_approved",
        second.pk: "director_approved",
        third.pk: "rejected",
    }


def test_a_reject_without_a_reason_stops_the_whole_confirmation(clerk, accountant, director):
    first = at_director(clerk, accountant, code="S0001")
    second = at_director(clerk, accountant, code="S0002")
    with pytest.raises(BulkRefused) as refused:
        services.decide_many(
            director, [Decision(first.pk, "approve"), Decision(second.pk, "reject", "  ")]
        )
    assert refused.value.errors == {second.pk: "Give a reason for rejecting."}
    assert Voucher.objects.get(pk=first.pk).status == "accountant_approved"  # nothing confirmed


def test_a_voucher_not_waiting_for_the_director_stops_the_whole_confirmation(
    clerk, accountant, director
):
    ready = at_director(clerk, accountant, code="S0001")
    early = draft(clerk, payee(code="S0002"), LineInput(amount="50.00"))
    attach(clerk, early, content=b"%PDF-1.7 early")
    services.submit(clerk, early)  # still waiting for the Accountant
    with pytest.raises(BulkRefused) as refused:
        services.decide_many(
            director, [Decision(ready.pk, "approve"), Decision(early.pk, "approve")]
        )
    assert list(refused.value.errors) == [early.pk]
    assert "approved by the Accountant" in refused.value.errors[early.pk]
    assert Voucher.objects.get(pk=ready.pk).status == "accountant_approved"


def test_the_director_page_through_the_api(clerk, accountant, director):
    first = at_director(clerk, accountant, code="S0001", comment="coded to machine repairs")
    second = at_director(clerk, accountant, code="S0002")
    client = as_user(director)
    rows = client.get("/api/v1/vouchers/waiting/").json()
    assert {r["number"] for r in rows} == {first.number, second.number}
    row = next(r for r in rows if r["id"] == first.pk)
    assert row["waiting_level"] == 3 and row["last_comment"] == "coded to machine repairs"
    assert row["division"] == "WS" and row["total_amount"] == "1000.00"
    refused = client.post(
        "/api/v1/vouchers/decisions/",
        {
            "decisions": [
                {"id": first.pk, "decision": "approve"},
                {"id": second.pk, "decision": "reject"},
            ]
        },
        format="json",
    )
    assert refused.status_code == 400
    assert refused.json()["errors"] == {str(second.pk): "Give a reason for rejecting."}
    done = client.post(
        "/api/v1/vouchers/decisions/",
        {
            "decisions": [
                {"id": first.pk, "decision": "approve"},
                {"id": second.pk, "decision": "reject", "reason": "duplicate"},
            ]
        },
        format="json",
    ).json()
    assert (done["approved"], done["rejected"]) == (1, 1)
    assert done["fully_approved"] == [first.number]
    assert client.get("/api/v1/vouchers/waiting/").json() == []
    assert (
        as_user(clerk)
        .post("/api/v1/vouchers/decisions/", {"decisions": []}, format="json")
        .status_code
        == 403
    )
