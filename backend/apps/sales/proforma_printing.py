"""The printed proforma invoice (backlog P15-08, spec 5.2), in the layout of SML's own
proforma (sample PI191120-02, received 31 Oct 2026) and the quotation: titled PROFORMA
INVOICE (correctly spelt), with the discount, SSCL, subtotal, VAT and total; the advance
and balance to pay; notes; payment terms and delivery term; for export, the Incoterm, ports
of loading and destination and the exchange rate; the bank details for paying the advance.
No SVAT line. A draft is marked DRAFT – NOT ISSUED and a cancelled one CANCELLED.

The packing list (owner, 31 Oct 2026) follows on its own page: per line the cartons,
quantity per carton, net and gross weight and the carton size, with totals and the volume.
"""

from reportlab.lib.units import mm
from reportlab.platypus import Spacer

from apps.vouchers.printing import Table

from . import proformas
from .document_pdf import (
    GRID,
    SHADE,
    WIDTH,
    Document,
    Line,
    build,
    heading,
    money,
    qty,
    taxes_by_component,
)
from .models import ProformaInvoice

MARKS = {
    ProformaInvoice.Status.DRAFT: "DRAFT – NOT ISSUED",
    ProformaInvoice.Status.CANCELLED: "CANCELLED",
}


def _weight(value) -> str:
    return "" if value is None else qty(value)


def packing_page(proforma: ProformaInvoice, doc: Document):
    def page(s):
        p = s.p
        rows = [
            [
                p("#", s.head),
                p("Description", s.head),
                p("Qty", s.head),
                p("Cartons", s.head),
                p("Qty per carton", s.head),
                p("Net kg", s.head),
                p("Gross kg", s.head),
                p("Carton size (cm)", s.head),
                p("Volume (CBM)", s.head),
            ]
        ]
        for line in proforma.lines.all():
            sizes = (line.carton_length_cm, line.carton_width_cm, line.carton_height_cm)
            size = "" if None in sizes else " × ".join(f"{v.normalize():f}" for v in sizes)
            volume = proformas.volume_m3(line)
            rows.append(
                [
                    p(line.line_no),
                    p(line.description),
                    p(qty(line.quantity), s.right),
                    p("" if line.cartons is None else f"{line.cartons:,}", s.right),
                    p(_weight(line.qty_per_carton), s.right),
                    p(_weight(line.net_weight_kg), s.right),
                    p(_weight(line.gross_weight_kg), s.right),
                    p(size, s.right),
                    p(_weight(volume), s.right),
                ]
            )
        totals = proformas.packing_totals(proforma)
        rows.append(
            [
                "",
                p("Total", s.bold),
                "",
                p("" if totals["cartons"] is None else f"{totals['cartons']:,}", s.right_bold),
                "",
                p(_weight(totals["net_weight_kg"]), s.right_bold),
                p(_weight(totals["gross_weight_kg"]), s.right_bold),
                "",
                p(_weight(totals["volume_m3"]), s.right_bold),
            ]
        )
        end = len(rows) - 1
        widths = [0.04, 0.25, 0.09, 0.1, 0.1, 0.09, 0.09, 0.13, 0.11]
        return heading(doc, s, title="PACKING LIST") + [
            Table(
                rows,
                colWidths=[WIDTH * w for w in widths],
                repeatRows=1,
                style=[
                    ("BOX", (0, 0), (-1, -1), 0.8, GRID),
                    ("INNERGRID", (0, 0), (-1, -1), 0.3, GRID),
                    ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                    ("BACKGROUND", (0, end), (-1, end), SHADE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ],
            ),
            Spacer(1, 4 * mm),
            p(f"Packing list for proforma invoice {proforma.number}.", s.small),
        ]

    return page


def document(proforma: ProformaInvoice) -> Document:
    currency = proforma.currency.code
    customer = proforma.customer
    lines = []
    for line in proforma.lines.select_related("tax_code"):
        text = line.description
        if line.drawing_no:
            text += f"\nDrawing {line.drawing_no}"
        if line.is_tooling:
            text += "\n(Tooling – charged once)"
        shown = qty(line.quantity) + ("" if line.unit == "pcs" else f" {line.unit}")
        lines.append(Line(text, shown, line.unit_price, line.amount))
    before, after = taxes_by_component(
        proforma.lines.select_related("tax_code"), proforma.issue_date
    )
    after_totals = []
    if proforma.advance_pct:
        advance = proforma.advance_amount
        pct = f"{proforma.advance_pct.normalize():f}%"
        after_totals += [
            f"Advance Payment ({pct}) - {currency} {money(advance)}",
            f"Balance Payment - {currency} {money(proforma.total_amount - advance)}",
        ]
    terms = [
        ("Payment Terms", proforma.payment_terms),
        ("Delivery Term", proforma.incoterm),
    ]
    if proforma.delivery_lead_time:
        terms.append(("Delivery Time", proforma.delivery_lead_time))
    if proforma.port_of_loading:
        terms.append(("Port of Loading", proforma.port_of_loading))
    if proforma.port_of_destination:
        terms.append(("Port of Destination", proforma.port_of_destination))
    boxes = []
    bank = proforma.bank_account
    if bank is not None:
        rows = [f"Account name: {bank.name}"]
        if bank.bank_name:
            rows.append(f"Bank: {bank.bank_name}" + (f", {bank.branch}" if bank.branch else ""))
        if bank.account_number:
            rows.append(f"Account no.: {bank.account_number} ({bank.currency.code})")
        boxes.append(("Bank details for payment", rows))
    refs = [f"Quotation: {proforma.quotation.label}"]
    if proforma.customer_po:
        refs.insert(0, f"Your PO: {proforma.customer_po}")
    doc = Document(
        title="PROFORMA INVOICE",
        reference=proforma.number,
        when=proforma.issue_date,
        customer_name=customer.name,
        customer_address=customer.billing_address,
        customer_vat=customer.vat_no,
        attention=proforma.contact.name if proforma.contact else "",
        other_refs=refs,
        currency=currency,
        lines=lines,
        discount_pct=proforma.discount_pct,
        discount_total=proforma.discount_total,
        net_total=proforma.subtotal,
        taxes_before=before,
        taxes_after=after,
        total=proforma.total_amount,
        exchange_rate=proforma.exchange_rate,
        rate_date=proforma.rate_date,
        after_totals=after_totals,
        terms=terms,
        boxes=boxes,
        notes=proforma.notes,
        mark=MARKS.get(proforma.status, ""),
        pdf_title=f"Proforma invoice {proforma.number}",
    )
    if proformas.has_packing(proforma):
        doc.extra_pages.append(packing_page(proforma, doc))
    return doc


def render(proforma: ProformaInvoice, *, compress: bool = True) -> bytes:
    """The PDF, with the packing list as its own page when packing is entered."""
    return build(document(proforma), compress=compress)
