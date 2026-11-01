from django.urls import path

from . import receipt_views as r
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
    path("goods-receipts/<int:pk>/photos/", r.PhotoListView.as_view(), name="grn-photos"),
    path(
        "goods-receipts/<int:pk>/photos/<int:photo_pk>/",
        r.PhotoDetailView.as_view(),
        name="grn-photo",
    ),
]
