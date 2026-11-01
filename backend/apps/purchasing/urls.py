from django.urls import path

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
]
