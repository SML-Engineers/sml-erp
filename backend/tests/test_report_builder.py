# ruff: noqa: F811 - fixtures of other test modules are imported and used by name
"""Custom report builder (backlog P2-26)."""

import json

import pytest
from django.core import mail
from django.utils import timezone

from apps.accounting import report_builder as rb
from apps.accounting.report_builder import ReportError

from .test_access import as_user, person
from .test_journal import accountant, cost, director, sale  # noqa: F401
from .test_quotation_pdf import mailbox, memory_storage  # noqa: F401

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
COSTS = {
    "source": "journal_lines",
    "columns": ["account", "debit", "credit"],
    "filters": [{"field": "account_type", "op": "equals", "value": "expense"}],
    "group_by": "account",
}


@pytest.fixture
def books(accountant):
    sale(accountant, "1000.00", "WS")
    cost(accountant, "400.00", "WS")
    cost(accountant, "300.00", "IM", account="6210")


def run(user, definition):
    return rb.run(user, rb.parse(user, definition))


def test_columns_filters_grouping_and_subtotals(accountant, books):
    result = run(accountant, COSTS)
    assert [c["key"] for c in result["columns"]] == ["account", "debit", "credit"]
    kinds = [r["kind"] for r in result["rows"]]
    assert kinds == ["line", "subtotal", "line", "subtotal", "total"]
    total = result["rows"][-1]["cells"]
    assert (total["account"], total["debit"], total["credit"]) == ("Total", "700.00", "0.00")
    assert result["rows"][1]["cells"]["debit"] in ("300.00", "400.00")


def test_period_columns_by_division_and_by_month(accountant, books):
    by_division = run(accountant, COSTS | {"period": "division", "measure": "debit"})
    assert [c["key"] for c in by_division["columns"]] == ["account", "IM", "WS", "total"]
    total = by_division["rows"][-1]["cells"]
    assert (total["IM"], total["WS"], total["total"]) == ("300.00", "400.00", "700.00")
    sales = run(
        accountant,
        {
            "source": "journal_lines",
            "columns": ["account", "credit"],
            "filters": [{"field": "account_number", "op": "equals", "value": "4010"}],
            "group_by": "account",
            "period": "month",
            "measure": "credit",
        },
    )
    month = f"{TODAY:%Y-%m}"
    assert sales["rows"][0]["cells"][month] == "1000.00"


def test_what_a_definition_may_be(accountant):
    with pytest.raises(ReportError, match="at least one column"):
        rb.parse(accountant, {"source": "journal_lines", "columns": []})
    with pytest.raises(ReportError, match="cannot be filtered"):
        rb.parse(
            accountant, COSTS | {"filters": [{"field": "debit", "op": "contains", "value": "1"}]}
        )
    with pytest.raises(ReportError, match="not an amount"):
        rb.parse(accountant, COSTS | {"group_by": "debit"})
    with pytest.raises(ReportError, match="no column"):
        rb.parse(accountant, COSTS | {"columns": ["salary"]})


def test_a_source_needs_its_area(accountant):
    clerk = person("clerk@sml.lk", "clerk", all_divisions=True)
    assert "journal_lines" not in {s.key for s in rb.sources_for(clerk)}
    with pytest.raises(ReportError, match="do not have access"):
        rb.parse(clerk, COSTS)


def test_saved_and_shared_with_a_role(accountant, director, books):
    api = as_user(accountant)
    made = api.post(
        "/api/v1/report-builder/saved/",
        {"name": "Costs by account", "definition": COSTS, "shared_role": "director"},
        format="json",
    )
    assert made.status_code == 201, made.data
    boss = as_user(director)
    seen = boss.get("/api/v1/report-builder/").json()
    assert [s["name"] for s in seen["saved"]] == ["Costs by account"]
    assert seen["saved"][0]["mine"] is False
    refused = boss.delete(f"/api/v1/report-builder/saved/{made.data['id']}/")
    assert refused.status_code == 400
    clerk = as_user(person("clerk@sml.lk", "clerk", all_divisions=True))
    assert clerk.get("/api/v1/report-builder/").json()["saved"] == []
    assert api.delete(f"/api/v1/report-builder/saved/{made.data['id']}/").status_code == 204


def test_run_export_and_email(accountant, books, mailbox):
    api = as_user(accountant)
    d = json.dumps(COSTS)
    got = api.get("/api/v1/report-builder/run/", {"d": d})
    assert got.status_code == 200 and got.json()["count"] == 2
    assert api.get("/api/v1/report-builder/run/", {"d": d, "export": "xlsx"}).status_code == 200
    assert api.get("/api/v1/report-builder/run/", {"d": d, "export": "pdf"}).status_code == 200
    message = api.get("/api/v1/report-builder/email/", {"name": "Costs"}).json()
    sent = api.post(
        "/api/v1/report-builder/email/",
        {
            "definition": COSTS,
            "name": "Costs",
            "to": ["owner@smlengineers.lk"],
            "subject": message["subject"],
            "body": message["body"],
        },
        format="json",
    )
    assert sent.status_code == 200, sent.json()
    (email,) = mail.outbox
    assert email.attachments[0][0] == "Costs.xlsx"
