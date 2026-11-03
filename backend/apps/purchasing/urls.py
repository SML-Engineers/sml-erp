from django.urls import path

from . import invoice_views as iv
from . import payable_views as pv
from . import report_views as pr
from . import request_views as qv
from . import return_views as rv
from . import views as v

urlpatterns = [
    path("payables/aging/", pv.AgingView.as_view(), name="payables-aging"),
    path("supplier-statements/", pv.StatementListView.as_view(), name="supplier-statements"),
    path(
        "supplier-statements/import/",
        pv.StatementImportView.as_view(),
        name="supplier-statement-import",
    ),
    path(
        "supplier-statements/<int:pk>/",
        pv.StatementDetailView.as_view(),
        name="supplier-statement",
    ),
    path(
        "supplier-statements/<int:pk>/check/",
        pv.StatementCheckView.as_view(),
        name="supplier-statement-check",
    ),
    path("reorder-levels/", qv.LevelListView.as_view(), name="reorder-levels"),
    path("reorder-levels/<int:pk>/", qv.LevelDetailView.as_view(), name="reorder-level"),
    path(
        "reorder-levels/<int:pk>/request/",
        qv.LevelRequestView.as_view(),
        name="reorder-level-request",
    ),
    path("purchase-requests/", qv.RequestListView.as_view(), name="pr-list"),
    path("purchase-requests/<int:pk>/", qv.RequestDetailView.as_view(), name="pr-detail"),
    path(
        "purchase-requests/<int:pk>/submit/",
        qv.RequestActionView.as_view(action="submit"),
        name="pr-submit",
    ),
    path(
        "purchase-requests/<int:pk>/approve/",
        qv.RequestActionView.as_view(action="approve"),
        name="pr-approve",
    ),
    path(
        "purchase-requests/<int:pk>/return/",
        qv.RequestActionView.as_view(action="return"),
        name="pr-return",
    ),
    path(
        "purchase-requests/<int:pk>/reject/",
        qv.RequestActionView.as_view(action="reject"),
        name="pr-reject",
    ),
    path(
        "purchase-requests/<int:pk>/cancel/",
        qv.RequestActionView.as_view(action="cancel"),
        name="pr-cancel",
    ),
    path(
        "purchase-requests/<int:pk>/order/",
        qv.RequestActionView.as_view(action="order"),
        name="pr-order",
    ),
    path("purchase-orders/", v.OrderListView.as_view(), name="po-list"),
    path("purchase-orders/<int:pk>/", v.OrderDetailView.as_view(), name="po-detail"),
    path("purchase-orders/<int:pk>/submit/", v.SubmitView.as_view(), name="po-submit"),
    path("purchase-orders/<int:pk>/approve/", v.ApproveView.as_view(), name="po-approve"),
    path("purchase-orders/<int:pk>/return/", v.ReturnView.as_view(), name="po-return"),
    path("purchase-orders/<int:pk>/revise/", v.ReviseView.as_view(), name="po-revise"),
    path("purchase-orders/<int:pk>/cancel/", v.CancelView.as_view(), name="po-cancel"),
    path("purchase-orders/<int:pk>/close/", v.CloseView.as_view(), name="po-close"),
    path("purchase-orders/<int:pk>/pdf/", v.PdfView.as_view(), name="po-pdf"),
    path("purchase-orders/<int:pk>/email/", v.EmailView.as_view(), name="po-email"),
    path("supplier-invoices/", iv.InvoiceListView.as_view(), name="si-list"),
    path("supplier-invoices/open-lines/", iv.OpenLinesView.as_view(), name="si-open-lines"),
    path("supplier-invoices/payable/", iv.PayableView.as_view(), name="si-payable"),
    path(
        "supplier-invoices/advance-orders/",
        iv.AdvanceOrdersView.as_view(),
        name="si-advance-orders",
    ),
    path("supplier-invoices/<int:pk>/", iv.InvoiceDetailView.as_view(), name="si-detail"),
    path("supplier-invoices/<int:pk>/match/", iv.MatchView.as_view(), name="si-match"),
    path("supplier-invoices/<int:pk>/reopen/", iv.ReopenView.as_view(), name="si-reopen"),
    path("supplier-invoices/<int:pk>/exception/", iv.ExceptionView.as_view(), name="si-exception"),
    path("supplier-invoices/<int:pk>/approve/", iv.ApproveView.as_view(), name="si-approve"),
    path("supplier-invoices/<int:pk>/return/", iv.ReturnView.as_view(), name="si-return"),
    path("supplier-invoices/<int:pk>/cancel/", iv.CancelView.as_view(), name="si-cancel"),
    path("supplier-invoices/<int:pk>/set-off/", iv.SetOffView.as_view(), name="si-set-off"),
    path(
        "supplier-invoices/<int:pk>/attachments/",
        iv.AttachmentListView.as_view(),
        name="si-attachments",
    ),
    path(
        "supplier-invoices/<int:pk>/attachments/<int:attachment_pk>/",
        iv.AttachmentDetailView.as_view(),
        name="si-attachment",
    ),
    path("supplier-returns/", rv.ReturnListView.as_view(), name="rtn-list"),
    path("supplier-returns/lots/", rv.LotsView.as_view(), name="rtn-lots"),
    path("supplier-returns/<int:pk>/", rv.ReturnDetailView.as_view(), name="rtn-detail"),
    path("supplier-returns/<int:pk>/confirm/", rv.ConfirmView.as_view(), name="rtn-confirm"),
    path("supplier-returns/<int:pk>/approve/", rv.ApproveView.as_view(), name="rtn-approve"),
    path("supplier-returns/<int:pk>/return/", rv.SendBackView.as_view(), name="rtn-return"),
    path("supplier-returns/<int:pk>/pdf/", rv.PdfView.as_view(), name="rtn-pdf"),
    path("purchasing-reports/open-orders/", pr.OpenOrdersView.as_view(), name="pr-open"),
    path("purchasing-reports/grni/", pr.GrniView.as_view(), name="pr-grni"),
    path("purchasing-reports/held-invoices/", pr.HeldInvoicesView.as_view(), name="pr-held"),
    path("purchasing-reports/exceptions/", pr.ExceptionsView.as_view(), name="pr-exceptions"),
    path("purchasing-reports/suppliers/", pr.SuppliersView.as_view(), name="pr-suppliers"),
    path("purchasing-reports/trail/", pr.TrailView.as_view(), name="pr-trail"),
    path("purchasing-reports/dashboard/", pr.DashboardView.as_view(), name="pr-dashboard"),
]
