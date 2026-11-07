"""Routings for machined parts (backlog P3-03; spec 7.1).

- A routing lists a part's operations in order (10, 20, 30 ...): each in a **section** (the
  machining method: manual milling, lathe, shaping ...) and optionally on one machine of
  it, with the standard **setup** minutes per batch and **run** minutes per piece; or
  **subcontracted** to a supplier at a standard cost per piece.
- **Revisions**: the Production Planner prepares a draft (new, a copy of the part's routing,
  or a copy of another part's), linked to the drawing revision, and submits it; the
  **Production Manager** approves it (approval engine, "routing"; never the person who
  prepared it, rule 5) or sends it back with a reason. The approved revision replaces the
  part's routing in force, which becomes obsolete. One routing in force and one open draft
  per part (database). Approved and obsolete routings never change and are never deleted
  (database); job orders copy the routing in force (P3-11), so a later revision never alters
  them.
- Excel export, and import of drafts (all or nothing, after a check).
"""

import io
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException

from apps.core import approvals
from apps.core.access import division_scope, effective_access
from apps.core.approvals import ApprovalError
from apps.core.audit import audit_context
from apps.core.models import ApprovalLog, ApprovalState, User
from apps.inventory.models import Item
from apps.masters.models import Machine, Section, Supplier

from .models import Routing, RoutingOperation

DOC = "routing"
MAX_BYTES = 5 * 1024 * 1024
St = Routing.Status


class RoutingError(Exception):
    pass


class ImportRefused(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("Nothing was imported.")
        self.errors = errors


def can_prepare(user: User) -> bool:
    return effective_access(user).has("production_planning", "enter")


def _check(user: User) -> None:
    if not can_prepare(user):
        raise RoutingError("Only the Production Planner prepares routings.")


def _text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value if value is not None else "").split())


def _decimal(value, label: str, places: int) -> Decimal:
    text = _text(value).replace(",", "")
    if not text:
        return Decimal(0)
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise RoutingError(f"The {label} is a number.") from None
    if not number.is_finite() or number < 0:
        raise RoutingError(f"The {label} is 0 or more.")
    if number != number.quantize(Decimal(1).scaleb(-places)):
        raise RoutingError(f"The {label} has at most {places} decimal places.")
    return number


def _yes(value) -> bool:
    return _text(value).lower() in ("true", "1", "yes", "y")


# --- Operations ----------------------------------------------------------------------------------


def _operations(user: User, rows) -> list[dict]:
    if not rows:
        raise RoutingError("Give at least one operation.")
    scope = division_scope(user)
    out, seqs = [], set()
    for n, row in enumerate(rows, start=1):
        where = f"Operation {n}"
        try:
            seq = int(_text(row.get("seq")) or n * 10)
        except ValueError:
            raise RoutingError(f"{where}: the number is a whole number, e.g. 10.") from None
        if not 1 <= seq <= 9999 or seq in seqs:
            raise RoutingError(f"{where}: the operation numbers are 1 to 9999, each once.")
        seqs.add(seq)
        where = f"Operation {seq}"
        name = _text(row.get("name"))[:100]
        if not name:
            raise RoutingError(f"{where}: give the operation, e.g. Face and drill.")
        sub = _yes(row.get("subcontract"))
        section = machine = supplier = None
        cost = None
        code = _text(row.get("section")).upper()
        if code:
            section = Section.objects.filter(code=code, division__in=scope, is_active=True).first()
            if section is None:
                raise RoutingError(f"{where}: there is no section {code} in your divisions.")
        code = _text(row.get("machine")).upper()
        if code:
            machine = Machine.objects.filter(code=code).select_related("section").first()
            if machine is None:
                raise RoutingError(f"{where}: there is no machine {code}.")
            if section is None:
                section = machine.section
            elif machine.section_id != section.pk:
                raise RoutingError(f"{where}: machine {code} is not in section {section.code}.")
        if sub:
            code = _text(row.get("supplier")).upper()
            supplier = Supplier.objects.filter(code=code).first() if code else None
            if supplier is None:
                raise RoutingError(f"{where}: give the supplier who does the work.")
            cost = _decimal(row.get("subcontract_cost"), "cost per piece", 2)
        elif section is None:
            raise RoutingError(f"{where}: give the section (the machining method).")
        out.append(
            {
                "seq": seq,
                "name": name,
                "section": section,
                "machine": machine,
                "setup_min": _decimal(row.get("setup_min"), "setup minutes", 2),
                "run_min": _decimal(row.get("run_min"), "run minutes per piece", 3),
                "subcontract": sub,
                "supplier": supplier,
                "subcontract_cost": cost,
                "notes": _text(row.get("notes"))[:300],
            }
        )
    return sorted(out, key=lambda o: o["seq"])


