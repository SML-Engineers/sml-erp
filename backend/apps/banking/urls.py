from django.urls import path

from . import views as v

urlpatterns = [
    path("cheques/issued/", v.IssuedView.as_view(), name="cheques-issued"),
    path("cheques/issued/<int:pk>/clear/", v.ClearIssuedView.as_view(), name="cheque-clear"),
    path("cheques/received/", v.ReceivedView.as_view(), name="cheques-received"),
    path(
        "cheques/received/<int:pk>/clear/",
        v.ClearReceivedView.as_view(),
        name="received-cheque-clear",
    ),
    path(
        "cheques/received/<int:pk>/return/",
        v.ReturnReceivedView.as_view(),
        name="received-cheque-return",
    ),
    path("deposits/", v.DepositListView.as_view(), name="deposits"),
    path("deposits/<int:pk>/", v.DepositDetailView.as_view(), name="deposit"),
]
