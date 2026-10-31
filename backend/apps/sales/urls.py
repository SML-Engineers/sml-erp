from django.urls import path

from . import advance_views, views

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
    path("advances/", advance_views.AdvanceListView.as_view(), name="advance-list"),
    path("advances/options/", advance_views.AdvanceOptionsView.as_view(), name="advance-options"),
    path("advances/<int:pk>/", advance_views.AdvanceDetailView.as_view(), name="advance-detail"),
    path(
        "advances/<int:pk>/approve/",
        advance_views.AdvanceApproveView.as_view(),
        name="advance-approve",
    ),
    path(
        "advances/<int:pk>/reject/",
        advance_views.AdvanceRejectView.as_view(),
        name="advance-reject",
    ),
    path(
        "advances/<int:pk>/receipt/",
        advance_views.AdvanceReceiptView.as_view(),
        name="advance-receipt",
    ),
    path("quotations/<int:pk>/pdf/", views.QuotationPdfView.as_view(), name="quotation-pdf"),
    path("quotations/<int:pk>/email/", views.QuotationEmailView.as_view(), name="quotation-email"),
]