def _item(code) -> Item:
    code = _text(code).upper()
    item = Item.objects.filter(code=code).first()
    if item is None:
        raise RoutingError(f"There is no item {code}.")
    return item


def _replace_operations(routing: Routing, operations: list[dict]) -> None:
    routing.operations.all().delete()
    RoutingOperation.objects.bulk_create(RoutingOperation(routing=routing, **o) for o in operations)


def _next_revision(item: Item) -> int:
    return (Routing.objects.filter(item=item).aggregate(top=Max("revision"))["top"] or 0) + 1


def _open(item: Item) -> Routing | None:
    return Routing.objects.filter(item=item, status__in=[St.DRAFT, St.AWAITING]).first()


# --- Drafts --------------------------------------------------------------------------------------


def create(user: User, values: dict) -> Routing:
    """A new draft for a part, from the operations given."""
    _check(user)
    item = _item(values.get("item"))
    operations = _operations(user, values.get("operations"))
    with audit_context("routing_drafted", item.code), transaction.atomic():
        if _open(item):
            raise RoutingError(f"{item.code} already has a routing being prepared.")
        routing = Routing.objects.create(
            item=item,
            revision=_next_revision(item),
            drawing_revision=_text(values.get("drawing_revision"))[:20],
            notes=str(values.get("notes") or "").strip()[:2000],
            created_by=user,
        )
        _replace_operations(routing, operations)
        return routing


def update(user: User, routing: Routing, values: dict) -> Routing:
    _check(user)
    if routing.status != St.DRAFT:
        raise RoutingError(
            f"Revision {routing.revision} is {routing.get_status_display().lower()}."
        )
    operations = _operations(user, values["operations"]) if "operations" in values else None
    with audit_context("routing_changed", routing.item.code), transaction.atomic():
        routing = Routing.objects.select_for_update().get(pk=routing.pk)
        if "drawing_revision" in values:
            routing.drawing_revision = _text(values.get("drawing_revision"))[:20]
        if "notes" in values:
            routing.notes = str(values.get("notes") or "").strip()[:2000]
        routing.save()
        if operations is not None:
            _replace_operations(routing, operations)
        return routing


def copy(user: User, source: Routing, item_code: str | None = None) -> Routing:
    """A draft copy: the next revision of the same part, or a new routing for another part."""
    _check(user)
    item = _item(item_code) if item_code else source.item
    with audit_context("routing_copied", f"{source.item.code} rev {source.revision}"):
        with transaction.atomic():
            if _open(item):
                raise RoutingError(f"{item.code} already has a routing being prepared.")
            routing = Routing.objects.create(
                item=item,
                revision=_next_revision(item),
                drawing_revision=source.drawing_revision if item == source.item else "",
                notes=source.notes,
                created_by=user,
            )
            RoutingOperation.objects.bulk_create(
                RoutingOperation(
                    routing=routing,
                    **{
                        f.name: getattr(op, f.name)
                        for f in RoutingOperation._meta.concrete_fields
                        if f.name not in ("id", "routing")
                    },
                )
                for op in source.operations.all()
            )
            return routing


def delete(user: User, routing: Routing) -> None:
    _check(user)
    if routing.status != St.DRAFT:
        raise RoutingError("Only a draft is deleted; an approved routing becomes obsolete.")
    with audit_context("routing_draft_deleted", routing.item.code), transaction.atomic():
        routing.delete()


