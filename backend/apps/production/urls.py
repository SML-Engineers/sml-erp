from django.urls import path

from . import views as v

urlpatterns = [
    path("moulds/", v.MouldListView.as_view(), name="moulds"),
    path("moulds/export/", v.MouldExportView.as_view(), name="moulds-export"),
    path("moulds/import/", v.MouldImportView.as_view(), name="moulds-import"),
    path("moulds/labels/", v.MouldLabelsView.as_view(), name="moulds-labels"),
    path("moulds/<int:pk>/", v.MouldDetailView.as_view(), name="mould"),
    path("moulds/<int:pk>/fit/", v.MouldFitView.as_view(), name="mould-fit"),
]
