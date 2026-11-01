"""Package-by-package receiving (backlog P16-07, spec 6A.2): the arithmetic.

What each package counts towards its GRN line depends on the item's unit:
- kg or g: the net weight (gross less tare);
- m or mm: the total length (pieces × length of a piece, in metres);
- anything else (pcs, box, sheet, ...): the number of pieces.

The checks, highlighted when outside the item's tolerance (owner, 1 Nov 2026: weights are
typed from the scale):
- bags and coils: net weight against the weight declared on the package;
- bars: kg per metre against the item's standard;
- plates: actual weight against the theoretical weight (length × width × thickness ×
  density).
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .models import Item, ReceiptPackage

QTY = Decimal("0.001")
WEIGHT_UNITS = ("kg", "g")
LENGTH_UNITS = ("m", "mm")
MAX_PACKAGES = 999
PT = Item.PackageType


class PackageError(Exception):
    pass


@dataclass
class PackageInput:
    supplier_lot: str = ""
    gross_weight: object = None
    tare_weight: object = None
    declared_weight: object = None
    pieces: object = None
    piece_length: object = None
    length_mm: object = None
    width_mm: object = None
    thickness_mm: object = None
    damaged: bool = False
    notes: str = ""


def number(value, what: str, places: int = 3, *, positive: bool = False) -> Decimal | None:
    """A typed number, or None when left empty."""
    if value is None or str(value).strip() == "":
        return None
    try:
        result = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        raise PackageError(f"The {what} is not a number.") from None
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise PackageError(
            f"The {what} must be more than 0." if positive else f"The {what} cannot be negative."
        )
    if result != result.quantize(Decimal(1).scaleb(-places)):
        raise PackageError(f"The {what} can have at most {places} decimal places.")
    if result >= Decimal(10) ** 9:
        raise PackageError(f"The {what} is too large.")
    return result


def needs_weight(item: Item) -> bool:
    return item.unit in WEIGHT_UNITS or item.package_type in (PT.BAG, PT.COIL)


def fill(package: ReceiptPackage, given: PackageInput, item: Item) -> None:
    """Check what was typed for one package and work out its net weight and quantity."""
    package.supplier_lot = (given.supplier_lot or "").strip()[:50]
    package.notes = (given.notes or "").strip()[:200]
    package.damaged = bool(given.damaged)
    package.gross_weight = number(given.gross_weight, "gross weight")
    tare = number(given.tare_weight, "tare")
    package.tare_weight = item.package_tare if tare is None else tare
    package.declared_weight = number(given.declared_weight, "declared weight")
    package.pieces = number(given.pieces, "number of pieces", positive=True)
    package.piece_length = number(given.piece_length, "length of a piece", positive=True)
    package.length_mm = number(given.length_mm, "length", 2, positive=True)
    package.width_mm = number(given.width_mm, "width", 2, positive=True)
    package.thickness_mm = number(given.thickness_mm, "thickness", 3, positive=True)
    package.net_weight = None
    if package.gross_weight is not None:
        if package.tare_weight >= package.gross_weight:
            raise PackageError("The gross weight must be more than the tare.")
        package.net_weight = package.gross_weight - package.tare_weight
    package.quantity = quantity(package, item)


def quantity(package: ReceiptPackage, item: Item) -> Decimal | None:
    """What the package counts towards the line, in the item's unit; None until measured."""
    if item.unit in WEIGHT_UNITS:
        if package.net_weight is None:
            return None
        return package.net_weight * (1000 if item.unit == "g" else 1)
    if item.unit in LENGTH_UNITS:
        if package.piece_length is None:
            return None
        metres = (package.pieces or Decimal(1)) * package.piece_length
        return (metres * (1000 if item.unit == "mm" else 1)).quantize(QTY, ROUND_HALF_UP)
    return package.pieces


def missing(package: ReceiptPackage, item: Item) -> str | None:
    """What still has to be entered before the GRN can be confirmed."""
    if package.quantity is None:
        if item.unit in WEIGHT_UNITS:
            return "the gross weight"
        if item.unit in LENGTH_UNITS:
            return "the length of a piece"
        return "the number of pieces"
    if needs_weight(item) and package.gross_weight is None:
        return "the gross weight"
    return None


def _pct(actual: Decimal, expected: Decimal) -> Decimal:
    return ((actual - expected) * 100 / expected).quantize(Decimal("0.01"), ROUND_HALF_UP)


def check(package: ReceiptPackage, line) -> dict:
    """The package's variance against what was expected, and whether it is outside the
    tolerance the line was entered with."""
    tolerance = line.weight_tolerance_pct
    found = {"expected": None, "actual": None, "variance_pct": None, "outside": False, "basis": ""}
    if package.net_weight is None:
        return found
    if package.declared_weight:
        found |= {
            "basis": "declared",
            "expected": package.declared_weight,
            "actual": package.net_weight,
        }
    elif line.standard_kg_per_m and package.piece_length:
        metres = (package.pieces or Decimal(1)) * package.piece_length
        found |= {
            "basis": "kg_per_m",
            "expected": line.standard_kg_per_m,
            "actual": (package.net_weight / metres).quantize(Decimal("0.0001"), ROUND_HALF_UP),
        }
    elif line.density and package.length_mm and package.width_mm and package.thickness_mm:
        theoretical = (
            package.length_mm
            * package.width_mm
            * package.thickness_mm
            * line.density
            * (package.pieces or Decimal(1))
            / Decimal(1_000_000)
        ).quantize(QTY, ROUND_HALF_UP)
        found |= {"basis": "theoretical", "expected": theoretical, "actual": package.net_weight}
    if found["expected"]:
        found["variance_pct"] = _pct(found["actual"], found["expected"])
        found["outside"] = abs(found["variance_pct"]) > tolerance
    return found
