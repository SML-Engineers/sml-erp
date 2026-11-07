"""Moulds (backlog P3-01; spec 7.1; owner, 7 Nov 2026).

- A mould makes one or more parts (items), each with its cavities: a family mould makes
  several parts in one shot. Standard cycle time, shot weight with the runner, runner
  weight, clamping force needed, size (width, height, closed thickness), the machines it
  can run on, the preventive maintenance interval in shots and its shot count so far.
- **Owner**: the company, or a customer. Customer moulds are tracked for shots and
  maintenance but not costed. A company mould can be linked to its fixed asset once the
  Accountant has entered it in the register (none is there yet: owner, 7 Nov 2026).
- **Fit**: a warning (never a refusal) when a mould is set against a machine too small for
  it: clamping force, shot weight, tie-bar spacing (width and height, either way round),
  maximum mould height and thickness. A measure missing on either side is not checked.
- The Production Planner and the Admin maintain moulds (Production planning area); the code
  is fixed once a production document uses the mould, and a used mould is retired, never
  deleted (rule 9, database). Excel export and import (checked first, all or nothing) and
  QR labels like the factory structure (3A.1).
"""

import io
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException

from apps.assets.models import FixedAsset
from apps.core.access import division_scope, effective_access
from apps.core.audit import audit_context
from apps.core.models import Division, User
from apps.inventory.models import Item
from apps.masters.models import CODE_REGEX, Customer, Machine

from .models import Mould, MouldPart

MAX_BYTES = 5 * 1024 * 1024
MEASURES = ("tonnage_t", "width_mm", "height_mm", "thickness_mm")


class MouldError(Exception):
    pass


