"""The customer's page of an emailed tax invoice (P2-27): reached by its secret link, with no
sign-in. It shows the invoice, its PDF and the bank details for a transfer, and records that
the customer looked. Nothing else of the system is reachable from it."""

from django.http import Http404, HttpResponse
from django.utils.html import format_html, format_html_join
from django.views import View

from apps.core.models import Company

from . import invoice_printing, receipts, tracking

PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Invoice {number}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 0; background: #f5f6f8; color: #1d2433; }}
main {{ max-width: 640px; margin: 0 auto; padding: 24px 16px; }}
section {{ background: #fff; border-radius: 10px; padding: 16px 20px; margin-bottom: 16px; }}
dl {{ display: grid; grid-template-columns: max-content 1fr; gap: 6px 16px; margin: 0; }}
dt {{ color: #5b6475; }} dd {{ margin: 0; font-weight: 600; }}
a.button {{ display: inline-block; background: #1f6feb; color: #fff; padding: 10px 16px;
  border-radius: 8px; text-decoration: none; }}
.paid {{ color: #1a7f37; }} .due {{ color: #b42318; }}
</style></head>
<body><main>
<h1>{company}</h1>
<section><h2>Tax invoice {number}</h2>
<dl>
<dt>Date</dt><dd>{date}</dd>
<dt>Due date</dt><dd>{due}</dd>
<dt>Amount</dt><dd>{currency} {amount}</dd>
<dt>Still to pay</dt><dd class="{state_class}">{currency} {left}</dd>
</dl>
<p><a class="button" href="pdf/">Download the invoice (PDF)</a></p>
</section>
<section><h2>Pay by bank transfer</h2>
<p>Please use <strong>{number}</strong> as the payment reference.</p>
{banks}
<p>To pay by card, reply to the invoice email and we will send you a secure payment link.</p>
</section>
</main></body></html>"""


def _invoice(token):
    invoice = tracking.by_token(token)
    if invoice is None:
        raise Http404
    return invoice


class PublicInvoiceView(View):
    def get(self, request, token):
        invoice = _invoice(token)
        tracking.record_view(invoice, "page")
        company = Company.objects.filter(pk=1).first()
        left = receipts.settlement([invoice])[invoice.pk]["open"]
        banks = tracking.bank_accounts(invoice)
        bank_html = (
            format_html_join(
                "",
                "<dl><dt>Bank</dt><dd>{} {}</dd><dt>Account name</dt><dd>{}</dd>"
                "<dt>Account number</dt><dd>{}</dd></dl><br>",
                (
                    (a.bank_name, a.branch, company.name if company else a.name, a.account_number)
                    for a in banks
                ),
            )
            if banks
            else format_html("<p>{}</p>", "Please ask us for our bank details.")
        )
        html = format_html(
            PAGE,
            company=company.name if company else "",
            number=invoice.number,
            date=f"{invoice.invoice_date:%d %b %Y}",
            due=f"{invoice.due_date:%d %b %Y}",
            currency=invoice.currency.code,
            amount=f"{invoice.total_amount:,.2f}",
            left=f"{max(left, 0):,.2f}",
            state_class="paid" if left <= 0 else "due",
            banks=bank_html,
        )
        response = HttpResponse(html)
        response["Cache-Control"] = "no-store"
        response["X-Robots-Tag"] = "noindex"
        return response


class PublicInvoicePdfView(View):
    def get(self, request, token):
        invoice = _invoice(token)
        tracking.record_view(invoice, "pdf")
        response = HttpResponse(invoice_printing.render(invoice), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="Tax-invoice-{invoice.number}.pdf"'
        response["Cache-Control"] = "no-store"
        return response
