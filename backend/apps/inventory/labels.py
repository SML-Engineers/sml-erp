"""QR labels for received packages (backlog P16-07, spec 6A.1): one 100 × 50 mm sticker per
bag, bundle, plate, coil or box, for a thermal label printer (owner, 1 Nov 2026).

The QR code holds the package's lot number. The sticker says QUARANTINE until QC accepts the
lot (P16-08)."""

from io import BytesIO

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from apps.core.models import Company

from .models import GoodsReceipt, ReceiptPackage

WIDTH, HEIGHT = 100 * mm, 50 * mm
QR_SIZE = 40 * mm


def _qr(text: str) -> Drawing:
    widget = QrCodeWidget(text, barLevel="M")
    left, bottom, right, top = widget.getBounds()
    drawing = Drawing(
        QR_SIZE,
        QR_SIZE,
        transform=[QR_SIZE / (right - left), 0, 0, QR_SIZE / (top - bottom), 0, 0],
    )
    drawing.add(widget)
    return drawing


def _amount(package: ReceiptPackage, unit: str) -> str:
    if package.net_weight is not None:
        text = f"Net {package.net_weight.normalize():f} kg"
        if unit not in ("kg", "g") and package.quantity is not None:
            text += f" · {package.quantity.normalize():f} {unit}"
        return text
    if package.quantity is not None:
        return f"{package.quantity.normalize():f} {unit}"
    if package.declared_weight is not None:
        return f"Declared {package.declared_weight.normalize():f} kg"
    return ""


def _fit(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render(grn: GoodsReceipt, line_no: int | None = None) -> bytes:
    rows = ReceiptPackage.objects.filter(line__receipt=grn).select_related("line__item")
    if line_no is not None:
        rows = rows.filter(line__line_no=line_no)
    company = Company.objects.filter(pk=1).first()
    name = (company.name if company else "").upper()
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(WIDTH, HEIGHT), pageCompression=1)
    pdf.setTitle(f"Labels {grn.number}")
    for package in rows.order_by("line__line_no", "package_no"):
        item = package.line.item
        renderPDF.draw(_qr(package.lot_no), pdf, 3 * mm, 5 * mm)
        x = 46 * mm
        y = HEIGHT - 6 * mm
        pdf.setFont("Helvetica", 6.5)
        pdf.drawString(x, y, _fit(name, 40))
        y -= 5 * mm
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(x, y, package.lot_no)
        y -= 5 * mm
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(x, y, _fit(item.code, 26))
        y -= 3.8 * mm
        pdf.setFont("Helvetica", 7)
        pdf.drawString(x, y, _fit(item.name, 34))
        y -= 4.5 * mm
        if package.supplier_lot:
            pdf.drawString(x, y, _fit(f"Lot/heat: {package.supplier_lot}", 34))
            y -= 3.8 * mm
        pdf.setFont("Helvetica-Bold", 8)
        pdf.drawString(x, y, _fit(_amount(package, item.unit), 32))
        y -= 3.8 * mm
        pdf.setFont("Helvetica", 6.5)
        pdf.drawString(x, y, _fit(f"{grn.number} · {grn.receipt_date:%d-%b-%Y}", 40))
        y -= 3.4 * mm
        pdf.drawString(x, y, _fit(grn.supplier.name, 40))
        pdf.setFont("Helvetica-Bold", 9)
        pdf.drawString(x, 3 * mm, "DAMAGED – QUARANTINE" if package.damaged else "QUARANTINE")
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