class ImportRefused(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("Nothing was imported.")
        self.errors = errors


def can_edit(user: User) -> bool:
    return effective_access(user).has("production_planning", "enter")


def visible(user: User):
    return Mould.objects.filter(division__in=division_scope(user))


# --- Values --------------------------------------------------------------------------------------


def _text(value) -> str:
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return " ".join(str(value if value is not None else "").split())


def _decimal(value, label: str, *, places: int, required=False) -> Decimal | None:
    text = _text(value).replace(",", "")
    if not text:
        if required:
            raise MouldError(f"Give the {label}.")
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        raise MouldError(f"The {label} is a number.") from None
    if not number.is_finite() or number < 0:
        raise MouldError(f"The {label} is 0 or more.")
    if number != number.quantize(Decimal(1).scaleb(-places)):
        raise MouldError(f"The {label} has at most {places} decimal place(s).")
    return number


def _whole(value, label: str) -> int | None:
    text = _text(value).replace(",", "")
    if not text:
        return None
    if not text.isdigit():
        raise MouldError(f"The {label} is a whole number.")
    return int(text)


def _parts(value) -> list[tuple[Item, int]]:
    """[{item: code, cavities: n}, ...] or "CODE x 2; CODE2 x 1"."""
    if isinstance(value, str):
        rows = []
        for piece in [p.strip() for p in value.split(";") if p.strip()]:
            m = re.match(r"^(\S+)\s*(?:[x×*:]\s*(\d+))?$", piece, re.IGNORECASE)
            if not m:
                raise MouldError(f"Write the parts as CODE x cavities; e.g. P-100 x 4 ({piece}).")
            rows.append({"item": m.group(1), "cavities": m.group(2) or "1"})
        value = rows
    out, seen = [], set()
    for row in value or []:
        code = _text(row.get("item")).upper()
        item = Item.objects.filter(code=code).first()
        if item is None:
            raise MouldError(f"There is no item {code}.")
        if item.pk in seen:
            raise MouldError(f"Part {code} is listed twice.")
        seen.add(item.pk)
        cavities = _whole(row.get("cavities"), "number of cavities")
        if not cavities or cavities > 512:
            raise MouldError(f"Part {code}: the cavities are 1 to 512.")
        out.append((item, cavities))
    if not out:
        raise MouldError("Give the part the mould makes and its cavities.")
    return out


def _machines(value) -> list[Machine]:
    if isinstance(value, str):
        value = [v.strip() for v in re.split(r"[;,]", value) if v.strip()]
    out = []
    for code in value or []:
        code = _text(code).upper()
        machine = Machine.objects.filter(code=code).first()
        if machine is None:
            raise MouldError(f"There is no machine {code}.")
        out.append(machine)
    return out


def _clean(values: dict, current: Mould | None) -> dict:
    out: dict = {}
    if current is None or "code" in values:
        code = _text(values.get("code")).upper()
        if not re.match(CODE_REGEX, code):
            raise MouldError(
                "The code is up to 20 capital letters, digits and dashes, e.g. MD-001."
            )
        if current is not None and code != current.code and current.first_used_at:
            raise MouldError(f"Mould {current.code} has been used: its code cannot change.")
        clash = Mould.objects.filter(code=code)
        if current is not None:
            clash = clash.exclude(pk=current.pk)
        if clash.exists():
            raise MouldError(f"There is already a mould {code}.")
        out["code"] = code
    if current is None or "name" in values:
        out["name"] = _text(values.get("name"))[:100]
        if not out["name"]:
            raise MouldError("Give the mould a name.")
    if current is None or "division" in values:
        code = _text(values.get("division") or "IM").upper()
        division = Division.objects.filter(code=code, is_active=True).first()
        if division is None:
            raise MouldError(f"There is no division {code}.")
        out["division"] = division
    if current is None or "cycle_time_s" in values:
        out["cycle_time_s"] = _decimal(
            values.get("cycle_time_s"), "standard cycle time (s)", places=2, required=True
        )
        if out["cycle_time_s"] <= 0:
            raise MouldError("The standard cycle time is more than 0 seconds.")
    if current is None or "shot_weight_g" in values:
        out["shot_weight_g"] = _decimal(
            values.get("shot_weight_g"), "shot weight with runner (g)", places=1, required=True
        )
        if out["shot_weight_g"] <= 0:
            raise MouldError("The shot weight is more than 0 g.")
    if current is None or "runner_weight_g" in values:
        out["runner_weight_g"] = _decimal(
            values.get("runner_weight_g"), "runner weight (g)", places=1
        ) or Decimal(0)
    for field in MEASURES:
        if current is None or field in values:
            label = str(Mould._meta.get_field(field).verbose_name).lower()
            out[field] = _decimal(values.get(field), label, places=1)
    if current is None or "pm_interval_shots" in values:
        out["pm_interval_shots"] = _whole(
            values.get("pm_interval_shots"), "maintenance interval (shots)"
        )
    if "status" in values:
        status = _text(values.get("status")).lower()
        labels = {label.lower(): code for code, label in Mould.Status.choices}
        status = labels.get(status, status)
        if status not in Mould.Status.values:
            raise MouldError("The status is Active, Under maintenance or Retired.")
        out["status"] = status
    if "notes" in values:
        out["notes"] = str(values.get("notes") or "").strip()[:2000]
    # Owner, customer and asset are checked together.
    owner = _text(values.get("owner") if "owner" in values else (current and current.owner))
    owner = (owner or "company").lower()
    if owner not in Mould.Owner.values:
        raise MouldError("The owner is Company or Customer.")
    out["owner"] = owner
    customer = current.customer if current and "customer" not in values else None
    if "customer" in values and _text(values.get("customer")):
        code = _text(values["customer"]).upper()
        customer = Customer.objects.filter(code=code).first()
        if customer is None:
            raise MouldError(f"There is no customer {code}.")
    asset = current.asset if current and "asset" not in values else None
    if "asset" in values and _text(values.get("asset")):
        code = _text(values["asset"]).upper()
        asset = FixedAsset.objects.filter(code=code).first()
        if asset is None:
            raise MouldError(f"There is no fixed asset {code}.")
        taken = Mould.objects.filter(asset=asset)
        if current is not None:
            taken = taken.exclude(pk=current.pk)
        if taken.exists():
            raise MouldError(f"Fixed asset {code} is already mould {taken.first().code}.")
    if owner == Mould.Owner.CUSTOMER:
        if customer is None:
            raise MouldError("Give the customer who owns the mould.")
        if asset is not None:
            raise MouldError("A customer's mould is not the company's fixed asset.")
    else:
        customer = None
    out["customer"], out["asset"] = customer, asset
    if out.get("runner_weight_g") is not None:
        shot = out.get("shot_weight_g", current.shot_weight_g if current else None)
        if shot is not None and out["runner_weight_g"] >= shot:
            raise MouldError("The runner weighs less than the whole shot.")
    if "parts" in values or current is None:
        out["parts"] = _parts(values.get("parts"))
    if "machines" in values:
        out["machines"] = _machines(values.get("machines"))
    return out


# --- Fit -----------------------------------------------------------------------------------------


def _n(value: Decimal) -> str:
    return f"{value.normalize():f}"


def fit(mould: Mould, machine: Machine) -> list[str]:
    """Why the mould may be too big for the machine (empty when it fits or is not known)."""
    out = []

    def over(need, have, what, unit):
        if need is not None and have is not None and need > have:
            out.append(f"{what}: the mould needs {_n(need)} {unit}, {machine.code} has {_n(have)}")

    over(mould.tonnage_t, machine.clamping_force_t, "Clamping force", "t")
    over(mould.shot_weight_g, machine.max_shot_weight_g, "Shot weight", "g")
    over(mould.thickness_mm, machine.max_mould_thickness_mm, "Mould thickness", "mm")
    over(mould.height_mm, machine.max_mould_height_mm, "Mould height", "mm")
    w, h = mould.width_mm, mould.height_mm
    th, tv = machine.tie_bar_h_mm, machine.tie_bar_v_mm
    if None not in (w, h, th, tv) and not ((w <= th and h <= tv) or (h <= th and w <= tv)):
        out.append(
            f"Tie bars: the mould is {_n(w)} x {_n(h)} mm, {machine.code} has {_n(th)} x "
            f"{_n(tv)} mm between its tie bars"
        )
    return out


def warnings(mould: Mould) -> list[str]:
    return [f"{m.code}: {w}" for m in mould.machines.all() for w in fit(mould, m)]


# --- Saving --------------------------------------------------------------------------------------


def _check_divisions(user: User, division: Division) -> None:
    if not division_scope(user).filter(pk=division.pk).exists():
        raise MouldError(f"Division {division.code} is not one of yours.")


def _apply(mould: Mould, values: dict) -> Mould:
    parts = values.pop("parts", None)
    machines = values.pop("machines", None)
    for key, value in values.items():
        setattr(mould, key, value)
    mould.save()
    if parts is not None:
        keep = {item.pk for item, _ in parts}
        mould.parts.exclude(item_id__in=keep).delete()
        for item, cavities in parts:
            MouldPart.objects.update_or_create(
                mould=mould, item=item, defaults={"cavities": cavities}
            )
    if machines is not None:
        mould.machines.set(machines)
    return mould


def create(user: User, values: dict) -> Mould:
    if not can_edit(user):
        raise MouldError("Only the Production Planner or the Admin keeps the moulds.")
    clean = _clean(values, None)
    _check_divisions(user, clean["division"])
    with audit_context("mould_created", ""), transaction.atomic():
        return _apply(Mould(), clean)


def update(user: User, mould: Mould, values: dict) -> Mould:
    if not can_edit(user):
        raise MouldError("Only the Production Planner or the Admin keeps the moulds.")
    clean = _clean(values, mould)
    _check_divisions(user, clean.get("division", mould.division))
    with audit_context("mould_changed", ""), transaction.atomic():
        mould = Mould.objects.select_for_update().get(pk=mould.pk)
        return _apply(mould, clean)


def delete(user: User, mould: Mould) -> None:
    if not can_edit(user):
        raise MouldError("Only the Production Planner or the Admin keeps the moulds.")
    if mould.first_used_at:
        raise MouldError(f"Mould {mould.code} has been used: retire it instead.")
    with audit_context("mould_deleted", mould.code), transaction.atomic():
        mould.delete()


def payload(mould: Mould) -> dict:
    due = None
    if mould.pm_interval_shots:
        due = mould.shots_at_last_pm + mould.pm_interval_shots
    return {
        "id": mould.pk,
        "code": mould.code,
        "name": mould.name,
        "division": mould.division.code,
        "owner": mould.owner,
        "owner_label": mould.get_owner_display(),
        "customer": mould.customer.code if mould.customer_id else "",
        "customer_name": mould.customer.name if mould.customer_id else "",
        "asset": mould.asset.code if mould.asset_id else "",
        "cycle_time_s": f"{mould.cycle_time_s}",
        "shot_weight_g": f"{mould.shot_weight_g}",
        "runner_weight_g": f"{mould.runner_weight_g}",
        **{f: (f"{getattr(mould, f)}" if getattr(mould, f) is not None else "") for f in MEASURES},
        "pm_interval_shots": mould.pm_interval_shots,
        "shot_count": mould.shot_count,
        "pm_due_at": due,
        "status": mould.status,
        "status_label": mould.get_status_display(),
        "notes": mould.notes,
        "in_use": mould.first_used_at is not None,
        "parts": [
            {"item": p.item.code, "name": p.item.name, "cavities": p.cavities}
            for p in mould.parts.select_related("item")
        ],
        "machines": [m.code for m in mould.machines.all()],
        "warnings": warnings(mould),
    }


def search(user: User, q: str = "", status: str = "") -> list[Mould]:
    found = visible(user).select_related("division", "customer", "asset")
    if q:
        found = found.filter(
            Q(code__icontains=q) | Q(name__icontains=q) | Q(parts__item__code__icontains=q)
        ).distinct()
    if status:
        found = found.filter(status=status)
    return list(found.prefetch_related("machines", "parts__item")[:500])


# --- Excel ---------------------------------------------------------------------------------------

COLUMNS = [
    ("code", "Code"),
    ("name", "Name"),
    ("division", "Division"),
    ("parts", "Parts (code x cavities; ...)"),
    ("owner", "Owner"),
    ("customer", "Customer code"),
    ("asset", "Fixed asset code"),
    ("cycle_time_s", "Cycle time (s)"),
    ("shot_weight_g", "Shot weight with runner (g)"),
    ("runner_weight_g", "Runner weight (g)"),
    ("tonnage_t", "Clamping force needed (t)"),
    ("width_mm", "Width (mm)"),
    ("height_mm", "Height (mm)"),
    ("thickness_mm", "Thickness, closed (mm)"),
    ("machines", "Compatible machines (codes; ...)"),
    ("pm_interval_shots", "Maintenance every (shots)"),
    ("status", "Status"),
    ("notes", "Notes"),
]


def export_workbook(user: User) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Moulds"
    sheet.append([label for _, label in COLUMNS])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for m in search(user):
        p = payload(m)
        p["parts"] = "; ".join(f"{x['item']} x {x['cavities']}" for x in p["parts"])
        p["machines"] = "; ".join(p["machines"])
        p["owner"] = m.get_owner_display()
        p["status"] = m.get_status_display()
        sheet.append([p.get(key) if p.get(key) is not None else "" for key, _ in COLUMNS])
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 18
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def import_workbook(user: User, content: bytes, *, dry_run: bool) -> dict:
    if not can_edit(user):
        raise ImportRefused(["Only the Production Planner or the Admin keeps the moulds."])
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
    if "code" not in index:
        raise ImportRefused(["The first row must hold the column names of the export."])
    errors, created, changed = [], 0, 0
    with transaction.atomic():
        for n, row in enumerate(rows[1:], start=2):
            values = {k: row[i] for k, i in index.items() if i < len(row)}
            code = _text(values.get("code")).upper()
            if not code and not any(_text(v) for v in values.values()):
                continue
            values = {
                k: v
                for k, v in values.items()
                if k == "code" or _text(v) or k in ("customer", "asset")
            }
            try:
                with transaction.atomic():
                    current = Mould.objects.filter(code=code).first()
                    if current is None:
                        create(user, values)
                        created += 1
                    else:
                        update(user, current, values)
                        changed += 1
            except MouldError as error:
                errors.append(f"Row {n} ({code or 'no code'}): {error}")
        if errors:
            transaction.set_rollback(True)
            raise ImportRefused(errors[:50])
        if dry_run:
            transaction.set_rollback(True)
    return {"created": created, "changed": changed, "saved": not dry_run}
