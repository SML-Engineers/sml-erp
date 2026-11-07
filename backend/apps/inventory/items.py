"""Items and stores (backlog P16-03, spec 5A.3).

- The Purchasing Officer and the stores person (Purchasing or Stores: Enter) add and change
  items; so does the Accountant. Only the Accountant (Accounting: Enter) chooses an item's
  accounts; otherwise a stock item takes the inventory account for its category.
- A code is 1 to 20 letters, digits or dashes; once a document has used the item it never
  changes, and the item can only be deactivated, with a reason (rule 9, database guard).
- Stores are set by the Admin (Settings: Manage), per division: main stores, and one
  quarantine and one rejected store each.
- Export and import in one Excel layout; an import is checked first and is all or nothing.
"""

import io
import re
import zipfile
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from apps.accounting.models import Account
from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.masters import excel
from apps.masters.models import Material
from apps.masters.services import MastersError

from .models import Item, Store
from .packages import PackageError, number

# The starter chart's inventory accounts (accounting catalogue STARTER_CHART_V1); the
# Accountant can choose another per item.
DEFAULT_INVENTORY_ACCOUNT = {
    Item.Category.RAW_MATERIAL: "1210",
    Item.Category.BOUGHT_OUT: "1210",
    Item.Category.CONSUMABLE: "1240",
    Item.Category.SPARE: "1240",
    Item.Category.PACKING: "1240",
    Item.Category.FINISHED: "1230",
}
INVENTORY_TYPES = ("other_current_asset",)
EXPENSE_TYPES = ("expense", "cost_of_goods_sold", "other_expense")
TEXT_FIELDS = ("name", "description", "notes")


class ItemError(MastersError):
    pass


# Item codes as SML writes them, e.g. 48/BL/08 or EN8-40 (owner's sample PO26061701).
ITEM_CODE = re.compile(r"^[A-Z0-9][A-Z0-9/.\-]{0,19}$")


def normalise_code(code: str, what: str) -> str:
    code = (code or "").strip().upper()
    pattern = ITEM_CODE if what == "item" else STORE_CODE
    if not pattern.match(code):
        allowed = (
            "letters, digits, dashes, slashes or dots"
            if what == "item"
            else ("letters, digits or dashes")
        )
        raise ItemError(
            f"The {what} code must be 1 to 20 {allowed}, starting with a letter or digit, "
            "for example 48/BL/08."
            if what == "item"
            else f"The {what} code must be 1 to 20 {allowed}, for example IM-RESIN."
        )
    return code


STORE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{0,19}$")


def can_enter(user: User) -> bool:
    access = effective_access(user)
    return (
        access.has("purchasing", "enter")
        or access.has("stores", "enter")
        or access.has("accounting", "enter")
    )


