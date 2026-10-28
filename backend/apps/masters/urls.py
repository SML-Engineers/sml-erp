from django.urls import path

from . import views

urlpatterns = [
    path("sections/", views.SectionPickerView.as_view(), name="section-picker"),
    path("machines/", views.MachinePickerView.as_view(), name="machine-picker"),
    path("settings/sections/", views.SectionListView.as_view(), name="settings-section-list"),
    path(
        "settings/sections/<int:pk>/",
        views.SectionDetailView.as_view(),
        name="settings-section-detail",
    ),
    path("settings/machines/", views.MachineListView.as_view(), name="settings-machine-list"),
    path(
        "settings/machines/<int:pk>/",
        views.MachineDetailView.as_view(),
        name="settings-machine-detail",
    ),
    path(
        "settings/machines/<int:pk>/rates/",
        views.MachineRatesView.as_view(),
        name="settings-machine-rates",
    ),
    path(
        "settings/machines/<int:pk>/rates/<int:rate_pk>/",
        views.MachineRateDetailView.as_view(),
        name="settings-machine-rate-detail",
    ),
    path(
        "settings/machines/<int:pk>/photo/",
        views.MachinePhotoView.as_view(),
        name="settings-machine-photo",
    ),
    path("settings/factory/export/", views.FactoryExportView.as_view(), name="factory-export"),
    path("settings/factory/import/", views.FactoryImportView.as_view(), name="factory-import"),
    path("users/<int:pk>/sections/", views.UserSectionsView.as_view(), name="user-sections"),
]
