"""The printed statement of account (P2-08): letterhead, the customer's name and address, the
period, the opening balance, every posting with a running balance, the closing balance, then
what is open by age, the amount due and what of it is overdue."""

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Spacer

from apps.vouchers.printing import Table

from .document_pdf import GRID, MARGIN, SHADE, WIDTH, Document, Styles, heading, letterhead, money


def render(st) -> bytes:
    """`st` is a receivables.Statement."""
    s = Styles()
    p = s.p
    customer = st.customer
    doc = Document(
        title="STATEMENT",
        reference=customer.code,
        when=st.end,
        customer_name=customer.name,
        customer_address=customer.billing_address,
        other_refs=[f"Period: {st.start:%d-%b-%Y} to {st.end:%d-%b-%Y}"],
    )
    story = letterhead(s) + heading(doc, s, "STATEMENT OF ACCOUNT")

    rows = [
        [
            p("Date", s.head),
            p("Reference", s.head),
            p("Description", s.head),
            p("Debit (LKR)", s.head),
            p("Credit (LKR)", s.head),
            p("Balance (LKR)", s.head),
        ],
        [
            p(f"{st.start:%d-%b-%Y}"),
            "",
            p("Opening balance", s.bold),
            "",
            "",
            p(money(st.opening), s.right_bold),
        ],
    ]
    for line in st.lines:
        rows.append(
            [
                p(f"{line['date']:%d-%b-%Y}"),
                p(line["reference"]),
                p(line["description"]),
                p(money(line["debit"]) if line["debit"] else "", s.right),
                p(money(line["credit"]) if line["credit"] else "", s.right),
                p(money(line["balance"]), s.right),
            ]
        )
    rows.append(
        [
            p(f"{st.end:%d-%b-%Y}"),
            "",
            p("Closing balance", s.bold),
            "",
            "",
            p(money(st.closing), s.right_bold),
        ]
    )
    widths = [0.12, 0.17, 0.32, 0.13, 0.13, 0.13]
    story.append(
        Table(
            rows,
            colWidths=[WIDTH * w for w in widths],
            repeatRows=1,
            style=[
                ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                ("BACKGROUND", (0, 0), (-1, 0), SHADE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ],
        )
    )
    story.append(Spacer(1, 6))

    labels = ["Not yet due", "1-30 days", "31-60 days", "61-90 days", "Over 90 days"]
    keys = ["current", "d30", "d60", "d90", "over90"]
    story.append(
        Table(
            [
                [p(label, s.head) for label in labels],
                [p(money(st.buckets.get(key, 0)), s.right) for key in keys],
            ],
            colWidths=[WIDTH / 5] * 5,
            style=[
                ("GRID", (0, 0), (-1, -1), 0.4, GRID),
                ("BACKGROUND", (0, 0), (-1, 0), SHADE),
            ],
        )
    )
    story.append(Spacer(1, 6))
    summary = [
        [p("Amount due", s.bold), p(f"LKR {money(st.closing)}", s.right_bold)],
        [p("Of which overdue", s.bold), p(f"LKR {money(st.overdue)}", s.right_bold)],
    ]
    if st.advances_held:
        summary.append(
            [
                p("Advances received, not yet set off"),
                p(f"LKR {money(st.advances_held)}", s.right),
            ]
        )
    story.append(
        Table(
            summary,
            colWidths=[WIDTH * 0.7, WIDTH * 0.3],
            style=[("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#999999"))],
        )
    )
    story.append(Spacer(1, 10))
    story.append(
        p(
            "Please let us know at once if any item on this statement does not agree with "
            "your records. If you have already paid, thank you, and please ignore the overdue "
            "amount.",
            s.small,
        )
    )

    buffer = BytesIO()
    SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Statement {customer.code} {st.end:%Y-%m-%d}",
    ).build(story)
    return buffer.getvalue()
