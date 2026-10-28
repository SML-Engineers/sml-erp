from django.urls import path

from . import views as v

urlpatterns = [
    path("chart-of-accounts/", v.AccountListView.as_view(), name="account-list"),
    path("chart-of-accounts/types/", v.AccountTypesView.as_view(), name="account-types"),
    path(
        "chart-of-accounts/detail-types/",
        v.DetailTypeListView.as_view(),
        name="detail-type-list",
    ),
    path(
        "chart-of-accounts/detail-types/<int:pk>/",
        v.DetailTypeDetailView.as_view(),
        name="detail-type-detail",
    ),
    path("chart-of-accounts/export/", v.ChartExportView.as_view(), name="chart-export"),
    path("chart-of-accounts/import/", v.ChartImportView.as_view(), name="chart-import"),
    path("chart-of-accounts/<int:pk>/", v.AccountDetailView.as_view(), name="account-detail"),
    path("chart-of-accounts/<int:pk>/merge/", v.AccountMergeView.as_view(), name="account-merge"),
]
