"""Where a journal entry came from: the page of the document that posted it (P2-03), so any
figure in a report opens the transactions behind it, down to the document and its scans."""

from collections import defaultdict

from django.apps import apps

# source_type -> (model, page). source_id is the document's number.
PAGES = {
    "manual_journal": ("accounting.ManualJournal", "/journals/manual/{pk}"),
    "opening_stock": ("inventory.OpeningStock", "/opening-stock/{pk}"),
    "goods_receipt": ("inventory.GoodsReceipt", "/goods-receipts/{pk}"),
    "supplier_invoice": ("purchasing.SupplierInvoice", "/supplier-invoices/{pk}"),
    "advance_set_off": ("purchasing.SupplierInvoice", "/supplier-invoices/{pk}"),
    "supplier_return": ("purchasing.SupplierReturn", "/supplier-returns/{pk}"),
    "customer_advance": ("sales.CustomerAdvance", "/advances/{pk}"),
    "tax_invoice": ("sales.TaxInvoice", "/tax-invoices/{pk}"),
    "credit_note": ("sales.CreditNote", "/credit-notes/{pk}"),
}


def paths(pairs) -> dict[tuple[str, str], str]:
    """{(source_type, source_id): page} for the documents that can be found. A supplier
    payment opens its voucher, where the invoice scans are."""
    wanted: dict[str, set[str]] = defaultdict(set)
    for source_type, source_id in pairs:
        if source_id:
            wanted[source_type].add(source_id)
    found: dict[tuple[str, str], str] = {}
    for source_type, numbers in wanted.items():
        if source_type in PAGES:
            label, page = PAGES[source_type]
            model = apps.get_model(label)
            for pk, number in model.objects.filter(number__in=numbers).values_list("pk", "number"):
                found[(source_type, number)] = page.format(pk=pk)
        elif source_type == "supplier_payment":
            model = apps.get_model("payments.SupplierPayment")
            for voucher, number in model.objects.filter(number__in=numbers).values_list(
                "voucher_id", "number"
            ):
                found[(source_type, number)] = f"/vouchers/{voucher}"
    return found
