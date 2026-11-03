from django.urls import path

from . import views as v

urlpatterns = [
    path("payments/", v.PaymentListView.as_view(), name="payment-list"),
    path("payments/to-pay/", v.ToPayView.as_view(), name="payment-to-pay"),
    path("payments/accounts/", v.AccountsView.as_view(), name="payment-accounts"),
    path("payments/<int:pk>/cancel/", v.CancelPaymentView.as_view(), name="payment-cancel"),
    path(
        "payment-cancellations/<int:pk>/approve/",
        v.CancellationDecisionView.as_view(decision="approve"),
        name="payment-cancellation-approve",
    ),
    path(
        "payment-cancellations/<int:pk>/reject/",
        v.CancellationDecisionView.as_view(decision="reject"),
        name="payment-cancellation-reject",
    ),
]
