from django.urls import path

from . import advance_views, delivery_views, order_views, proforma_views, report_views, views

urlpatterns = [
    path("quotations/", views.QuotationListView.as_view(), name="quotation-list"),
    path("quotations/<int:pk>/", views.QuotationDetailView.as_view(), name="quotation-detail"),
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
