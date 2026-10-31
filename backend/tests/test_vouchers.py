"""The Clerk's payment voucher: entry, attachments, submission (backlog P1-02)."""

import itertools
from datetime import date
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import taxes
from apps.accounting.models import TaxCode, TaxComponent
from apps.core import approvals
from apps.core.models import ApprovalState, Division, Notification
from apps.masters.models import CompanyAccount, Currency, Supplier
from apps.vouchers import services
from apps.vouchers.models import Voucher, VoucherAttachment, VoucherLine, VoucherType
from apps.vouchers.services import LineInput, VoucherError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

PDF = b"%PDF-1.7\n" + b"0" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
TODAY = timezone.localdate()


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


def payee(name="Lanka Steel (Pvt) Ltd", category="supplier", code="S0001"):
    return Supplier.objects.create(
        code=code, name=name, category=category, currency=Currency.objects.get(code="LKR")
    )


@pytest.fixture
def supplier():
    return payee()


def vt(code):
    return VoucherType.objects.get(code=code)


def ws():
    return Division.objects.get(code="WS")


_INVOICES = itertools.count(1001)


def draft(user, the_payee, *lines, code="CHQ"):
    """A draft voucher; without lines, one line with a new invoice number (a supplier invoice
    can be on one voucher only)."""
    return services.save(
        user,
        None,
        voucher_type=vt(code),
        division=ws(),
        payee=the_payee,
        description="Steel for job 145",
        lines=list(lines) or [LineInput(amount="25000.00", invoice_no=f"INV-{next(_INVOICES)}")],
    )


def attach(user, voucher, content=PDF, name="invoice.pdf"):
    return services.add_attachment(user, voucher, SimpleUploadedFile(name, content))


# --- Entering a voucher -----------------------------------------------------------------


def test_the_clerk_saves_a_numbered_draft(clerk, supplier):
    voucher = draft(clerk, supplier)
    assert voucher.number == f"WS{TODAY:%y%m%d}001"
    assert (voucher.status, voucher.voucher_date, voucher.total_amount) == (
        "draft",
        TODAY,
        Decimal("25000.00"),
    )
    assert draft(clerk, supplier).number.endswith("002")
    assert voucher.lines.get().division == ws()  # defaults to the voucher's division


def test_tax_is_worked_out_from_the_tax_code(clerk, accountant, supplier):
    taxes.add_rate(
        accountant,
        TaxComponent.objects.get(code="SSCL"),
        effective_from=date(2024, 1, 1),
        rate="2.125",
    )
    taxes.add_rate(
        accountant, TaxComponent.objects.get(code="VAT"), effective_from=date(2024, 1, 1), rate="18"
    )
    voucher = draft(
        clerk,
        supplier,
        LineInput(
            amount="115750.00", invoice_no="A1", tax_code=TaxCode.objects.get(code="VAT-SSCL")
        ),
        LineInput(amount="1000.00", invoice_no="A2", tax_amount="50.00"),
    )
    first, second = voucher.lines.all()
    assert first.tax_amount == Decimal("23737.43")
    assert second.tax_amount == Decimal("50.00")
    assert voucher.total_amount == Decimal("139487.43") + Decimal("1050.00")


@pytest.mark.parametrize(
    "line, why",
    [
        (LineInput(amount="0"), "more than zero"),
        (LineInput(amount="-5"), "more than zero"),
        (LineInput(amount=10.5), "floating point"),
        (LineInput(amount="10.005"), "to the cent"),
        (LineInput(amount="10", tax_amount="-1"), "negative"),
        (LineInput(amount="10", invoice_date=date(2999, 1, 1)), "future"),
    ],
)
def test_lines_must_be_valid(clerk, supplier, line, why):
    with pytest.raises(VoucherError, match=why):
        draft(clerk, supplier, line)


def test_the_payee_must_suit_the_voucher_type(clerk, supplier):
    with pytest.raises(VoucherError, match="category Employee"):
        draft(clerk, supplier, code="RMB")
    employee = payee("Nimal Perera", "employee", "S0002")
    assert draft(clerk, employee, code="RMB").payee == employee
    with pytest.raises(VoucherError, match="has no payee"):
        draft(clerk, supplier, code="INT")


def test_only_its_creator_changes_a_draft_and_the_division_stays(clerk, accountant, supplier):
    voucher = draft(clerk, supplier)
    with pytest.raises(VoucherError, match="Only the person who created"):
        services.save(
            accountant,
            voucher,
            voucher_type=vt("CHQ"),
            payee=supplier,
            lines=[LineInput(amount="1")],
        )
    with pytest.raises(VoucherError, match="cannot change"):
        services.save(
            clerk,
            voucher,
            voucher_type=vt("CHQ"),
            division=Division.objects.get(code="IM"),
            payee=supplier,
            lines=[LineInput(amount="1")],
        )
    services.save(
        clerk, voucher, voucher_type=vt("ONL"), payee=supplier, lines=[LineInput(amount="300.00")]
    )
    voucher.refresh_from_db()
    assert voucher.voucher_type.code == "ONL" and voucher.total_amount == Decimal("300.00")
    director = person("director@sml.lk", "director", all_divisions=True)
    with pytest.raises(VoucherError, match="Only the Clerk"):
        draft(director, supplier)


