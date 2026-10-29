"""Row actions on vouchers: who may edit, delete and print, and what happens (backlog P1-04b,
spec 4.4)."""

from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting.models import Account
from apps.core import approvals
from apps.core.models import ApprovalState, AuditEvent, Division
from apps.core.words import amount_in_words
from apps.vouchers import printing, services
from apps.vouchers.models import Voucher, VoucherPrint
from apps.vouchers.services import CodingInput, LineInput, VoucherError

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
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


def ws():
    return Division.objects.get(code="WS")


def submitted(clerk, code="S0001", amount="1000.00"):
    voucher = draft(clerk, payee(code=code), LineInput(amount=amount, invoice_no=f"I-{code}"))
    attach(clerk, voucher, content=b"%PDF-1.7 " + code.encode())
    return services.submit(clerk, voucher)


def at_director(clerk, accountant, code="S0001", amount="1000.00"):
    voucher = submitted(clerk, code, amount)
    services.code_lines(
        accountant,
        voucher,
        [CodingInput(line_no=1, account=Account.objects.get(number="6210"), division=ws())],
    )
    return services.approve(accountant, voucher, "coded")


def fresh(voucher):
    return Voucher.objects.get(pk=voucher.pk)


# --- Which actions each person sees -----------------------------------------------------


def test_each_person_sees_only_the_actions_they_may_take(clerk, accountant, director, admin):
    mine = draft(clerk, payee(code="S0009"))
    assert services.actions(clerk, mine) == ["resources", "print", "edit", "delete"]
    assert services.actions(admin, mine) == ["resources", "print", "delete"]
    assert services.actions(accountant, mine) == ["resources", "print"]

    waiting_l2 = submitted(clerk, "S0001")
    assert services.actions(clerk, waiting_l2) == ["resources", "print"]
    assert services.actions(accountant, waiting_l2) == ["resources", "print", "edit_coding"]
    assert services.actions(director, waiting_l2) == ["resources", "print", "delete"]

    waiting_l3 = at_director(clerk, accountant, "S0002")
    assert services.actions(accountant, waiting_l3) == ["resources", "print"]
    assert services.actions(director, waiting_l3) == ["resources", "print", "revise", "delete"]
    assert services.actions(admin, waiting_l3) == ["resources", "print", "delete"]


def test_the_list_carries_each_rows_actions(clerk, accountant):
    voucher = submitted(clerk)
    rows = as_user(accountant).get("/api/v1/vouchers/").json()
    assert rows[0]["id"] == voucher.pk
    assert rows[0]["actions"] == ["resources", "print", "edit_coding"]


# --- Delete ---------------------------------------------------------------------------


def test_a_draft_is_deleted_by_its_creator_or_the_admin_only(clerk, accountant, admin):
    other = person("clerk2@sml.lk", "clerk", all_divisions=True)
    first = draft(clerk, payee(code="S0001"))
    with pytest.raises(VoucherError, match="creator or the Admin"):
        services.delete(other, first)
    with pytest.raises(VoucherError, match="creator or the Admin"):
        services.delete(accountant, first)
    deleted = services.delete(clerk, first)  # no reason needed for a draft
    assert (deleted.status, deleted.deleted_by, deleted.delete_reason) == ("deleted", clerk, "")
    second = draft(clerk, payee(code="S0002"))
    assert services.delete(admin, second).status == "deleted"
    assert second.number != first.number  # numbers are never reused


def test_a_submitted_voucher_is_deleted_by_the_director_with_a_reason(clerk, accountant, director):
    voucher = at_director(clerk, accountant)
    with pytest.raises(VoucherError, match="Director or the Admin"):
        services.delete(clerk, voucher, "mistake")
    with pytest.raises(VoucherError, match="Director or the Admin"):
        services.delete(accountant, voucher, "mistake")
    with pytest.raises(VoucherError, match="reason"):
        services.delete(director, voucher, "  ")
    services.delete(director, voucher, "Entered twice; see WS261029002")

    voucher = fresh(voucher)
    assert voucher.status == "deleted"
    assert voucher.delete_reason == "Entered twice; see WS261029002"
    state = approvals.state_of("voucher", voucher.pk)
    assert state.status == ApprovalState.Status.WITHDRAWN
    assert list(approvals.history("voucher", voucher.pk))[-1].action == "withdraw"
    assert not services.waiting(director).exists()  # gone from the working lists
    assert AuditEvent.objects.filter(event="voucher_deleted", object_id=str(voucher.pk)).exists()
    with pytest.raises(VoucherError, match="already deleted"):
        services.delete(director, voucher, "again")


