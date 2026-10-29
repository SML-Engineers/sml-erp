"""Cancelling an approved, unpaid voucher: the Accountant requests, the Director approves
(backlog P1-06, spec 4.2)."""

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.core import approvals
from apps.core.models import Notification
from apps.vouchers import services
from apps.vouchers.models import Voucher, VoucherCancellation
from apps.vouchers.services import LineInput, VoucherError

from .test_access import as_user, person
from .test_voucher_amendments import approved
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
def voucher(clerk, accountant, director):
    return approved(clerk, accountant, director)


def fresh(v):
    return Voucher.objects.get(pk=v.pk)


def test_only_the_accountant_requests_and_only_for_an_approved_unpaid_voucher(
    clerk, accountant, director, voucher
):
    with pytest.raises(VoucherError, match="Say why"):
        services.request_cancellation(accountant, voucher, " ")
    for someone in (clerk, director):
        with pytest.raises(VoucherError, match="Only the Accountant"):
            services.request_cancellation(someone, voucher, "Supplier will not deliver")
    in_approval = draft(clerk, payee(code="S0002"), LineInput(amount="50.00"))
    attach(clerk, in_approval, content=b"%PDF-1.7 other")
    services.submit(clerk, in_approval)
    with pytest.raises(VoucherError, match="rejected instead"):
        services.request_cancellation(accountant, fresh(in_approval), "no")
    assert "cancel" in services.actions(accountant, voucher)
    assert "cancel" not in services.actions(clerk, voucher)


def test_while_waiting_the_voucher_cannot_be_amended_or_deleted(
    clerk, accountant, director, voucher
):
    services.request_cancellation(accountant, voucher, "Supplier will not deliver")
    state = approvals.state_of("voucher_cancellation", voucher.cancellations.get().pk)
    assert state.route == [{"level": 2, "role": "director", "role_name": "Director"}]
    assert Notification.objects.filter(user=director, event="approval_waiting").exists()
    with pytest.raises(VoucherError, match="already waiting"):
        services.request_cancellation(accountant, voucher, "again")
    with pytest.raises(VoucherError, match="waiting for the Director"):
        services.amend(clerk, voucher, "change")
    with pytest.raises(VoucherError, match="waiting for the Director"):
        services.delete(director, voucher, "duplicate")
    assert services.actions(accountant, voucher) == ["resources", "print"]
    assert fresh(voucher).status == "director_approved"


def test_the_director_approves_and_the_voucher_is_cancelled_for_good(accountant, director, voucher):
    request = services.request_cancellation(accountant, voucher, "Supplier will not deliver")
    assert not services.can_decide(accountant, request)
    assert services.can_decide(director, request)
    with pytest.raises(VoucherError):
        services.decide_cancellation(accountant, request, True)
    services.decide_cancellation(director, request, True, "agreed")

    request.refresh_from_db()
    assert (request.status, request.decided_by, request.decision_reason) == (
        "approved",
        director,
        "agreed",
    )
    voucher = fresh(voucher)
    assert voucher.status == "cancelled"
    assert services.actions(director, voucher) == ["resources", "print", "delete"]
    assert services.payee_balance(voucher.payee)["approved_unpaid"] == "0.00"
    with pytest.raises(VoucherError, match="already been decided"):
        services.decide_cancellation(director, request, False, "no")
    with pytest.raises(DatabaseError, match="cancelled for good"), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(status="director_approved")


def test_the_director_rejects_with_a_reason_and_the_voucher_stands(accountant, director, voucher):
    request = services.request_cancellation(accountant, voucher, "Duplicate of another bill")
    with pytest.raises(VoucherError, match="reason"):
        services.decide_cancellation(director, request, False, "")
    services.decide_cancellation(director, request, False, "Not a duplicate; pay it")
    request.refresh_from_db()
    assert request.status == "rejected"
    assert fresh(voucher).status == "director_approved"
    services.request_cancellation(accountant, fresh(voucher), "Asked again")  # allowed again
    assert VoucherCancellation.objects.filter(voucher=voucher).count() == 2


def test_a_voucher_with_payments_is_never_cancelled(accountant, director, voucher):
    request = services.request_cancellation(accountant, voucher, "Supplier will not deliver")
    Voucher.objects.filter(pk=voucher.pk).update(status="partly_paid")  # as payments will
    with pytest.raises(VoucherError, match="has payments"):
        services.decide_cancellation(director, request, True)
    with pytest.raises(VoucherError, match="has payments"):
        services.request_cancellation(accountant, fresh(voucher), "x")
    with pytest.raises(DatabaseError, match="has payments"), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(status="cancelled")


def test_cancellation_through_the_api(accountant, director, voucher):
    assert (
        as_user(director)
        .post(f"/api/v1/vouchers/{voucher.pk}/cancel/", {"reason": "x"}, format="json")
        .status_code
        == 400
    )
    asked = as_user(accountant).post(
        f"/api/v1/vouchers/{voucher.pk}/cancel/", {"reason": "Order withdrawn"}, format="json"
    )
    assert asked.status_code == 200
    assert asked.json()["cancellation"]["status"] == "pending"
    assert asked.json()["cancellation"]["can_decide"] is False

    client = as_user(director)
    pending = client.get("/api/v1/vouchers/cancellations/?pending=1").json()
    assert [(r["voucher"]["number"], r["reason"], r["can_decide"]) for r in pending] == [
        (voucher.number, "Order withdrawn", True)
    ]
    done = client.post(f"/api/v1/vouchers/cancellations/{pending[0]['id']}/approve/", {})
    assert done.status_code == 200
    assert done.json()["status"] == "cancelled"
    assert done.json()["cancellation"]["decided_by"] == director.full_name
    assert client.get("/api/v1/vouchers/cancellations/?pending=1").json() == []