def test_the_same_supplier_invoice_cannot_be_entered_twice(clerk, supplier):
    """Owner's decision (31 Oct 2026): supplier + invoice number is unique, ignoring case and
    spaces; another supplier may use the same number; a deleted voucher frees it."""
    first = draft(clerk, supplier, LineInput(amount="10.00", invoice_no="INV-77"))
    with pytest.raises(VoucherError, match=f"already on voucher {first.number}"):
        draft(clerk, supplier, LineInput(amount="10.00", invoice_no="inv - 77"))
    other = payee("Other Ltd", code="S0009")
    draft(clerk, other, LineInput(amount="1", invoice_no="INV-77"))
    # The same invoice twice on one voucher (two lines of one bill) is fine.
    services.save(
        clerk,
        first,
        voucher_type=first.voucher_type,
        payee=supplier,
        lines=[
            LineInput(amount="10.00", invoice_no="INV-77"),
            LineInput(amount="5.00", invoice_no="INV-77"),
        ],
    )
    services.delete(clerk, first, "Entered by mistake")
    draft(clerk, supplier, LineInput(amount="10.00", invoice_no="INV-77"))  # freed


def test_the_database_refuses_a_duplicate_supplier_invoice(clerk, supplier):
    first = draft(clerk, supplier, LineInput(amount="10.00", invoice_no="INV-88"))
    second = draft(clerk, supplier, LineInput(amount="10.00", invoice_no="INV-89"))
    with pytest.raises(DatabaseError, match="already on voucher"), transaction.atomic():
        VoucherLine.objects.filter(voucher=second).update(invoice_no="inv-88 ")
    assert first.lines.count() == 1


# --- Attachments ------------------------------------------------------------------------


def test_scans_are_attached_and_the_same_file_twice_is_flagged(clerk, supplier):
    first = draft(clerk, supplier)
    attachment, warnings = attach(clerk, first)
    assert (attachment.content_type, warnings) == ("application/pdf", [])
    second = draft(clerk, supplier)
    _, warnings = attach(clerk, second, name="copy.pdf")
    assert warnings == [f"This file is already attached to voucher {first.number}."]
    photo, _ = attach(clerk, second, PNG, "phone.png")
    assert photo.content_type == "image/png"


@pytest.mark.parametrize(
    "content, why",
    [
        (b"MZ\x90\x00 an exe pretending", "Only PDF, JPG and PNG"),
        (b"just text with a .pdf name", "Only PDF, JPG and PNG"),
        (PDF + b"0" * (20 * 1024 * 1024), "larger than 20 MB"),
    ],
)
def test_only_pdf_jpg_png_up_to_20_mb(clerk, supplier, content, why):
    with pytest.raises(VoucherError, match=why):
        attach(clerk, draft(clerk, supplier), content, "invoice.pdf")


# --- Submitting -------------------------------------------------------------------------


def test_submitting_needs_a_payee_and_a_scan(clerk, supplier):
    no_payee = services.save(
        clerk, None, voucher_type=vt("CHQ"), division=ws(), lines=[LineInput(amount="5")]
    )
    with pytest.raises(VoucherError, match="Choose the payee"):
        services.submit(clerk, no_payee)
    voucher = draft(clerk, supplier)
    with pytest.raises(VoucherError, match="Attach the scanned invoice"):
        services.submit(clerk, voucher)
    empty = draft(clerk, supplier)
    empty.lines.all().delete()
    with pytest.raises(VoucherError, match="at least one invoice line"):
        services.submit(clerk, empty)


def test_a_submitted_voucher_goes_to_the_accountant_then_the_director(
    clerk, accountant, director, supplier
):
    voucher = draft(clerk, supplier)
    attach(clerk, voucher)
    voucher = services.submit(clerk, voucher, comment="urgent")
    assert voucher.status == "submitted" and voucher.submitted_at is not None
    state = approvals.state_of("voucher", voucher.pk)
    assert [s["role"] for s in state.route] == ["accountant", "director"]
    assert state.title.startswith(f"Voucher {voucher.number} – Lanka Steel")
    assert Notification.objects.filter(user=accountant, link=f"/vouchers/{voucher.pk}").exists()
    assert supplier.__class__.objects.get(pk=supplier.pk).first_used_at is not None
    # nothing can change it now
    with pytest.raises(VoucherError, match="only a draft or a returned voucher"):
        services.save(
            clerk, voucher, voucher_type=vt("CHQ"), payee=supplier, lines=[LineInput(amount="1")]
        )
    with pytest.raises(VoucherError, match="only a draft or a returned voucher"):
        attach(clerk, voucher, PNG)
    with pytest.raises(DatabaseError), transaction.atomic():
        VoucherAttachment.objects.filter(voucher=voucher).delete()
    approvals.approve(accountant, "voucher", voucher.pk)
    assert services.sync_status(voucher).status == "accountant_approved"
    approvals.approve(director, "voucher", voucher.pk)
    assert services.sync_status(voucher).status == "director_approved"
    assert services.payee_balance(supplier)["approved_unpaid"] == "25000.00"