def can_set_accounts(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def can_view(user: User) -> bool:
    access = effective_access(user)
    return access.has("stores", "view") or access.has("purchasing", "view")


def can_manage_stores(user: User) -> bool:
    return effective_access(user).has("settings", "manage")


# --- Checks -----------------------------------------------------------------------------


def _choice(values: dict, field: str, choices, what: str) -> dict:
    if field not in values:
        return {}
    value = (values[field] or "").strip()
    if value not in choices.values:
        raise ItemError(f"Choose the {what}.")
    return {field: value}


def _account(value, types, what: str) -> Account | None:
    if value in (None, ""):
        return None
    account = value if isinstance(value, Account) else None
    if account is None:
        account = Account.objects.filter(number=str(value).strip(), is_active=True).first()
    if account is None or not account.is_active:
        raise ItemError(f"There is no active account {value} for the {what}.")
    if account.account_type not in types:
        raise ItemError(f"{account.number} {account.name} cannot be the {what}.")
    return account


def _check(values: dict, user: User, item: Item | None) -> dict:
    cleaned = {}
    for field in TEXT_FIELDS:
        if field in values:
            cleaned[field] = (values[field] or "").strip()
    if "name" in cleaned and not cleaned["name"]:
        raise ItemError("The item name is required.")
    cleaned |= _choice(values, "category", Item.Category, "category")
    cleaned |= _choice(values, "unit", Item.Unit, "unit")
    cleaned |= _choice(values, "package_type", Item.PackageType, "way it arrives")
    for flag in ("is_stock", "inspection_required"):
        if flag in values:
            cleaned[flag] = bool(values[flag])
    if "division" in values:
        code = values["division"]
        if code in (None, ""):
            cleaned["division"] = None
        else:
            division = Division.objects.filter(code=str(code).upper(), is_active=True).first()
            if division is None:
                raise ItemError(f"There is no active division {code}.")
            cleaned["division"] = division
    if "material" in values:
        code = values["material"]
        if code in (None, ""):
            cleaned["material"] = None
        else:
            material = Material.objects.filter(code=str(code).upper(), is_active=True).first()
            if material is None:
                raise ItemError(f"There is no active costing material {code}.")
            cleaned["material"] = material
    for field, what, places, blank_is in (
        ("package_tare", "usual tare", 3, Decimal("0")),
        ("weight_tolerance_pct", "weight tolerance", 2, Decimal("0")),
        ("standard_kg_per_m", "standard kg per metre", 4, None),
        ("density", "density", 3, None),
    ):
        if field not in values:
            continue
        try:
            value = number(values[field], what, places)
        except PackageError as error:
            raise ItemError(str(error)) from None
        if field == "weight_tolerance_pct" and value is not None and value > 100:
            raise ItemError("The weight tolerance is a percentage up to 100.")
        if blank_is is None and value == 0:
            value = None
        cleaned[field] = blank_is if value is None else value
    for field, types, what in (
        ("inventory_account", INVENTORY_TYPES, "inventory account"),
        ("expense_account", EXPENSE_TYPES, "expense account"),
    ):
        if field not in values:
            continue
        chosen = _account(values[field], types, what)
        current = getattr(item, field) if item else None
        if chosen != current and not can_set_accounts(user):
            raise ItemError("Only the Accountant chooses an item's accounts.")
        cleaned[field] = chosen
    return cleaned


def _finish(item: Item) -> None:
    """The rules that depend on several fields together."""
    if not item.is_stock:
        item.inspection_required = False
        item.package_type = Item.PackageType.NONE
        item.inventory_account = None
    else:
        item.expense_account = None
        if item.inventory_account is None:
            number = DEFAULT_INVENTORY_ACCOUNT.get(item.category)
            item.inventory_account = Account.objects.filter(number=number, is_active=True).first()
        if item.inventory_account is None:
            raise ItemError(
                "Choose the inventory account for this stock item (the Accountant sets it)."
            )


# --- Items ------------------------------------------------------------------------------


def create_item(user: User, values: dict) -> Item:
    if not can_enter(user):
        raise ItemError("You cannot add items.")
    code = normalise_code(values.get("code", ""), "item")
    cleaned = _check(values, user, None)
    if not cleaned.get("name") or not cleaned.get("category"):
        raise ItemError("Give the item's code, name and category.")
    if Item.objects.filter(code=code).exists():
        raise ItemError(f"There is already an item {code}.")
    with audit_context("item_created"), transaction.atomic():
        item = Item(code=code, created_by=user, **cleaned)
        _finish(item)
        item.save()
        return item


def update_item(user: User, item: Item, values: dict, *, reason: str = "") -> Item:
    """Change an item's details. The code changes only while no document has used it."""
    if not can_enter(user):
        raise ItemError("You cannot change items.")
    with transaction.atomic():
        item = Item.objects.select_for_update().get(pk=item.pk)
        cleaned = _check(values, user, item)
        if "code" in values:
            code = normalise_code(values["code"], "item")
            if code != item.code:
                if item.first_used_at:
                    raise ItemError(f"Item {item.code} has been used: its code cannot change.")
                if Item.objects.filter(code=code).exclude(pk=item.pk).exists():
                    raise ItemError(f"There is already an item {code}.")
                cleaned["code"] = code
        for key, value in cleaned.items():
            setattr(item, key, value)
        _finish(item)
        item.updated_at = timezone.now()
        with audit_context("item_changed", reason):
            item.save()
        return item


def set_active(user: User, item: Item, active: bool, *, reason: str = "") -> Item:
    if not can_enter(user):
        raise ItemError("You cannot change items.")
    if not active and not (reason or "").strip():
        raise ItemError("Give a reason for deactivating the item.")
    with transaction.atomic():
        item = Item.objects.select_for_update().get(pk=item.pk)
        if item.is_active == active:
            return item
        item.is_active = active
        item.updated_at = timezone.now()
        event = "item_reactivated" if active else "item_deactivated"
        with audit_context(event, reason):
            item.save(update_fields=["is_active", "updated_at"])
        return item


def delete_item(user: User, item: Item) -> None:
    """An item no document has used can be removed; a used one only deactivated."""
    if not can_enter(user):
        raise ItemError("You cannot remove items.")
    if item.first_used_at:
        raise ItemError(f"Item {item.code} has been used: deactivate it instead.")
    with audit_context("item_deleted"), transaction.atomic():
        item.delete()


def mark_used(item: Item) -> None:
    """Called when a document first uses the item (purchase orders, P16-04)."""
    Item.objects.filter(pk=item.pk, first_used_at__isnull=True).update(first_used_at=timezone.now())


def search(queryset, text: str):
    text = (text or "").strip()
    if not text:
        return queryset
    query = Q()
    for word in text.split():
        query &= Q(code__icontains=word) | Q(name__icontains=word) | Q(description__icontains=word)
    return queryset.filter(query)


# --- Stores -----------------------------------------------------------------------------


def create_store(user: User, values: dict) -> Store:
    if not can_manage_stores(user):
        raise ItemError("Only the Admin sets up stores.")
    code = normalise_code(values.get("code", ""), "store")
    name = (values.get("name") or "").strip()
    if not name:
        raise ItemError("The store name is required.")
    division = Division.objects.filter(
        code=str(values.get("division", "")).upper(), is_active=True
    ).first()
    if division is None or division.division_type != Division.Type.PRODUCTION:
        raise ItemError("A store belongs to a production division (Workshop or Moulding).")
    kind = values.get("kind") or Store.Kind.MAIN
    if kind not in Store.Kind.values:
        raise ItemError("Choose the kind of store.")
    if Store.objects.filter(code=code).exists():
        raise ItemError(f"There is already a store {code}.")
    if kind != Store.Kind.MAIN and Store.objects.filter(division=division, kind=kind).exists():
        raise ItemError(f"{division.code} already has its {Store.Kind(kind).label.lower()} store.")
    with audit_context("store_created"), transaction.atomic():
        return Store.objects.create(code=code, name=name, division=division, kind=kind)


def update_store(user: User, store: Store, values: dict, *, reason: str = "") -> Store:
    """Rename a store, or deactivate it (with a reason) or reactivate it."""
    if not can_manage_stores(user):
        raise ItemError("Only the Admin sets up stores.")
    with transaction.atomic():
        store = Store.objects.select_for_update().get(pk=store.pk)
        event = "store_changed"
        if "name" in values:
            name = (values["name"] or "").strip()
            if not name:
                raise ItemError("The store name is required.")
            store.name = name
        if "is_active" in values and bool(values["is_active"]) != store.is_active:
            if not values["is_active"]:
                if not (reason or "").strip():
                    raise ItemError("Give a reason for deactivating the store.")
                if store.kind != Store.Kind.MAIN:
                    raise ItemError(
                        "Each division needs its quarantine and rejected stores; rename it instead."
                    )
            store.is_active = bool(values["is_active"])
            event = "store_reactivated" if store.is_active else "store_deactivated"
        with audit_context(event, reason):
            store.save()
        return store


# --- Excel ------------------------------------------------------------------------------

SHEET = "Items"
COLUMNS = [
    "Code",
    "Name",
    "Description",
    "Category",
    "Unit",
    "Stock item",
    "Arrives as",
    "QC inspection",
    "Inventory account",
    "Expense account",
    "Costing material",
    "Division",
    "Notes",
    "Active",
]


def _label(choices, value) -> str:
    return dict(choices.choices).get(value, value)


def export_workbook(rows) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    lines = [
        [
            i.code,
            i.name,
            i.description,
            _label(Item.Category, i.category),
            i.unit,
            "Yes" if i.is_stock else "No",
            _label(Item.PackageType, i.package_type),
            "Yes" if i.inspection_required else "No",
            i.inventory_account.number if i.inventory_account else "",
            i.expense_account.number if i.expense_account else "",
            i.material.code if i.material else "",
            i.division.code if i.division else "",
            i.notes,
            "Yes" if i.is_active else "No",
        ]
        for i in rows
    ]
    excel._sheet(workbook, SHEET, COLUMNS, lines)
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()


def _from_label(choices, text: str, what: str) -> str:
    text = text.strip()
    for value, label in choices.choices:
        if text.lower() in (value.lower(), label.lower()):
            return value
    raise ItemError(f"Unknown {what} {text!r}.")


def _import_row(row: dict, *, user: User, reason: str) -> str:
    text = {column: excel._text(row.get(column)) for column in COLUMNS}
    values = {
        "name": text["Name"],
        "description": text["Description"],
        "category": _from_label(Item.Category, text["Category"], "category"),
        "unit": _from_label(Item.Unit, text["Unit"] or "pcs", "unit"),
        "is_stock": excel._yes_no(row.get("Stock item")) if text["Stock item"] else True,
        "package_type": _from_label(
            Item.PackageType, text["Arrives as"] or "none", "way it arrives"
        ),
        "inspection_required": excel._yes_no(row.get("QC inspection"))
        if text["QC inspection"]
        else True,
        "material": text["Costing material"],
        "division": text["Division"],
        "notes": text["Notes"],
    }
    # Accounts come in only when the importer may set them; otherwise defaults apply.
    if can_set_accounts(user):
        values["inventory_account"] = text["Inventory account"]
        values["expense_account"] = text["Expense account"]
    active = excel._yes_no(row.get("Active")) if text["Active"] else True
    code = normalise_code(text["Code"], "item")
    item = Item.objects.filter(code=code).first()
    if item is None:
        if not active:
            raise ItemError("A new item cannot be imported as inactive.")
        create_item(user, {"code": code, **values})
        return "created"
    item = update_item(user, item, values, reason=reason)
    if active != item.is_active:
        set_active(user, item, active, reason=reason)
    return "updated"


def import_workbook(content: bytes, *, user: User, reason: str, dry_run: bool) -> dict:
    """Apply a workbook of items. Returns counts; raises excel.ImportRefused listing every
    refused row, in which case nothing is saved."""
    if not can_enter(user):
        raise excel.ImportRefused(["You cannot add or change items."])
    if not (reason or "").strip():
        raise excel.ImportRefused(["Give a reason for the import."])
    if len(content) > excel.MAX_BYTES:
        raise excel.ImportRefused(["The file must be 5 MB or smaller."])
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, OSError, KeyError, ValueError):
        raise excel.ImportRefused(["The file is not an Excel workbook (.xlsx)."]) from None
    rows = excel._rows(workbook, SHEET, COLUMNS)
    if not rows:
        raise excel.ImportRefused([f"The workbook has no rows on a sheet called {SHEET}."])
    counts = {"created": 0, "updated": 0}
    errors = []
    with transaction.atomic():
        for number, row in rows:
            try:
                with transaction.atomic():
                    counts[_import_row(row, user=user, reason=reason)] += 1
            except MastersError as error:
                errors.append(f"Row {number}: {error}")
        if errors or dry_run:
            transaction.set_rollback(True)
    if errors:
        raise excel.ImportRefused(errors)
    return counts
