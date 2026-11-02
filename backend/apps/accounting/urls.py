from django.urls import path

from . import journal_views as j
from . import manual_views as mj
from . import rate_views as rv
from . import recurring_views as rj
from . import report_views as reports_api
from . import tax_views as t
from . import views as v

urlpatterns = [
    path("chart-of-accounts/", v.AccountListView.as_view(), name="account-list"),
    path("chart-of-accounts/types/", v.AccountTypesView.as_view(), name="account-types"),
    path(
        "chart-of-accounts/detail-types/",
        v.DetailTypeListView.as_view(),
        name="detail-type-list",
    ),
    path(
        "chart-of-accounts/detail-types/<int:pk>/",
        v.DetailTypeDetailView.as_view(),
        name="detail-type-detail",
    ),
    path("chart-of-accounts/export/", v.ChartExportView.as_view(), name="chart-export"),
    path("chart-of-accounts/import/", v.ChartImportView.as_view(), name="chart-import"),
    path("chart-of-accounts/<int:pk>/", v.AccountDetailView.as_view(), name="account-detail"),
    path("chart-of-accounts/<int:pk>/merge/", v.AccountMergeView.as_view(), name="account-merge"),
    path("journal/", j.JournalListView.as_view(), name="journal-list"),
    path("journal/<int:pk>/", j.JournalDetailView.as_view(), name="journal-detail"),
    path("journal/<int:pk>/reverse/", j.JournalReverseView.as_view(), name="journal-reverse"),
    path("recurring-journals/", rj.TemplateListView.as_view(), name="recurring-list"),
    path("recurring-journals/<int:pk>/", rj.TemplateDetailView.as_view(), name="recurring"),
    path(
        "recurring-journals/<int:pk>/active/",
        rj.TemplateActiveView.as_view(),
        name="recurring-active",
    ),
    path("manual-journals/", mj.JournalListView.as_view(), name="manual-journal-list"),
    path("manual-journals/<int:pk>/", mj.JournalDetailView.as_view(), name="manual-journal"),
    path("manual-journals/<int:pk>/submit/", mj.SubmitView.as_view(), name="mj-submit"),
    path("manual-journals/<int:pk>/approve/", mj.ApproveView.as_view(), name="mj-approve"),
    path("manual-journals/<int:pk>/return/", mj.ReturnView.as_view(), name="mj-return"),
    path("manual-journals/<int:pk>/reject/", mj.RejectView.as_view(), name="mj-reject"),
    path(
        "manual-journals/<int:pk>/attachments/",
        mj.AttachmentListView.as_view(),
        name="mj-attachments",
    ),
    path(
        "manual-journals/<int:pk>/attachments/<int:attachment_pk>/",
        mj.AttachmentDetailView.as_view(),
        name="mj-attachment",
    ),
    path("accounting-periods/", j.PeriodListView.as_view(), name="period-list"),
    path(
        "accounting-periods/<str:month>/<str:action>/",
        j.PeriodChangeView.as_view(),
        name="period-change",
    ),
    path("reports/profit-and-loss/", j.ProfitAndLossView.as_view(), name="profit-and-loss"),
    path("reports/trial-balance/", reports_api.TrialBalanceView.as_view(), name="trial-balance"),
    path("reports/balance-sheet/", reports_api.BalanceSheetView.as_view(), name="balance-sheet"),
    path(
        "reports/general-ledger/",
        reports_api.GeneralLedgerView.as_view(),
        name="general-ledger",
    ),
    path("settings/tax-rates/", rv.RateListView.as_view(), name="tax-rates"),
    path("settings/tax-rates/<int:pk>/confirm/", rv.RateConfirmView.as_view(), name="rate-confirm"),
    path("settings/tax-rates/<int:pk>/reject/", rv.RateRejectView.as_view(), name="rate-reject"),
    path(
        "settings/tax-rates/<int:pk>/withdraw/",
        rv.RateWithdrawView.as_view(),
        name="rate-withdraw",
    ),
    path("taxes/", t.TaxOverviewView.as_view(), name="taxes"),
    path("taxes/calculate/", t.CalculateView.as_view(), name="tax-calculate"),
    path("taxes/components/", t.ComponentListView.as_view(), name="tax-component-list"),
    path(
        "taxes/components/<int:pk>/",
        t.ComponentDetailView.as_view(),
        name="tax-component-detail",
    ),
    path("taxes/components/<int:pk>/rates/", t.RateListView.as_view(), name="tax-rate-list"),
    path(
        "taxes/components/<int:pk>/rates/<int:rate_pk>/",
        t.RateDetailView.as_view(),
        name="tax-rate-detail",
    ),
    path("taxes/codes/", t.CodeListView.as_view(), name="tax-code-list"),
    path("taxes/codes/<int:pk>/", t.CodeDetailView.as_view(), name="tax-code-detail"),
]