def test_a_returned_voucher_is_corrected_and_resubmitted(clerk, accountant, supplier):
    voucher = draft(clerk, supplier)
    attach(clerk, voucher)
    services.submit(clerk, voucher)
    approvals.send_back(accountant, "voucher", voucher.pk, reason="Wrong amount")
    voucher = services.sync_status(Voucher.objects.get(pk=voucher.pk))
    assert voucher.status == "returned"
    services.save(
        clerk,
        voucher,
        voucher_type=vt("CHQ"),
        payee=supplier,
        lines=[LineInput(amount="24000.00", invoice_no="INV-1001")],
    )
    voucher = services.submit(clerk, Voucher.objects.get(pk=voucher.pk))
    assert voucher.status == "submitted" and voucher.total_amount == Decimal("24000.00")
    assert ApprovalState.objects.get(document_id=voucher.pk).round == 2


def test_an_internal_transfer_has_no_payee_but_a_receiving_account(clerk):
    cash = CompanyAccount.objects.create(
        code="CASH", kind="cash", name="Office cash", currency=Currency.objects.get(code="LKR")
    )
    voucher = services.save(
        clerk, None, voucher_type=vt("INT"), division=ws(), lines=[LineInput(amount="50000.00")]
    )
    with pytest.raises(VoucherError, match="money goes to"):
        services.submit(clerk, voucher)
    services.save(
        clerk,
        voucher,
        voucher_type=vt("INT"),
        transfer_to=cash,
        lines=[LineInput(amount="50000.00")],
    )
    assert services.submit(clerk, Voucher.objects.get(pk=voucher.pk)).status == "submitted"


def test_vouchers_are_never_deleted_and_keep_their_number(clerk, supplier):
    voucher = draft(clerk, supplier)
    with pytest.raises(DatabaseError), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).delete()
    with pytest.raises(DatabaseError), transaction.atomic():
        Voucher.objects.filter(pk=voucher.pk).update(number="WS000000999")


# --- Who sees what, through the API -----------------------------------------------------


def test_the_api_creates_and_shows_a_voucher(clerk, supplier):
    client = as_user(clerk)
    body = {
        "voucher_type": "chq",
        "division": "WS",
        "payee": supplier.pk,
        "description": "Steel",
        "lines": [{"invoice_no": "INV-9", "invoice_date": TODAY.isoformat(), "amount": "1500.50"}],
    }
    response = client.post("/api/v1/vouchers/", body, format="json")
    assert response.status_code == 201, response.json()
    created = response.json()
    assert created["total_amount"] == "1500.50" and created["can_edit"] is True
    pk = created["id"]
    upload = client.post(
        f"/api/v1/vouchers/{pk}/attachments/",
        {"file": SimpleUploadedFile("scan.pdf", PDF)},
        format="multipart",
    )
    assert upload.status_code == 201, upload.json()
    assert upload.json()["attachments"][0]["file_name"] == "scan.pdf"
    file_response = client.get(
        f"/api/v1/vouchers/{pk}/attachments/{upload.json()['attachments'][0]['id']}/"
    )
    assert file_response.status_code == 200 and file_response["Content-Type"] == "application/pdf"
    submitted = client.post(f"/api/v1/vouchers/{pk}/submit/", {}, format="json").json()
    assert submitted["status"] == "submitted" and submitted["approvals"][0]["action"] == "submit"
    assert client.get("/api/v1/vouchers/?status=submitted").json()[0]["number"] == created["number"]


def test_each_role_sees_the_right_vouchers(clerk, accountant, director, supplier):
    voucher = draft(clerk, supplier)
    other_clerk = person("clerk2@sml.lk", "clerk", all_divisions=True)
    cashier = person("cashier@sml.lk", "cashier", all_divisions=True)
    url = f"/api/v1/vouchers/{voucher.pk}/"
    assert as_user(other_clerk).get(url).status_code == 404
    assert as_user(accountant).get(url).status_code == 200
    assert as_user(director).get(url).status_code == 200
    assert as_user(cashier).get(url).status_code == 404  # not approved yet
    assert (
        as_user(director)
        .post("/api/v1/vouchers/", {"voucher_type": "CHQ"}, format="json")
        .status_code
        == 403
    )
    moulding_clerk = person("im@sml.lk", "clerk", divisions=["IM"])
    response = as_user(moulding_clerk).post(
        "/api/v1/vouchers/", {"voucher_type": "CHQ", "division": "WS", "lines": []}, format="json"
    )
    assert response.status_code == 400 and "do not work in division WS" in response.json()["detail"]
