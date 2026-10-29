"""Returns and amendments (backlog P1-05, spec 4.2)."""

from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.accounting.models import Account
from apps.core.models import Division
from apps.vouchers import services
from apps.vouchers.models import Voucher, VoucherLine, VoucherLineSplit
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
def cashier():
    return person("cashier@sml.lk", "cashier", all_divisions=True)


def div(code):
    return Division.objects.get(code=code)


def fresh(voucher):
    return Voucher.objects.get(pk=voucher.pk)


def approved(clerk, accountant, director, code="S0001"):
    """A voucher through all three levels, its line split between two divisions."""
    voucher = draft(clerk, payee(code=code), LineInput(amount="1000.00", invoice_no="INV-7"))
    attach(clerk, voucher, content=b"%PDF-1.7 " + code.encode())
    services.submit(clerk, voucher)
    services.code_lines(
        accountant,
        voucher,
        [
            CodingInput(
                line_no=1,
                account=Account.objects.get(number="6210"),
                splits=[
                    SplitInput(division=div("WS"), amount="600.00"),
                    SplitInput(division=div("IM"), amount="400.00"),
                ],
            )
        ],
    )
    services.approve(accountant, voucher, "coded")
    return services.approve(director, fresh(voucher))


def through_approval(accountant, director, voucher):
    services.approve(accountant, voucher, "checked")
    return services.approve(director, fresh(voucher))


# --- Returns ----------------------------------------------------------------------------


def test_a_return_by_the_director_restarts_approval_at_the_accountant(clerk, accountant, director):
    voucher = draft(clerk, payee(), LineInput(amount="1000.00"))
    attach(clerk, voucher)
    services.submit(clerk, voucher)
    services.code_lines(
        accountant,
        voucher,
        [CodingInput(line_no=1, account=Account.objects.get(number="6210"), division=div("WS"))],
    )
    services.approve(accountant, voucher)
    services.send_back(director, fresh(voucher), "Attach the delivery note")
    assert fresh(voucher).status == "returned"
    assert services.actions(clerk, fresh(voucher))[:3] == ["resources", "print", "edit"]

    services.save(
        clerk,
        fresh(voucher),
        voucher_type=voucher.voucher_type,
        payee=voucher.payee,
        lines=[LineInput(amount="1000.00")],
    )
    services.submit(clerk, fresh(voucher), "Delivery note attached")
    assert fresh(voucher).status == "submitted"  # back at L2, not L3
    assert list(services.waiting(accountant)) == [fresh(voucher)]
    assert not services.waiting(director).exists()


# --- An approved voucher is never edited ----------------------------------------------


def test_an_approved_voucher_cannot_be_edited(clerk, accountant, director):
    voucher = approved(clerk, accountant, director)
    with pytest.raises(VoucherError, match="only a draft or a returned voucher"):
        services.save(
            clerk,
            voucher,
            voucher_type=voucher.voucher_type,
            payee=voucher.payee,
            lines=[LineInput(amount="1.00")],
        )
    assert services.actions(clerk, voucher) == ["resources", "print", "amend"]
    with pytest.raises(DatabaseError, match="amend it instead"), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(total_amount=Decimal("1.00"))
    with pytest.raises(DatabaseError, match="amend it instead"), transaction.atomic():
        VoucherLine.objects.filter(voucher=voucher).update(amount=Decimal("1.00"))
    with pytest.raises(DatabaseError, match="amend it instead"), transaction.atomic():
        VoucherLineSplit.objects.filter(line__voucher=voucher).delete()


# --- Amendments -----------------------------------------------------------------------


