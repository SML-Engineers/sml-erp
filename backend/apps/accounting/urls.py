from django.urls import path

from . import budget_views as bv
from . import close_views as cv
from . import journal_views as j
from . import manual_views as mj
from . import planner_views as pv
from . import quickbooks_views as qbv
from . import rate_views as rv
from . import recurring_views as rj
from . import report_builder_views as rbv
from . import report_views as reports_api
from . import revaluation_views as rev
from . import tax_report_views as tr
from . import tax_views as t
from . import views as v

urlpatterns = [
    path("migration/", qbv.MigrationView.as_view(), name="migration"),
    path(
        "migration/<int:pk>/",
        qbv.MigrationActionView.as_view(action="delete"),
        name="migration-one",
    ),
    *[
        path(
            f"migration/<int:pk>/{name}/",
            qbv.MigrationActionView.as_view(action=name),
            name=f"migration-{name}",
        )
        for name in ("submit", "approve", "return", "reject")
    ],
    path("report-builder/", rbv.BuilderView.as_view(), name="report-builder"),
    path("report-builder/run/", rbv.RunView.as_view(), name="report-builder-run"),
    path("report-builder/email/", rbv.EmailView.as_view(), name="report-builder-email"),
    path("report-builder/saved/", rbv.SavedListView.as_view(), name="report-builder-saved"),
    path(
        "report-builder/saved/<int:pk>/",
        rbv.SavedDetailView.as_view(),
        name="report-builder-saved-one",
    ),
    path("cash-planner/", pv.PlannerView.as_view(), name="cash-planner"),
    path("cash-planner/what-ifs/", pv.WhatIfView.as_view(), name="cash-planner-what-ifs"),
    path(
        "cash-planner/what-ifs/<int:pk>/",
        pv.WhatIfDetailView.as_view(),
        name="cash-planner-what-if",
    ),
    path("month-end/<str:month>/", cv.ChecklistView.as_view(), name="month-end"),
    path("month-end/<str:month>/tick/", cv.TickView.as_view(), name="month-end-tick"),
    path("year-end/", cv.YearView.as_view(), name="year-end"),
    path(
        "year-end/<int:year>/close/",
        cv.YearActionView.as_view(action="close"),
        name="year-end-close",
    ),
    path(
        "year-end/<int:year>/reopen/",
        cv.YearActionView.as_view(action="reopen"),
        name="year-end-reopen",
    ),
    path("budgets/", bv.BudgetListView.as_view(), name="budget-list"),
    path("budgets/<int:pk>/", bv.BudgetDetailView.as_view(), name="budget-detail"),
    path("budgets/<int:pk>/export/", bv.BudgetExportView.as_view(), name="budget-export"),
    path("budgets/<int:pk>/import/", bv.BudgetImportView.as_view(), name="budget-import"),
    path(
        "budgets/<int:pk>/submit/",
        bv.BudgetActionView.as_view(action="submit"),
        name="budget-submit",
    ),
    path(
        "budgets/<int:pk>/approve/",
        bv.BudgetActionView.as_view(action="approve"),
        name="budget-approve",
    ),
    path(
        "budgets/<int:pk>/return/",
        bv.BudgetActionView.as_view(action="return"),
        name="budget-return",
    ),
    path(
        "budgets/<int:pk>/reject/",
        bv.BudgetActionView.as_view(action="reject"),
        name="budget-reject",
    ),
    path("revaluations/", rev.RevaluationListView.as_view(), name="revaluation-list"),
    path(
        "revaluations/<int:pk>/post/",
        rev.RevaluationActionView.as_view(action="post"),
        name="revaluation-post",
    ),
    path(
        "revaluations/<int:pk>/discard/",
        rev.RevaluationActionView.as_view(action="discard"),
        name="revaluation-discard",
    ),
    path("tax-reports/vat/", tr.VatView.as_view(), name="tax-report-vat"),
    path(
        "tax-reports/vat/purchases/",
        tr.VatPurchasesExportView.as_view(),
        name="tax-report-vat-purchases",
    ),
    path("tax-reports/sscl/", tr.SsclView.as_view(), name="tax-report-sscl"),
    path("tax-reports/wht/", tr.WhtView.as_view(), name="tax-report-wht"),
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
    path("reports/cash-flow/", reports_api.CashFlowView.as_view(), name="cash-flow"),
    path(
        "reports/dashboard/",
        reports_api.FinancialDashboardView.as_view(),
        name="financial-dashboard",
    ),
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
