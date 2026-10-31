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
]
