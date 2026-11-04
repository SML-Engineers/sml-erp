from django.urls import path

from . import (
    advance_views,
    credit_note_views,
    delivery_views,
    invoice_views,
    order_views,
    proforma_views,
    public_views,
    receipt_views,
    receivable_views,
    report_views,
    views,
)

urlpatterns = [
    # The customer's page of an emailed invoice, by its secret link (P2-27): no sign-in.
    path(
        "public/invoices/<str:token>/",
        public_views.PublicInvoiceView.as_view(),
        name="public-invoice",
    ),
    path(
        "public/invoices/<str:token>/pdf/",
        public_views.PublicInvoicePdfView.as_view(),
        name="public-invoice-pdf",
    ),
    path("quotations/", views.QuotationListView.as_view(), name="quotation-list"),
    path("quotations/<int:pk>/", views.QuotationDetailView.as_view(), name="quotation-detail"),
    path(
        "quotations/<int:pk>/images/",
        views.QuotationImageListView.as_view(),
        name="quotation-images",
    ),
    path(
        "quotations/<int:pk>/images/<int:image_pk>/",
        views.QuotationImageDetailView.as_view(),
        name="quotation-image",
    ),
    path(
        "quotations/<int:pk>/files/", views.QuotationFileListView.as_view(), name="quotation-files"
    ),
    path(
        "quotations/<int:pk>/files/<int:file_pk>/",
        views.QuotationFileDetailView.as_view(),
        name="quotation-file-detail",
    ),
    path(
        "quotations/<int:pk>/costing/",
        views.QuotationCostingView.as_view(),
        name="quotation-costing",
    ),
    path(
        "quotations/<int:pk>/costing/<int:line_no>/",
        views.QuotationLineCostingView.as_view(),
        name="quotation-line-costing",
    ),
    path(
        "quotations/<int:pk>/submit/",
        views.QuotationSubmitView.as_view(),
        name="quotation-submit",
    ),
    path(
        "quotations/<int:pk>/approve/",
        views.QuotationApproveView.as_view(),
        name="quotation-approve",
    ),
    path(
        "quotations/<int:pk>/return/",
        views.QuotationReturnView.as_view(),
        name="quotation-return",
    ),
    path(
        "quotations/<int:pk>/sent/",
        views.QuotationSentView.as_view(),
        name="quotation-sent",
    ),
    path(
        "quotations/<int:pk>/outcome/",
        views.QuotationOutcomeView.as_view(),
        name="quotation-outcome",
    ),
    path(
        "quotations/<int:pk>/revise/",
        views.QuotationReviseView.as_view(),
        name="quotation-revise",
    ),
    path("receivables/aging/", receivable_views.AgingView.as_view(), name="receivables-aging"),
    path(
        "receivables/statements/<int:pk>/",
        receivable_views.StatementView.as_view(),
        name="customer-statement",
    ),
    path(
        "receivables/statements/<int:pk>/email/",
        receivable_views.StatementEmailView.as_view(),
        name="customer-statement-email",
    ),
    path(
        "receivables/statements/<int:pk>/reminders/",
        receivable_views.RemindersView.as_view(),
        name="customer-reminders",
    ),
    path("credit-holds/", receivable_views.CreditHoldListView.as_view(), name="credit-holds"),
    path(
        "credit-holds/<int:pk>/allow/",
        receivable_views.CreditHoldAllowView.as_view(),
        name="credit-hold-allow",
    ),
    path("receipts/", receipt_views.ReceiptListView.as_view(), name="receipt-list"),
    path("receipts/options/", receipt_views.ReceiptOptionsView.as_view(), name="receipt-options"),
    path("receipts/<int:pk>/", receipt_views.ReceiptDetailView.as_view(), name="receipt-detail"),
    path(
        "receipts/<int:pk>/approve/",
        receipt_views.ReceiptApproveView.as_view(),
        name="receipt-approve",
    ),
    path(
        "receipts/<int:pk>/reject/",
        receipt_views.ReceiptRejectView.as_view(),
        name="receipt-reject",
    ),
    path("receipts/<int:pk>/pdf/", receipt_views.ReceiptPdfView.as_view(), name="receipt-pdf"),
    path(
        "advances/<int:pk>/set-off/",
        receipt_views.AdvanceSetOffView.as_view(),
        name="advance-set-off",
    ),
    path("advances/", advance_views.AdvanceListView.as_view(), name="advance-list"),
    path("advances/options/", advance_views.AdvanceOptionsView.as_view(), name="advance-options"),
    path("advances/<int:pk>/", advance_views.AdvanceDetailView.as_view(), name="advance-detail"),
    path(
        "advances/<int:pk>/approve/",
        advance_views.AdvanceApproveView.as_view(),
        name="advance-approve",
    ),
    path(
        "advances/<int:pk>/reject/",
        advance_views.AdvanceRejectView.as_view(),
        name="advance-reject",
    ),
    path(
        "advances/<int:pk>/receipt/",
        advance_views.AdvanceReceiptView.as_view(),
        name="advance-receipt",
    ),
    path("quotations/<int:pk>/pdf/", views.QuotationPdfView.as_view(), name="quotation-pdf"),
    path("quotations/<int:pk>/email/", views.QuotationEmailView.as_view(), name="quotation-email"),
    path("proformas/", proforma_views.ProformaListView.as_view(), name="proforma-list"),
    path(
        "proformas/<int:pk>/", proforma_views.ProformaDetailView.as_view(), name="proforma-detail"
    ),
    path(
        "proformas/<int:pk>/issue/",
        proforma_views.ProformaIssueView.as_view(),
        name="proforma-issue",
    ),
    path(
        "proformas/<int:pk>/cancel/",
        proforma_views.ProformaCancelView.as_view(),
        name="proforma-cancel",
    ),
    path("proformas/<int:pk>/pdf/", proforma_views.ProformaPdfView.as_view(), name="proforma-pdf"),
    path(
        "proformas/<int:pk>/email/",
        proforma_views.ProformaEmailView.as_view(),
        name="proforma-email",
    ),
    path("credit-notes/", credit_note_views.CreditListView.as_view(), name="credit-list"),
    path(
        "credit-notes/invoice/<int:pk>/",
        credit_note_views.InvoiceLinesView.as_view(),
        name="credit-invoice",
    ),
    path(
        "credit-notes/<int:pk>/",
        credit_note_views.CreditDetailView.as_view(),
        name="credit-detail",
    ),
    path(
        "credit-notes/<int:pk>/submit/",
        credit_note_views.CreditSubmitView.as_view(),
        name="credit-submit",
    ),
    path(
        "credit-notes/<int:pk>/approve/",
        credit_note_views.CreditApproveView.as_view(),
        name="credit-approve",
    ),
    path(
        "credit-notes/<int:pk>/return/",
        credit_note_views.CreditReturnView.as_view(),
        name="credit-return",
    ),
    path(
        "credit-notes/<int:pk>/reject/",
        credit_note_views.CreditRejectView.as_view(),
        name="credit-reject",
    ),
    path(
        "credit-notes/<int:pk>/pdf/",
        credit_note_views.CreditPdfView.as_view(),
        name="credit-pdf",
    ),
    path("tax-invoices/", invoice_views.InvoiceListView.as_view(), name="invoice-list"),
    path(
        "tax-invoices/orders/",
        invoice_views.OrdersToInvoiceView.as_view(),
        name="invoice-orders",
    ),
    path(
        "tax-invoices/<int:pk>/",
        invoice_views.InvoiceDetailView.as_view(),
        name="invoice-detail",
    ),
    path(
        "tax-invoices/<int:pk>/issue/",
        invoice_views.InvoiceIssueView.as_view(),
        name="invoice-issue",
    ),
    path("tax-invoices/<int:pk>/pdf/", invoice_views.InvoicePdfView.as_view(), name="invoice-pdf"),
    path(
        "tax-invoices/<int:pk>/card-links/",
        invoice_views.CardLinkView.as_view(),
        name="invoice-card-links",
    ),
    path(
        "tax-invoices/<int:pk>/email/",
        invoice_views.InvoiceEmailView.as_view(),
        name="invoice-email",
    ),
    path("sales-accounts/", invoice_views.SalesAccountsView.as_view(), name="sales-accounts"),
    path("delivery-notes/", delivery_views.DeliveryListView.as_view(), name="delivery-list"),
    path(
        "delivery-notes/orders/",
        delivery_views.OrdersToDeliverView.as_view(),
        name="delivery-orders",
    ),
    path(
        "delivery-notes/<int:pk>/",
        delivery_views.DeliveryDetailView.as_view(),
        name="delivery-detail",
    ),
    path(
        "delivery-notes/<int:pk>/issue/",
        delivery_views.DeliveryIssueView.as_view(),
        name="delivery-issue",
    ),
    path(
        "delivery-notes/<int:pk>/received/",
        delivery_views.DeliveryReceivedView.as_view(),
        name="delivery-received",
    ),
    path(
        "delivery-notes/<int:pk>/cancel/",
        delivery_views.DeliveryCancelView.as_view(),
        name="delivery-cancel",
    ),
    path(
        "delivery-notes/<int:pk>/pdf/",
        delivery_views.DeliveryPdfView.as_view(),
        name="delivery-pdf",
    ),
    path(
        "delivery-notes/<int:pk>/signed-copy/",
        delivery_views.SignedCopyView.as_view(),
        name="delivery-signed-copy",
    ),
    path("sales-orders/", order_views.SalesOrderListView.as_view(), name="sales-order-list"),
    path(
        "sales-orders/<int:pk>/",
        order_views.SalesOrderDetailView.as_view(),
        name="sales-order-detail",
    ),
    path(
        "sales-orders/<int:pk>/confirm/",
        order_views.SalesOrderConfirmView.as_view(),
        name="sales-order-confirm",
    ),
    path(
        "sales-orders/<int:pk>/approve/",
        order_views.SalesOrderApproveView.as_view(),
        name="sales-order-approve",
    ),
    path(
        "sales-orders/<int:pk>/return/",
        order_views.SalesOrderReturnView.as_view(),
        name="sales-order-return",
    ),
    path(
        "sales-orders/<int:pk>/complete/",
        order_views.SalesOrderCompleteView.as_view(),
        name="sales-order-complete",
    ),
    path(
        "sales-orders/<int:pk>/cancel/",
        order_views.SalesOrderCancelView.as_view(),
        name="sales-order-cancel",
    ),
    path("sales/reports/register/", report_views.RegisterView.as_view(), name="sales-register"),
    path("sales/reports/win-loss/", report_views.WinLossView.as_view(), name="sales-win-loss"),
    path("sales/reports/attention/", report_views.AttentionView.as_view(), name="sales-attention"),
    path(
        "sales/reports/open-orders/",
        report_views.OpenOrdersView.as_view(),
        name="sales-open-orders",
    ),
    path("sales/reports/advances/", report_views.AdvancesOpenView.as_view(), name="sales-advances"),
    path("sales/dashboard/", report_views.DashboardView.as_view(), name="sales-dashboard"),
]