def test_deleted_vouchers_are_listed_with_their_history(clerk, director, admin):
    voucher = submitted(clerk)
    refused = as_user(clerk).post(
        f"/api/v1/vouchers/{voucher.pk}/delete/", {"reason": "x"}, format="json"
    )
    assert refused.status_code == 400
    done = as_user(admin).post(
        f"/api/v1/vouchers/{voucher.pk}/delete/", {"reason": "Wrong supplier"}, format="json"
    )
    assert done.status_code == 200 and done.json()["status"] == "deleted"

    for user in (director, admin):
        client = as_user(user)
        assert client.get("/api/v1/vouchers/").json() == []
        report = client.get("/api/v1/vouchers/deleted/").json()
        assert [r["number"] for r in report] == [voucher.number]
        assert report[0]["deleted"]["reason"] == "Wrong supplier"
        assert report[0]["deleted"]["by"] == admin.full_name
        assert report[0]["actions"] == ["resources", "print"]
        detail = client.get(f"/api/v1/vouchers/{voucher.pk}/").json()
        assert [a["action"] for a in detail["approvals"]] == ["submit", "withdraw"]
    # The Clerk still finds their own deleted voucher in the report.
    assert len(as_user(clerk).get("/api/v1/vouchers/deleted/").json()) == 1


def test_a_voucher_with_payments_cannot_be_deleted(clerk, accountant, director):
    voucher = at_director(clerk, accountant)
    services.approve(director, voucher)
    Voucher.objects.filter(pk=voucher.pk).update(status="partly_paid")  # as payments will
    with pytest.raises(VoucherError, match="has payments"):
        services.delete(director, fresh(voucher), "duplicate")
    with pytest.raises(DatabaseError, match="has payments"), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(
            status="deleted", deleted_at=timezone.now(), deleted_by=director
        )


def test_the_database_keeps_a_deleted_voucher_unchanged(clerk):
    voucher = services.delete(clerk, draft(clerk, payee()))
    with pytest.raises(DatabaseError, match="deleted"), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(description="changed")
    with pytest.raises(DatabaseError), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(status="draft")
    with pytest.raises(DatabaseError), transaction.atomic():
        # A deleted voucher always records who deleted it.
        Voucher.objects.filter(pk=draft(clerk, payee(code="S0002")).pk).update(status="deleted")


# --- Edit while waiting ---------------------------------------------------------------


def lines_of(voucher):
    return [
        LineInput(
            amount=line.amount,
            invoice_no=line.invoice_no,
            invoice_date=line.invoice_date,
            description=line.description,
            tax_code=line.tax_code,
            tax_amount=line.tax_amount,
        )
        for line in voucher.lines.all()
    ]


def test_the_director_corrects_the_description_without_sending_it_back(clerk, accountant, director):
    voucher = at_director(clerk, accountant)
    services.revise(
        director, voucher, payee=voucher.payee, description="Steel plates", lines=lines_of(voucher)
    )
    voucher = fresh(voucher)
    assert (voucher.description, voucher.status) == ("Steel plates", "accountant_approved")


def test_a_director_change_to_the_amount_goes_back_to_the_accountant(clerk, accountant, director):
    voucher = at_director(clerk, accountant)
    changed = lines_of(voucher)
    changed[0].amount = "1200.00"
    services.revise(director, voucher, payee=voucher.payee, description="", lines=changed)

    voucher = fresh(voucher)
    assert voucher.status == "submitted" and voucher.total_amount == Decimal("1200.00")
    line = voucher.lines.get()
    assert line.account.number == "6210" and line.division == ws()  # coding kept
    sent = list(approvals.history("voucher", voucher.pk))[-1]
    assert (sent.action, sent.level, sent.user) == ("send_down", 3, director)
    assert "Line 1 amount: 1,000.00 → 1,200.00" in sent.reason
    assert "Total: 1,000.00 → 1,200.00" in sent.reason
    assert list(services.waiting(accountant)) == [voucher]
    assert printing.signatures(voucher)["checked"] is None  # the old check no longer counts

    services.approve(accountant, voucher, "checked again")
    services.approve(director, fresh(voucher))
    signed = printing.signatures(fresh(voucher))
    assert (signed["prepared"].user, signed["checked"].user, signed["approved"].user) == (
        clerk,
        accountant,
        director,
    )
    assert signed["checked"].reason == "checked again"


def test_a_director_change_of_payee_is_listed(clerk, accountant, director):
    voucher = at_director(clerk, accountant)
    other = payee("Ceylon Oxygen", code="S0002")
    services.revise(director, voucher, payee=other, description="", lines=lines_of(voucher))
    sent = list(approvals.history("voucher", voucher.pk))[-1]
    assert sent.reason == "Changed: Payee: Lanka Steel (Pvt) Ltd → Ceylon Oxygen"
    assert fresh(voucher).payee == other


