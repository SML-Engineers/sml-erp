from django.urls import path

from . import invoice_views as iv
from . import views as v

urlpatterns = [
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
    path("supplier-invoices/<int:pk>/", iv.InvoiceDetailView.as_view(), name="si-detail"),
    path("supplier-invoices/<int:pk>/match/", iv.MatchView.as_view(), name="si-match"),
    path("supplier-invoices/<int:pk>/reopen/", iv.ReopenView.as_view(), name="si-reopen"),
    path("supplier-invoices/<int:pk>/exception/", iv.ExceptionView.as_view(), name="si-exception"),
    path("supplier-invoices/<int:pk>/approve/", iv.ApproveView.as_view(), name="si-approve"),
    path("supplier-invoices/<int:pk>/return/", iv.ReturnView.as_view(), name="si-return"),
    path("supplier-invoices/<int:pk>/cancel/", iv.CancelView.as_view(), name="si-cancel"),
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
]
