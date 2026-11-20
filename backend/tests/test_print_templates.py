"""The template designer (owner, 13 Nov 2026): saved layouts of the delivery note, their
history, who may change them, the guard on old versions, and printing from a layout."""

# ruff: noqa: F811  (fixtures shared with test_delivery_notes)
import copy

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError

from apps.core import print_layout, print_templates
from apps.core.models import PrintTemplate
from apps.core.print_templates import TemplateError
from apps.sales import deliveries, delivery_layout, delivery_printing

from .test_access import as_user, person
from .test_delivery_notes import (  # noqa: F401
    director,
    executive,
    lines,
    memory_storage,
    order,
    stores,
)

pytestmark = pytest.mark.django_db

DOC = "delivery_note"
URL = f"/api/v1/print-templates/{DOC}/"


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


def standard():
    return copy.deepcopy(delivery_layout.STANDARD)


def block(layout, key):
    return next(b for b in layout["blocks"] if b["key"] == key)


def test_the_admin_and_the_director_save_versions_and_others_only_look(admin, director, stores):
    page = as_user(director).get(URL).json()
    assert (page["version"], page["can_edit"], page["layout"]) == (None, True, standard())
    moved = standard()
    block(moved, "title")["size"] = 18
    saved = as_user(admin).post(URL, {"layout": moved, "note": "Bigger title"}, format="json")
    assert saved.status_code == 200, saved.json()
    assert saved.json()["version"] == 1
    as_user(director).post(URL, {"reset": True}, format="json")
    page = as_user(director).get(URL).json()
    assert page["version"] == 2 and page["layout"] == standard()
    assert [(h["version"], h["note"], h["by"]) for h in page["history"]] == [
        (2, "Back to the standard layout", director.full_name),
        (1, "Bigger title", admin.full_name),
    ]
    as_user(director).post(URL, {"restore": 1}, format="json")
    assert block(print_templates.layout_for(DOC), "title")["size"] == 18
    with pytest.raises(TemplateError, match="Only the Admin and the Director"):
        print_templates.save(stores, DOC, standard())
    assert as_user(admin).get("/api/v1/print-templates/").json()["documents"] == [
        {"document": DOC, "label": "Delivery note", "version": 3}
    ]


def test_a_saved_version_never_changes(admin):
    saved = print_templates.save(admin, DOC, standard())
    for sql in (
        "UPDATE core_printtemplate SET note = 'x' WHERE id = %s",
        "DELETE FROM core_printtemplate WHERE id = %s",
    ):
        with pytest.raises(DatabaseError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(sql, [saved.pk])
    assert PrintTemplate.objects.get(pk=saved.pk).note == ""


@pytest.mark.parametrize(
    "change,message",
    [
        (lambda layout: layout["blocks"].pop(), "must have every block: Slogan missing"),
        (lambda layout: block(layout, "lines").update(hidden=True), "Items table must stay"),
        (lambda layout: block(layout, "customer").update(x=150), "past the edge of the page"),
        (lambda layout: block(layout, "title").update(size=40), "text size must be from 6 to 24"),
        (lambda layout: block(layout, "refs").update(w="wide"), "width must be a number"),
        (lambda layout: layout["blocks"].append({"key": "logo2"}), "Unknown block"),
        (
            lambda layout: layout["blocks"].append(
                {"key": "text-1", "x": 0, "y": 0, "w": 50, "h": 10, "text": " "}
            ),
            "A text block is empty",
        ),
    ],
)
def test_a_layout_that_cannot_print_is_refused(admin, change, message):
    layout = standard()
    change(layout)
    with pytest.raises(TemplateError, match=message):
        print_templates.save(admin, DOC, layout)
    assert not PrintTemplate.objects.exists()


def test_the_note_prints_from_the_saved_layout(admin, order, stores):
    note = deliveries.issue(stores, deliveries.create(stores, order, lines=lines(order, "6000")))
    layout = standard()
    block(layout, "transport")["hidden"] = True
    layout["blocks"].append(
        {"key": "text-1", "x": 0, "y": 250, "w": 182, "h": 6, "text": "Thank you, come again"}
    )
    print_templates.save(admin, DOC, layout)
    text = delivery_printing.render(note, compress=False)
    for expected in (b"DELIVERY NOTE", note.number.encode(), b"6,000", b"Thank you, come again"):
        assert expected in text, expected
    assert b"Vehicle no." not in text  # hidden


def test_a_long_table_runs_onto_more_pages_and_what_follows_comes_after_it():
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, Table

    body = getSampleStyleSheet()["Normal"]

    def contents(text):
        return lambda size, align: [Paragraph(text, body)]

    def table(size, align):
        rows = [["No.", "Item"]] + [[str(n), f"Row {n}"] for n in range(1, 121)]
        return [Table(rows, repeatRows=1)]

    layout = {
        "blocks": [
            {"key": "head", "x": 0, "y": 0, "w": 182, "h": 20},
            {"key": "lines", "x": 0, "y": 30, "w": 182, "h": 100},
            {"key": "foot", "x": 0, "y": 140, "w": 182, "h": 20},
        ]
    }
    pdf = print_layout.render(
        layout,
        {"head": contents("HEADING"), "lines": table, "foot": contents("SIGN HERE")},
        table="lines",
        compress=False,
    )
    pages = pdf.split(b"/Type /Page\n")
    assert len(pages) - 1 >= 3  # 120 rows need three pages
    assert pdf.count(b"HEADING") == 1 and pdf.count(b"SIGN HERE") == 1
    assert b"Row 120" in pdf and pdf.index(b"Row 120") < pdf.index(b"SIGN HERE")


def test_the_preview_prints_the_latest_note_with_an_unsaved_layout(admin, stores, order):
    client = as_user(admin)
    assert client.post(f"{URL}preview/", {"layout": standard()}, format="json").json() == {
        "detail": "Make a delivery note first: the preview prints the latest one."
    }
    deliveries.create(stores, order, lines=lines(order, "10"))
    answer = client.post(f"{URL}preview/", {"layout": standard()}, format="json")
    assert answer["Content-Type"] == "application/pdf"
    assert not PrintTemplate.objects.exists()  # nothing saved
    assert as_user(stores).post(
        f"{URL}preview/", {"layout": standard()}, format="json"
    ).status_code in (400, 403)
