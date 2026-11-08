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
    path("production-orders/", v.ProductionOrderListView.as_view(), name="production-orders"),
    path(
        "production-orders/sales-lines/",
        v.ProductionOrderSalesLinesView.as_view(),
        name="production-orders-sales-lines",
    ),
    path(
        "production-orders/where-used/",
        v.ProductionOrderWhereUsedView.as_view(),
        name="production-orders-where-used",
    ),
    path(
        "production-orders/<int:pk>/",
        v.ProductionOrderDetailView.as_view(),
        name="production-order",
    ),
    path(
        "production-orders/<int:pk>/<str:action>/",
        v.ProductionOrderActionView.as_view(),
        name="production-order-action",
    ),
    path("job-orders/", v.JobOrderListView.as_view(), name="job-orders"),
    path(
        "job-orders/sales-lines/", v.JobOrderSalesLinesView.as_view(), name="job-orders-sales-lines"
    ),
    path("job-orders/waiting/", v.JobExcessWaitingView.as_view(), name="job-orders-waiting"),
    path(
        "job-orders/excess/<int:pk>/decide/",
        v.JobExcessDecideView.as_view(),
        name="job-excess-decide",
    ),
    path("job-orders/<int:pk>/", v.JobOrderDetailView.as_view(), name="job-order"),
    path("job-orders/<int:pk>/lots/", v.JobOrderLotsView.as_view(), name="job-order-lots"),
    path("job-orders/<int:pk>/cards/", v.JobCardsView.as_view(), name="job-order-cards"),
    path(
        "job-orders/<int:pk>/<str:action>/", v.JobOrderActionView.as_view(), name="job-order-action"
    ),
    path("production-plan/", v.PlanView.as_view(), name="production-plan"),
    path("production-plan/copy/", v.PlanCopyView.as_view(), name="production-plan-copy"),
    path("production-plan/mine/", v.MyPlanView.as_view(), name="production-plan-mine"),
    path("production-plan/<int:pk>/", v.PlanEntryView.as_view(), name="production-plan-entry"),
    path("shift-reports/", v.ShiftReportListView.as_view(), name="shift-reports"),
    path("shift-reports/<int:pk>/", v.ShiftReportDetailView.as_view(), name="shift-report"),
    path(
        "shift-reports/<int:pk>/submit/",
        v.ShiftReportSubmitView.as_view(),
        name="shift-report-submit",
    ),
    path(
        "shift-reports/<int:pk>/decide/",
        v.ShiftReportDecideView.as_view(),
        name="shift-report-decide",
    ),
    path(
        "shift-reports/<int:pk>/corrections/",
        v.ShiftCorrectionAskView.as_view(),
        name="shift-report-correction",
    ),
    path(
        "shift-reports/corrections/<int:pk>/decide/",
        v.ShiftCorrectionDecideView.as_view(),
        name="shift-correction-decide",
    ),
    path("mould-maintenance/", v.MouldMaintenanceView.as_view(), name="mould-maintenance"),
    path("cost-rates/", v.CostRatesView.as_view(), name="cost-rates"),
    path("cost-rates/accept/", v.CostRatesAcceptView.as_view(), name="cost-rates-accept"),
    path("cost-rates/<int:pk>/", v.CostRateView.as_view(), name="cost-rate"),
    path("production-setup/", v.ProductionSetupView.as_view(), name="production-setup"),
    path("production-reasons/", v.ReasonsView.as_view(), name="production-reasons"),
    path("production-reasons/<int:pk>/", v.ReasonView.as_view(), name="production-reason"),
]
