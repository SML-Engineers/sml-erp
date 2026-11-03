from django.urls import path

from . import petty_views as pv
from . import reconcile_views as rv
from . import statement_views as sv
from . import views as v

urlpatterns = [
    path("cheques/issued/", v.IssuedView.as_view(), name="cheques-issued"),
    path("cheques/issued/<int:pk>/clear/", v.ClearIssuedView.as_view(), name="cheque-clear"),
    path("cheques/received/", v.ReceivedView.as_view(), name="cheques-received"),
    path(
        "cheques/received/<int:pk>/clear/",
        v.ClearReceivedView.as_view(),
        name="received-cheque-clear",
    ),
    path(
        "cheques/received/<int:pk>/return/",
        v.ReturnReceivedView.as_view(),
        name="received-cheque-return",
    ),
    path("deposits/", v.DepositListView.as_view(), name="deposits"),
    path("deposits/<int:pk>/", v.DepositDetailView.as_view(), name="deposit"),
    path("statement-templates/", sv.TemplateListView.as_view(), name="statement-templates"),
    path(
        "statement-templates/<int:pk>/",
        sv.TemplateDetailView.as_view(),
        name="statement-template",
    ),
    path("bank-statements/", sv.StatementListView.as_view(), name="bank-statements"),
    path("bank-statements/import/", sv.ImportView.as_view(), name="bank-statement-import"),
    path("bank-statements/<int:pk>/", sv.StatementDetailView.as_view(), name="bank-statement"),
    path("reconciliation/", rv.SummaryView.as_view(), name="reconciliation"),
    path(
        "reconciliation/lines/<int:pk>/candidates/",
        rv.CandidatesView.as_view(),
        name="reconciliation-candidates",
    ),
    path("reconciliation/match/", rv.MatchView.as_view(), name="reconciliation-match"),
    path("reconciliation/unmatch/", rv.UnmatchView.as_view(), name="reconciliation-unmatch"),
    path("reconciliation/post/", rv.PostView.as_view(), name="reconciliation-post"),
    path("reconciliation/accept/", rv.AcceptView.as_view(), name="reconciliation-accept"),
    path("reconciliation/finish/", rv.FinishView.as_view(), name="reconciliation-finish"),
    path("bank-rules/", rv.RuleListView.as_view(), name="bank-rules"),
    path("bank-rules/<int:pk>/", rv.RuleDetailView.as_view(), name="bank-rule"),
    path("petty-cash/", pv.FloatListView.as_view(), name="petty-floats"),
    path("petty-cash/<int:pk>/expenses/", pv.ExpenseListView.as_view(), name="petty-expenses"),
    path("petty-cash/<int:pk>/replenish/", pv.ReplenishView.as_view(), name="petty-replenish"),
    path(
        "petty-expenses/<int:pk>/",
        pv.ExpenseDetailView.as_view(),
        name="petty-expense",
    ),
    path("petty-expenses/<int:pk>/slip/", pv.SlipView.as_view(), name="petty-expense-slip"),
]