def test_the_accountant_returns_rather_than_changes_amounts(clerk, accountant, director):
    voucher = submitted(clerk)
    changed = lines_of(voucher)
    changed[0].amount = "900.00"
    with pytest.raises(VoucherError, match="Return the voucher to the Clerk"):
        services.revise(accountant, voucher, payee=voucher.payee, lines=changed)
    services.revise(
        accountant, voucher, payee=voucher.payee, description="ok", lines=lines_of(voucher)
    )
    assert fresh(voucher).description == "ok"
    with pytest.raises(VoucherError):
        services.revise(director, voucher, payee=voucher.payee, lines=lines_of(voucher))


def test_a_director_tax_change_in_coding_goes_back_to_the_accountant(clerk, accountant, director):
    voucher = at_director(clerk, accountant)
    services.code_lines(
        director,
        voucher,
        [
            CodingInput(
                line_no=1,
                account=Account.objects.get(number="6210"),
                division=ws(),
                tax_amount="180.00",
            )
        ],
    )
    voucher = fresh(voucher)
    assert voucher.status == "submitted" and voucher.total_amount == Decimal("1180.00")
    assert "Total: 1,000.00 → 1,180.00" in list(approvals.history("voucher", voucher.pk))[-1].reason


def test_the_director_revises_through_the_api(clerk, accountant, director):
    voucher = at_director(clerk, accountant)
    body = {
        "voucher_type": "CHQ",
        "payee": voucher.payee_id,
        "description": "",
        "lines": [{"invoice_no": "I-S0001", "amount": "1500.00"}],
    }
    assert (
        as_user(clerk)
        .patch(f"/api/v1/vouchers/{voucher.pk}/revise/", body, format="json")
        .status_code
        == 403
    )
    done = as_user(director).patch(f"/api/v1/vouchers/{voucher.pk}/revise/", body, format="json")
    assert done.status_code == 200, done.json()
    assert done.json()["status"] == "submitted"
    body["voucher_type"] = "ONL"
    refused = as_user(accountant).patch(
        f"/api/v1/vouchers/{voucher.pk}/revise/", body, format="json"
    )
    assert refused.json()["detail"] == "The voucher type cannot change here."


# --- Print ----------------------------------------------------------------------------


def test_printing_gives_a_pdf_and_reprints_are_copies(clerk, accountant, director):
    voucher = at_director(clerk, accountant)
    services.approve(director, voucher)
    client = as_user(accountant)
    first = client.get(f"/api/v1/vouchers/{voucher.pk}/print/")
    assert first.status_code == 200 and first["Content-Type"] == "application/pdf"
    assert first.content.startswith(b"%PDF")
    assert first["Content-Disposition"] == f'inline; filename="{voucher.number}.pdf"'
    again = as_user(clerk).get(f"/api/v1/vouchers/{voucher.pk}/print/?paper=a5")
    assert again["Content-Disposition"] == f'inline; filename="{voucher.number}-copy.pdf"'
    prints = list(VoucherPrint.objects.filter(voucher=voucher))
    assert [(p.printed_by, p.paper, p.is_copy) for p in prints] == [
        (accountant, "A4", False),
        (clerk, "A5", True),
    ]
    assert AuditEvent.objects.filter(event="voucher_printed").count() == 2
    assert client.get(f"/api/v1/vouchers/{voucher.pk}/print/?paper=A3").status_code == 400
    with pytest.raises(DatabaseError), transaction.atomic():
        VoucherPrint.objects.filter(voucher=voucher).update(is_copy=False)


def test_drafts_and_deleted_vouchers_can_be_printed(clerk):
    voucher = draft(clerk, payee())
    assert as_user(clerk).get(f"/api/v1/vouchers/{voucher.pk}/print/").status_code == 200
    services.delete(clerk, voucher)
    assert as_user(clerk).get(f"/api/v1/vouchers/{voucher.pk}/print/").status_code == 200


@pytest.mark.parametrize(
    ("amount", "words"),
    [
        ("0.50", "Rupees Zero and Cents Fifty Only"),
        ("21", "Rupees Twenty-One Only"),
        ("1000", "Rupees One Thousand Only"),
        ("172500.00", "Rupees One Hundred Seventy-Two Thousand Five Hundred Only"),
        (
            "1250000.05",
            "Rupees One Million Two Hundred Fifty Thousand and Cents Five Only",
        ),
    ],
)
def test_amounts_in_words(amount, words):
    assert amount_in_words(Decimal(amount)) == words
    with pytest.raises(TypeError):
        amount_in_words(1.5)
