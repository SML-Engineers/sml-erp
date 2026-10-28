from django.urls import path

from . import views as v

urlpatterns = [
    path("voucher-types/", v.TypeListView.as_view(), name="voucher-type-list"),
    path("voucher-types/<int:pk>/", v.TypeDetailView.as_view(), name="voucher-type-detail"),
]
