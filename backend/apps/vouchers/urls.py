from django.urls import path

from . import views as v

urlpatterns = [
    path("voucher-types/", v.TypeListView.as_view(), name="voucher-type-list"),
    path("voucher-types/<int:pk>/", v.TypeDetailView.as_view(), name="voucher-type-detail"),
]

urlpatterns += [
    path("vouchers/", v.VoucherListView.as_view(), name="voucher-list"),
    path(
        "vouchers/transfer-accounts/",
        v.TransferAccountsView.as_view(),
        name="voucher-transfer-accounts",
    ),
    path(
        "vouchers/payee-balance/<int:payee_pk>/",
        v.PayeeBalanceView.as_view(),
        name="voucher-payee-balance",
    ),
    path("vouchers/<int:pk>/", v.VoucherDetailView.as_view(), name="voucher-detail"),
    path("vouchers/<int:pk>/submit/", v.SubmitView.as_view(), name="voucher-submit"),
    path(
        "vouchers/<int:pk>/attachments/",
        v.AttachmentListView.as_view(),
        name="voucher-attachments",
    ),
    path(
        "vouchers/<int:pk>/attachments/<int:attachment_pk>/",
        v.AttachmentDetailView.as_view(),
        name="voucher-attachment",
    ),
]
