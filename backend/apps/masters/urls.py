from django.urls import path

from . import currency_views as cv
from . import limit_views as lv
from . import roster_views as rv
from . import supplier_views as sv
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
    path("settings/shifts/", rv.ShiftListView.as_view(), name="settings-shift-list"),
    path("settings/shifts/<int:pk>/", rv.ShiftDetailView.as_view(), name="settings-shift-detail"),
    path("settings/roster-patterns/", rv.PatternListView.as_view(), name="roster-pattern-list"),
    path(
        "settings/roster-patterns/<int:pk>/",
        rv.PatternDetailView.as_view(),
        name="roster-pattern-detail",
    ),
    path("settings/crews/", rv.CrewListView.as_view(), name="crew-list"),
    path("settings/crews/<int:pk>/", rv.CrewDetailView.as_view(), name="crew-detail"),
    path("settings/rosters/", rv.AssignmentListView.as_view(), name="roster-list"),
    path("settings/rosters/preview/", rv.RosterPreviewView.as_view(), name="roster-preview"),
    path("settings/rosters/<int:pk>/", rv.AssignmentDetailView.as_view(), name="roster-detail"),
    path("currencies/", cv.CurrencyPickerView.as_view(), name="currency-picker"),
    path("exchange-rates/lookup/", cv.RateLookupView.as_view(), name="rate-lookup"),
    path("settings/currencies/", cv.CurrencyListView.as_view(), name="currency-list"),
    path(
        "settings/currencies/<str:code>/", cv.CurrencyDetailView.as_view(), name="currency-detail"
    ),
    path("settings/exchange-rates/", cv.RateListView.as_view(), name="rate-list"),
    path("settings/exchange-rates/import/", cv.RateImportView.as_view(), name="rate-import"),
    path("settings/exchange-rates/<int:pk>/", cv.RateDetailView.as_view(), name="rate-detail"),
    path("settings/quotation-limits/", lv.LimitListView.as_view(), name="limit-list"),
    path(
        "settings/quotation-limits/<int:pk>/confirm/",
        lv.LimitConfirmView.as_view(),
        name="limit-confirm",
    ),
    path(
        "settings/quotation-limits/<int:pk>/reject/",
        lv.LimitRejectView.as_view(),
        name="limit-reject",
    ),
    path(
        "settings/quotation-limits/<int:pk>/withdraw/",
        lv.LimitWithdrawView.as_view(),
        name="limit-withdraw",
    ),
    path("payees/", sv.SupplierListView.as_view(), name="payee-list"),
    path("payees/<int:pk>/", sv.SupplierDetailView.as_view(), name="payee-detail"),
    path(
        "payees/<int:pk>/bank-accounts/",
        sv.BankAccountListView.as_view(),
        name="payee-bank-accounts",
    ),
    path(
        "payees/<int:pk>/bank-accounts/<int:account_pk>/",
        sv.BankAccountDetailView.as_view(),
        name="payee-bank-account-detail",
    ),
    path(
        "payees/<int:pk>/acknowledge-bank-change/",
        sv.AcknowledgeBankChangeView.as_view(),
        name="payee-acknowledge-bank-change",
    ),
    path("users/<int:pk>/sections/", views.UserSectionsView.as_view(), name="user-sections"),
]
