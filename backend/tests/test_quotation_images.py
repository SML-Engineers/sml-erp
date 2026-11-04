# ruff: noqa: F811 - the fixtures of test_quotation_pdf are imported and used by name
"""Product pictures on a quotation (owner's request, 4 Nov 2026): at most three JPG or PNG of
at most 1 MB, added by the person making the quotation, seen by the approver and emailed to
the customer with the quotation."""

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError

from apps.core.models import SentEmail
from apps.sales import quotation_email, services, workflow
from apps.sales.models import QuotationImage
from apps.sales.services import SalesError

from .test_access import as_user, person
from .test_quotation_pdf import (  # noqa: F401 - fixtures used by name
    accountant,
    aluflex,
    approved,
    director,
    draft,
    executive,
    mailbox,
    memory_storage,
    vat_sscl,
)

pytestmark = pytest.mark.django_db

JPG = b"\xff\xd8\xff\xe0" + b"\x00JFIF" + b"j" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 200


def picture(name="die.jpg", content=JPG):
    return SimpleUploadedFile(name, content)


def test_up_to_three_small_pictures_by_the_person_making_it(draft, executive):
    services.add_image(executive, draft, picture("front.jpg"))
    services.add_image(executive, draft, picture("side.png", PNG))
    with pytest.raises(SalesError, match="already on the quotation"):
        services.add_image(executive, draft, picture("again.jpg"))
    services.add_image(executive, draft, picture("top.jpg", JPG + b"2"))
    assert [i.file_name for i in draft.images.all()] == ["front.jpg", "side.png", "top.jpg"]
    with pytest.raises(SalesError, match="at most 3 pictures"):
        services.add_image(executive, draft, picture("fourth.jpg", JPG + b"4"))


def test_only_jpg_or_png_of_at_most_1_mb(draft, executive):
    too_big = JPG + b"x" * (1024 * 1024)
    with pytest.raises(SalesError, match="larger than 1 MB"):
        services.add_image(executive, draft, picture("big.jpg", too_big))
    with pytest.raises(SalesError, match="Only JPG and PNG"):
        services.add_image(executive, draft, picture("drawing.pdf", b"%PDF-1.7 xx"))
    other = person("sales2@sml.lk", "sales_executive", all_divisions=True)
    with pytest.raises(SalesError, match="by the person who made it"):
        services.add_image(other, draft, picture())
    assert not draft.images.exists()


def test_the_approver_sees_them_and_they_are_fixed_once_submitted(draft, executive, director):
    added = as_user(executive).post(
        f"/api/v1/quotations/{draft.pk}/images/", {"file": picture()}, format="multipart"
    )
    assert added.status_code == 201, added.json()
    (shown,) = added.json()["images"]
    assert (shown["file_name"], shown["content_type"]) == ("die.jpg", "image/jpeg")
    workflow.submit(executive, draft)
    boss = as_user(director)
    seen = boss.get(f"/api/v1/quotations/{draft.pk}/")
    assert [i["file_name"] for i in seen.json()["images"]] == ["die.jpg"]
    got = boss.get(f"/api/v1/quotations/{draft.pk}/images/{shown['id']}/")
    assert got.status_code == 200 and b"".join(got.streaming_content) == JPG
    with pytest.raises(SalesError, match="added to a draft"):
        services.add_image(executive, draft, picture("late.png", PNG))
    removed = as_user(executive).delete(f"/api/v1/quotations/{draft.pk}/images/{shown['id']}/")
    assert removed.status_code == 400
    with transaction.atomic(), pytest.raises(DatabaseError, match="only while it is a draft"):
        QuotationImage.objects.filter(quotation=draft).delete()


def test_the_pictures_go_with_the_emailed_quotation(draft, executive, director, mailbox):
    services.add_image(executive, draft, picture("front.jpg"))
    services.add_image(executive, draft, picture("side.png", PNG))
    workflow.submit(executive, draft)
    q = workflow.approve(director, draft)
    message = quotation_email.draft(executive, q)
    assert message["images"] == ["front.jpg", "side.png"]
    record = quotation_email.send(
        executive, q, to=message["to"], subject=message["subject"], body=message["body"]
    )
    assert record.status == SentEmail.Status.SENT
    (sent,) = mail.outbox
    assert [(a[0], a[2]) for a in sent.attachments] == [
        (f"Quotation-{q.number}.pdf", "application/pdf"),
        ("front.jpg", "image/jpeg"),
        ("side.png", "image/png"),
    ]
    assert sent.attachments[1][1] == JPG
    assert record.other_attachments.splitlines()[0].startswith("front.jpg ")


def test_the_pictures_can_be_left_out_of_the_email(draft, executive, director, mailbox):
    services.add_image(executive, draft, picture())
    workflow.submit(executive, draft)
    q = workflow.approve(director, draft)
    sent = as_user(executive).post(
        f"/api/v1/quotations/{q.pk}/email/",
        {
            "to": ["ruwani@aluflex.lk"],
            "subject": "Quotation",
            "body": "Please find our quotation.",
            "include_images": False,
        },
        format="json",
    )
    assert sent.status_code == 200, sent.json()
    assert [a[0] for a in mail.outbox[0].attachments] == [f"Quotation-{q.number}.pdf"]


def test_a_revision_keeps_the_pictures(draft, executive, director):
    services.add_image(executive, draft, picture())
    workflow.submit(executive, draft)
    revised = workflow.revise(executive, workflow.approve(director, draft))
    assert [(i.file_name, i.sha256) for i in revised.images.all()] == [
        (x.file_name, x.sha256) for x in draft.images.all()
    ]
    services.add_image(executive, revised, picture("second.png", PNG))  # a draft again
    assert revised.images.count() == 2
