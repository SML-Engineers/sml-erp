from django.urls import path

from . import views as v

urlpatterns = [
    path("payments/", v.PaymentListView.as_view(), name="payment-list"),
    path("payments/to-pay/", v.ToPayView.as_view(), name="payment-to-pay"),
    path("payments/accounts/", v.AccountsView.as_view(), name="payment-accounts"),
]
