"""Saved layouts of printed documents (owner, 13 Nov 2026: the template designer).

The Admin and the Director ("edit_print_templates") move, size, hide and add blocks; each
save is a new version, so the history shows who changed what and when, and any version can
be brought back (as a new version). "Reset" saves the standard layout as a new version. The
newest version is printed; with none, the document prints in its standard layout.

A document joins the designer by adding itself to `_documents()`: its blocks (key, label,
may it be hidden), its standard layout, the key of its items table, and how to print one of
its documents with a layout.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .access import effective_access
from .audit import audit_context
from .models import PrintTemplate, User
from .print_layout import ALIGN, PAGE_H_MM, PAGE_W_MM

MAX_TEXT_BLOCKS = 10


class TemplateError(Exception):
    pass


@dataclass
class DocumentKind:
    label: str
    blocks: list  # (key, label, may be hidden)
    standard: dict
    table: str
    sample: object  # () -> a document to preview with, or None
    print_with: object  # (document, layout) -> PDF bytes


def _documents() -> dict[str, DocumentKind]:
    from apps.sales import delivery_layout, delivery_printing
    from apps.sales.models import DeliveryNote

    return {
        PrintTemplate.Document.DELIVERY_NOTE: DocumentKind(
            label="Delivery note",
            blocks=delivery_layout.BLOCKS,
            standard=delivery_layout.STANDARD,
            table="lines",
            sample=lambda: (
                DeliveryNote.objects.exclude(number="").order_by("-pk").first()
                or DeliveryNote.objects.order_by("-pk").first()
            ),
            print_with=delivery_printing.render_with_layout,
        )
    }


def kind(document: str) -> DocumentKind:
    found = _documents().get(document)
    if found is None:
        raise TemplateError("There is no layout for that document.")
    return found


def can_edit(user: User) -> bool:
    return effective_access(user).can("edit_print_templates")


def current(document: str) -> PrintTemplate | None:
    return PrintTemplate.objects.filter(document=document).order_by("-version").first()


def layout_for(document: str) -> dict | None:
    """The layout to print with, or None for the standard print."""
    found = current(document)
    return found.layout if found else None


def _number(value, name: str, low: float, high: float) -> float:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise TemplateError(f"{name} must be a number.") from None
    if not number.is_finite() or number < Decimal(str(low)) or number > Decimal(str(high)):
        raise TemplateError(f"{name} must be from {low} to {high}.")
    return float(round(number, 1))


def clean(document: str, layout) -> dict:
    """Check a layout from the designer and keep only what it may hold."""
    spec = kind(document)
    if not isinstance(layout, dict) or not isinstance(layout.get("blocks"), list):
        raise TemplateError("The layout has no blocks.")
    labels = {key: (label, may_hide) for key, label, may_hide in spec.blocks}
    seen, out, texts = set(), [], 0
    for raw in layout["blocks"]:
        if not isinstance(raw, dict):
            raise TemplateError("A block is not readable.")
        key = str(raw.get("key", ""))
        own = key.startswith("text-")
        if not own and key not in labels:
            raise TemplateError(f"Unknown block {key!r}.")
        if key in seen:
            raise TemplateError(f"The block {key!r} is there twice.")
        seen.add(key)
        name = "Your text" if own else labels[key][0]
        block = {
            "key": key,
            "x": _number(raw.get("x"), f"{name}: left", 0, PAGE_W_MM - 5),
            "y": _number(raw.get("y"), f"{name}: top", 0, PAGE_H_MM - 5),
            "w": _number(raw.get("w"), f"{name}: width", 5, PAGE_W_MM),
            "h": _number(raw.get("h"), f"{name}: height", 4, PAGE_H_MM),
            "size": _number(raw.get("size", 9), f"{name}: text size", 6, 24),
            "align": raw.get("align") if raw.get("align") in ALIGN else "left",
        }
        if block["x"] + block["w"] > PAGE_W_MM + 0.05 or block["y"] + block["h"] > PAGE_H_MM + 0.05:
            raise TemplateError(f"{name} goes past the edge of the page.")
        if raw.get("hidden"):
            if not own and not labels[key][1]:
                raise TemplateError(f"{name} must stay on the document.")
            block["hidden"] = True
        if own:
            texts += 1
            text = str(raw.get("text", "")).strip()
            if not text:
                raise TemplateError("A text block is empty: type its text or remove it.")
            block["text"] = text[:500]
        out.append(block)
    missing = [labels[k][0] for k in labels if k not in seen]
    if missing:
        raise TemplateError(f"The layout must have every block: {', '.join(missing)} missing.")
    if texts > MAX_TEXT_BLOCKS:
        raise TemplateError(f"At most {MAX_TEXT_BLOCKS} text blocks.")
    return {"blocks": out}


def save(user: User, document: str, layout, note: str = "") -> PrintTemplate:
    if not can_edit(user):
        raise TemplateError("Only the Admin and the Director change the layout of documents.")
    cleaned = clean(document, layout)
    with transaction.atomic(), audit_context("print_template_saved", note):
        last = (
            PrintTemplate.objects.select_for_update().filter(document=document).order_by("-version")
        ).first()
        return PrintTemplate.objects.create(
            document=document,
            version=(last.version + 1) if last else 1,
            layout=cleaned,
            note=str(note or "").strip()[:200],
            created_by=user,
        )


def reset(user: User, document: str) -> PrintTemplate:
    return save(user, document, kind(document).standard, "Back to the standard layout")


def restore(user: User, document: str, version) -> PrintTemplate:
    old = PrintTemplate.objects.filter(document=document, version=version).first()
    if old is None:
        raise TemplateError("That version does not exist.")
    return save(user, document, old.layout, f"Version {old.version} brought back")


def preview(user: User, document: str, layout) -> bytes:
    """The latest document printed with an unsaved layout, to check it before saving."""
    if not can_edit(user):
        raise TemplateError("Only the Admin and the Director change the layout of documents.")
    spec = kind(document)
    sample = spec.sample()
    if sample is None:
        raise TemplateError(
            f"Make a {spec.label.lower()} first: the preview prints the latest one."
        )
    return spec.print_with(sample, clean(document, layout))


def page(user: User, document: str) -> dict:
    spec = kind(document)
    found = current(document)
    history = PrintTemplate.objects.filter(document=document).select_related("created_by")
    return {
        "document": document,
        "label": spec.label,
        "page": {"width": PAGE_W_MM, "height": PAGE_H_MM},
        "blocks": [{"key": k, "label": label, "may_hide": h} for k, label, h in spec.blocks],
        "table": spec.table,
        "standard": spec.standard,
        "layout": found.layout if found else spec.standard,
        "version": found.version if found else None,
        "history": [
            {
                "version": t.version,
                "note": t.note,
                "by": t.created_by.full_name,
                "at": t.created_at,
            }
            for t in history.order_by("-version")[:50]
        ],
        "can_edit": can_edit(user),
    }


def documents() -> list[dict]:
    out = []
    for key, spec in _documents().items():
        found = current(key)
        out.append(
            {"document": key, "label": spec.label, "version": found.version if found else None}
        )
    return out
