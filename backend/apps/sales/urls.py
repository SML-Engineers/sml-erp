from django.urls import path

from . import views

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
]
