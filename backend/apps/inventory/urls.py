from django.urls import path

from . import inspection_views as q
from . import receipt_views as r
from . import stock_views as sv
from . import views

urlpatterns = [
    path("items/", views.ItemListView.as_view(), name="item-list"),
    path("items/options/", views.ItemOptionsView.as_view(), name="item-options"),
    path("items/export/", views.ItemExportView.as_view(), name="item-export"),
    path("items/import/", views.ItemImportView.as_view(), name="item-import"),
    path("items/<int:pk>/", views.ItemDetailView.as_view(), name="item-detail"),
    path("items/<int:pk>/active/", views.ItemActiveView.as_view(), name="item-active"),
    path("stores/", views.StoreListView.as_view(), name="store-list"),
    path("stores/<int:pk>/", views.StoreDetailView.as_view(), name="store-detail"),
    path("goods-receipts/", r.ReceiptListView.as_view(), name="grn-list"),
    path("goods-receipts/receivable/", r.ReceivableView.as_view(), name="grn-receivable"),
    path("goods-receipts/<int:pk>/", r.ReceiptDetailView.as_view(), name="grn-detail"),
    path("goods-receipts/<int:pk>/confirm/", r.ConfirmView.as_view(), name="grn-confirm"),
    path("goods-receipts/<int:pk>/approve/", r.ApproveExcessView.as_view(), name="grn-approve"),
    path("goods-receipts/<int:pk>/return/", r.ReturnView.as_view(), name="grn-return"),
    path("goods-receipts/<int:pk>/reverse/", r.ReverseView.as_view(), name="grn-reverse"),
    path(
        "goods-receipts/<int:pk>/reversal/approve/",
        r.ApproveReversalView.as_view(),
        name="grn-reversal-approve",
    ),
    path(
        "goods-receipts/<int:pk>/reversal/refuse/",
        r.RefuseReversalView.as_view(),
        name="grn-reversal-refuse",
    ),
    path(
        "goods-receipts/<int:pk>/lines/<int:line_no>/packages/",
        r.PackagesView.as_view(),
        name="grn-packages",
    ),
    path("goods-receipts/<int:pk>/labels/", r.LabelsView.as_view(), name="grn-labels"),
    path("goods-receipts/<int:pk>/photos/", r.PhotoListView.as_view(), name="grn-photos"),
    path(
        "goods-receipts/<int:pk>/photos/<int:photo_pk>/",
        r.PhotoDetailView.as_view(),
        name="grn-photo",
    ),
    path("inspection-plans/", q.PlanListView.as_view(), name="plan-list"),
    path("inspection-plans/<int:pk>/", q.PlanDetailView.as_view(), name="plan-detail"),
    path("inspections/", q.InspectionListView.as_view(), name="inspection-list"),
    path("inspections/queue/", q.QueueView.as_view(), name="inspection-queue"),
    path("inspections/<int:pk>/", q.InspectionDetailView.as_view(), name="inspection-detail"),
    path("inspections/<int:pk>/decide/", q.DecideView.as_view(), name="inspection-decide"),
    path("inspections/<int:pk>/approve/", q.ApproveView.as_view(), name="inspection-approve"),
    path("inspections/<int:pk>/return/", q.ReturnView.as_view(), name="inspection-return"),
    path(
        "inspections/<int:pk>/attachments/",
        q.AttachmentListView.as_view(),
        name="inspection-attachments",
    ),
    path(
        "inspections/<int:pk>/attachments/<int:attachment_pk>/",
        q.AttachmentDetailView.as_view(),
        name="inspection-attachment",
    ),
    path("stock/", sv.StockOnHandView.as_view(), name="stock-on-hand"),
    path("stock/movements/", sv.MovementListView.as_view(), name="stock-movements"),
]