# --- Approval ------------------------------------------------------------------------------------


def submit(user: User, routing: Routing) -> Routing:
    _check(user)
    with transaction.atomic():
        routing = Routing.objects.select_for_update().select_related("item").get(pk=routing.pk)
        if routing.status != St.DRAFT:
            raise RoutingError("Only a draft is sent for approval.")
        if not routing.operations.exists():
            raise RoutingError("Give at least one operation.")
        try:
            approvals.submit(
                user,
                DOC,
                routing.pk,
                created_by=routing.created_by,
                title=f"Routing {routing.item.code} rev {routing.revision}: {routing.item.name}",
                link="/routings",
            )
        except ApprovalError as error:
            raise RoutingError(str(error)) from None
        with audit_context("routing_submitted", routing.item.code):
            routing.status = St.AWAITING
            routing.save(update_fields=["status"])
        return routing


def decide(user: User, routing: Routing, action: str, reason: str = "") -> Routing:
    reason = " ".join((reason or "").split())
    with transaction.atomic():
        routing = Routing.objects.select_for_update().select_related("item").get(pk=routing.pk)
        if routing.status != St.AWAITING:
            raise RoutingError("This routing is not waiting for approval.")
        try:
            if action == "approve":
                state = approvals.approve(user, DOC, routing.pk, reason)
                if state.status != ApprovalState.Status.APPROVED:
                    return routing
                with audit_context("routing_approved", routing.item.code):
                    Routing.objects.filter(item=routing.item, status=St.APPROVED).update(
                        status=St.OBSOLETE
                    )
                    routing.status, routing.approved_at = St.APPROVED, timezone.now()
                    routing.save(update_fields=["status", "approved_at"])
            elif action == "send_back":
                approvals.send_back(user, DOC, routing.pk, reason)
                with audit_context("routing_sent_back", reason):
                    routing.status = St.DRAFT
                    routing.save(update_fields=["status"])
            else:
                raise RoutingError("Unknown action.")
        except ApprovalError as error:
            raise RoutingError(str(error)) from None
        return routing


def in_force(item: Item) -> Routing | None:
    return Routing.objects.filter(item=item, status=St.APPROVED).first()


# --- Listing -------------------------------------------------------------------------------------


def _number(value: Decimal) -> str:
    return f"{value.normalize():f}"


def payload(routing: Routing, user: User) -> dict:
    ops = list(routing.operations.select_related("section", "machine", "supplier"))
    state = approvals.state_of(DOC, routing.pk) if routing.status == St.AWAITING else None
    returned = None
    if routing.status == St.DRAFT:
        log = (
            ApprovalLog.objects.filter(document_type=DOC, document_id=routing.pk)
            .order_by("-acted_at", "-pk")
            .first()
        )
        if log is not None and log.action == ApprovalLog.Action.RETURN:
            returned = log.reason
    return {
        "id": routing.pk,
        "item": routing.item.code,
        "item_name": routing.item.name,
        "revision": routing.revision,
        "drawing_revision": routing.drawing_revision,
        "status": routing.status,
        "status_label": routing.get_status_display(),
        "notes": routing.notes,
        "created_by": routing.created_by.full_name,
        "approved_at": routing.approved_at,
        "setup_min": _number(sum((o.setup_min for o in ops), Decimal(0))),
        "run_min": _number(sum((o.run_min for o in ops if not o.subcontract), Decimal(0))),
        "subcontract_cost": f"{sum((o.subcontract_cost or 0 for o in ops), Decimal(0)):.2f}",
        "operations": [
            {
                "seq": o.seq,
                "name": o.name,
                "section": o.section.code if o.section_id else "",
                "section_name": o.section.name if o.section_id else "",
                "machine": o.machine.code if o.machine_id else "",
                "setup_min": _number(o.setup_min),
                "run_min": _number(o.run_min),
                "subcontract": o.subcontract,
                "supplier": o.supplier.code if o.supplier_id else "",
                "supplier_name": o.supplier.name if o.supplier_id else "",
                "subcontract_cost": f"{o.subcontract_cost:.2f}"
                if o.subcontract_cost is not None
                else "",
                "notes": o.notes,
            }
            for o in ops
        ],
        "returned_reason": returned,
        "can_edit": routing.status == St.DRAFT and can_prepare(user),
        "can_decide": state is not None and approvals.why_not(user, state) is None,
    }


