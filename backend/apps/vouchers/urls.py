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
    path("vouchers/waiting/", v.WaitingView.as_view(), name="voucher-waiting"),
    path("vouchers/decisions/", v.BulkDecisionView.as_view(), name="voucher-decisions"),
    path("vouchers/<int:pk>/", v.VoucherDetailView.as_view(), name="voucher-detail"),
    path("vouchers/<int:pk>/coding/", v.CodingView.as_view(), name="voucher-coding"),
    path(
        "vouchers/<int:pk>/approve/",
        v.DecisionView.as_view(),
        {"decision": "approve"},
        name="voucher-approve",
    ),
    path(
        "vouchers/<int:pk>/return/",
        v.DecisionView.as_view(),
        {"decision": "return"},
        name="voucher-return",
    ),
    path(
        "vouchers/<int:pk>/reject/",
        v.DecisionView.as_view(),
        {"decision": "reject"},
        name="voucher-reject",
    ),
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
