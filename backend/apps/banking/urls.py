from django.urls import path

from . import statement_views as sv
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
    path("statement-templates/", sv.TemplateListView.as_view(), name="statement-templates"),
    path(
        "statement-templates/<int:pk>/",
        sv.TemplateDetailView.as_view(),
        name="statement-template",
    ),
    path("bank-statements/", sv.StatementListView.as_view(), name="bank-statements"),
    path("bank-statements/import/", sv.ImportView.as_view(), name="bank-statement-import"),
    path("bank-statements/<int:pk>/", sv.StatementDetailView.as_view(), name="bank-statement"),
]
