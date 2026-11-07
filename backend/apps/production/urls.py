from django.urls import path

from . import views as v

urlpatterns = [
    path("moulds/", v.MouldListView.as_view(), name="moulds"),
    path("moulds/export/", v.MouldExportView.as_view(), name="moulds-export"),
    path("moulds/import/", v.MouldImportView.as_view(), name="moulds-import"),
    path("moulds/labels/", v.MouldLabelsView.as_view(), name="moulds-labels"),
    path("moulds/<int:pk>/", v.MouldDetailView.as_view(), name="mould"),
    path("moulds/<int:pk>/fit/", v.MouldFitView.as_view(), name="mould-fit"),
    path("routings/", v.RoutingListView.as_view(), name="routings"),
    path("routings/export/", v.RoutingExportView.as_view(), name="routings-export"),
    path("routings/import/", v.RoutingImportView.as_view(), name="routings-import"),
    path("routings/<int:pk>/", v.RoutingDetailView.as_view(), name="routing"),
    path("routings/<int:pk>/<str:action>/", v.RoutingActionView.as_view(), name="routing-action"),
    path("boms/", v.BomListView.as_view(), name="boms"),
    path("boms/export/", v.BomExportView.as_view(), name="boms-export"),
    path("boms/import/", v.BomImportView.as_view(), name="boms-import"),
    path("boms/compare/", v.BomCompareView.as_view(), name="boms-compare"),
    path("boms/where-used/", v.BomWhereUsedView.as_view(), name="boms-where-used"),
    path("boms/machining/", v.BomMachiningCalcView.as_view(), name="boms-machining"),
    path("boms/<int:pk>/", v.BomDetailView.as_view(), name="bom"),
    path("boms/<int:pk>/<str:action>/", v.BomActionView.as_view(), name="bom-action"),
    path("production-setup/", v.ProductionSetupView.as_view(), name="production-setup"),
    path("production-reasons/", v.ReasonsView.as_view(), name="production-reasons"),
    path("production-reasons/<int:pk>/", v.ReasonView.as_view(), name="production-reason"),
]
