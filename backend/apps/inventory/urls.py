from django.urls import path

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
]