def test_an_amendment_is_a_new_revision_through_l2_and_l3(clerk, accountant, director, cashier):
    original = approved(clerk, accountant, director)
    with pytest.raises(VoucherError, match="why"):
        services.amend(clerk, original, " ")
    with pytest.raises(VoucherError, match="Clerk or the Accountant"):
        services.amend(director, original, "wrong amount")

    amendment = services.amend(clerk, original, "Supplier sent a corrected invoice")
    assert amendment.number == f"{original.number}-R1"
    assert (amendment.revision, amendment.parent, amendment.status) == (1, original, "draft")
    assert amendment.amendment_reason == "Supplier sent a corrected invoice"
    line = amendment.lines.get()
    assert (line.invoice_no, line.amount, line.account.number) == (
        "INV-7",
        Decimal("1000.00"),
        "6210",
    )
    assert sorted(line.splits.values_list("division__code", "amount")) == [
        ("IM", Decimal("400.00")),
        ("WS", Decimal("600.00")),
    ]
    assert amendment.attachments.count() == 1
    assert services.duplicate_invoices(amendment) == []  # its own original is not a duplicate

    original = fresh(original)
    assert original.status == "amended"  # replaced: cannot be paid
    assert services.actions(clerk, original) == ["resources", "print"]
    assert not services.visible(cashier).filter(pk=original.pk).exists()
    with pytest.raises(VoucherError, match="only a Director-approved"):
        services.amend(clerk, original, "again")

    services.save(
        clerk,
        amendment,
        voucher_type=amendment.voucher_type,
        payee=amendment.payee,
        description=amendment.description,
        lines=[LineInput(amount="1150.00", invoice_no="INV-7A")],
    )
    services.submit(clerk, fresh(amendment))
    assert list(services.waiting(accountant)) == [fresh(amendment)]
    services.code_lines(
        accountant,
        fresh(amendment),
        [CodingInput(line_no=1, account=Account.objects.get(number="6210"), division=div("WS"))],
    )
    done = through_approval(accountant, director, fresh(amendment))
    assert done.status == "director_approved" and done.total_amount == Decimal("1150.00")
    assert fresh(original).status == "amended"
    assert fresh(original).total_amount == Decimal("1000.00")  # the original never changes

    second = services.amend(accountant, done, "Discount agreed")
    assert second.number == f"{original.number}-R2" and second.parent == done
    assert list(services.amendments(accountant)) == [second, done]


def test_a_rejected_amendment_leaves_the_original_approved(clerk, accountant, director):
    original = approved(clerk, accountant, director)
    amendment = services.amend(clerk, original, "Change the amount")
    services.submit(clerk, amendment)
    services.reject(accountant, fresh(amendment), "The original amount was right")
    assert fresh(original).status == "director_approved"
    again = services.amend(clerk, fresh(original), "Second try")
    assert again.number == f"{original.number}-R2"  # R1 is never reused


def test_a_deleted_draft_amendment_leaves_the_original_approved(clerk, accountant, director):
    original = approved(clerk, accountant, director)
    amendment = services.amend(clerk, original, "Change the amount")
    with pytest.raises(VoucherError, match="replaced by an amendment"):
        services.delete(director, fresh(original), "x")
    services.delete(clerk, amendment)
    assert fresh(original).status == "director_approved"


def test_amendments_through_the_api(clerk, accountant, director):
    original = approved(clerk, accountant, director)
    client = as_user(clerk)
    assert (
        client.post(f"/api/v1/vouchers/{original.pk}/amend/", {}, format="json").status_code == 400
    )
    assert (
        as_user(director)
        .post(f"/api/v1/vouchers/{original.pk}/amend/", {"reason": "x"}, format="json")
        .status_code
        == 403
    )
    made = client.post(
        f"/api/v1/vouchers/{original.pk}/amend/", {"reason": "Corrected invoice"}, format="json"
    )
    assert made.status_code == 201
    body = made.json()
    assert body["number"] == f"{original.number}-R1"
    assert body["parent"] == {"id": original.pk, "number": original.number}
    assert body["can_edit"] is True and body["status"] == "draft"
    shown = client.get(f"/api/v1/vouchers/{original.pk}/").json()
    assert shown["status"] == "amended"
    assert shown["revisions"] == [{"id": body["id"], "number": body["number"], "status": "draft"}]
    rows = as_user(accountant).get("/api/v1/vouchers/amendments/").json()
    assert [(r["number"], r["revision"], r["parent"]["number"]) for r in rows] == [
        (body["number"], 1, original.number)
    ]
    assert rows[0]["amendment_reason"] == "Corrected invoice"
    assert rows[0]["parent"]["total_amount"] == "1000.00"
