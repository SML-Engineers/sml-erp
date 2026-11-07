"""QR labels for moulds (backlog P3-01): one 100 x 50 mm sticker per mould, for the same
thermal label printer as the goods-receipt labels. The QR code holds the mould's code, which
the supervisors scan on the shift report (P3-08)."""

from io import BytesIO

from reportlab.graphics import renderPDF
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

from apps.core.models import Company
from apps.inventory.labels import HEIGHT, WIDTH, _fit, _qr


def render(moulds) -> bytes:
    company = Company.objects.filter(pk=1).first()
    name = (company.name if company else "").upper()
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(WIDTH, HEIGHT), pageCompression=1)
    pdf.setTitle("Mould labels")
    for mould in moulds:
        renderPDF.draw(_qr(mould.code), pdf, 3 * mm, 5 * mm)
        x, y = 46 * mm, HEIGHT - 6 * mm
        pdf.setFont("Helvetica", 6.5)
        pdf.drawString(x, y, _fit(name, 40))
        y -= 6 * mm
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(x, y, mould.code)
        y -= 5 * mm
        pdf.setFont("Helvetica", 7.5)
        pdf.drawString(x, y, _fit(mould.name, 32))
        y -= 4.5 * mm
        for part in mould.parts.select_related("item")[:3]:
            pdf.drawString(x, y, _fit(f"{part.item.code} x {part.cavities}", 32))
            y -= 3.8 * mm
        if mould.owner == mould.Owner.CUSTOMER and mould.customer_id:
            pdf.drawString(x, y, _fit(f"Owner: {mould.customer.name}", 32))
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