def search(q: str = "", status: str = ""):
    found = Routing.objects.select_related("item", "created_by")
    if q:
        found = found.filter(Q(item__code__icontains=q) | Q(item__name__icontains=q))
    if status:
        found = found.filter(status=status)
    else:
        found = found.exclude(status=St.OBSOLETE)
    return found[:300]


# --- Excel ---------------------------------------------------------------------------------------

COLUMNS = [
    ("item", "Item code"),
    ("revision", "Revision"),
    ("drawing_revision", "Drawing revision"),
    ("seq", "Op no"),
    ("name", "Operation"),
    ("section", "Section code"),
    ("machine", "Machine code"),
    ("setup_min", "Setup (min)"),
    ("run_min", "Run (min per piece)"),
    ("subcontract", "Subcontract (yes/no)"),
    ("supplier", "Supplier code"),
    ("subcontract_cost", "Cost per piece"),
    ("notes", "Notes"),
]


def export_workbook() -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Routings"
    sheet.append([label for _, label in COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for r in Routing.objects.filter(status__in=[St.APPROVED, St.DRAFT]).select_related("item"):
        for o in r.operations.select_related("section", "machine", "supplier"):
            sheet.append(
                [
                    r.item.code,
                    r.revision,
                    r.drawing_revision,
                    o.seq,
                    o.name,
                    o.section.code if o.section_id else "",
                    o.machine.code if o.machine_id else "",
                    o.setup_min,
                    o.run_min,
                    "yes" if o.subcontract else "no",
                    o.supplier.code if o.supplier_id else "",
                    o.subcontract_cost,
                    o.notes,
                ]
            )
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 16
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def import_workbook(user: User, content: bytes, *, dry_run: bool) -> dict:
    """Each part in the file becomes a draft (a new revision), or replaces its open draft."""
    if not can_prepare(user):
        raise ImportRefused(["Only the Production Planner prepares routings."])
    if len(content) > MAX_BYTES:
        raise ImportRefused(["The file must be 5 MB or smaller."])
    try:
        rows = list(
            load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            .worksheets[0]
            .iter_rows(values_only=True)
        )
    except (InvalidFileException, OSError, KeyError, ValueError):
        raise ImportRefused(["The file is not an Excel workbook (.xlsx)."]) from None
    if not rows:
        raise ImportRefused(["The file is empty."])
    head = [_text(c).lower() for c in rows[0]]
    index = {key: head.index(label.lower()) for key, label in COLUMNS if label.lower() in head}
    missing = [label for key, label in COLUMNS[:5] if key in ("item", "name") and key not in index]
    if missing:
        raise ImportRefused(["The first row must hold the column names of the export."])
    parts: dict[str, dict] = {}
    for row in rows[1:]:
        values = {k: row[i] for k, i in index.items() if i < len(row)}
        code = _text(values.get("item")).upper()
        if not code:
            continue
        part = parts.setdefault(code, {"drawing_revision": "", "operations": []})
        if _text(values.get("drawing_revision")):
            part["drawing_revision"] = _text(values.get("drawing_revision"))
        part["operations"].append(values)
    errors, made = [], 0
    with transaction.atomic():
        for code, part in parts.items():
            try:
                with transaction.atomic():
                    item = _item(code)
                    current = _open(item)
                    if current is not None and current.status == St.AWAITING:
                        raise RoutingError("its routing is waiting for approval.")
                    if current is not None:
                        update(user, current, part)
                    else:
                        create(user, {"item": code, **part})
                    made += 1
            except RoutingError as error:
                errors.append(f"{code}: {error}")
        if errors:
            transaction.set_rollback(True)
            raise ImportRefused(errors[:50])
        if dry_run:
            transaction.set_rollback(True)
    return {"drafts": made, "saved": not dry_run}
