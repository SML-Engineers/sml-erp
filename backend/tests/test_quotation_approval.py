"""Approval, revisions and status of quotations (backlog P15-06, spec 5.1, 3)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.core import approvals
from apps.core.models import AuditEvent, Division, Notification
from apps.masters import costing_rates, customers, limits
from apps.masters import services as masters
from apps.masters.models import Section
from apps.sales import costing, services, tasks, workflow
from apps.sales.costing import CostingInput, OperationInput
from apps.sales.models import Quotation, QuotationCosting, QuotationLine
from apps.sales.services import BreakInput, LineInput, SalesError

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
S = Quotation.Status


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def manager():
    return person("salesmanager@sml.lk", "sales_manager", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def unilever(executive):
    return customers.create_customer(executive, {"name": "Unilever Sri Lanka"})


@pytest.fixture
def lathe(accountant):
    """A lathe at LKR 3,000 an hour; WS costing rates 15% overhead and 20% margin."""
    costing_rates.add_costing_rate(
        accountant,
        Division.objects.get(code="WS"),
        effective_from=TODAY,
        overhead_pct="15",
        margin_pct="20",
        setup_rate="1500",
    )
    m = masters.create_machine(
        code="C-LAT-01", section=Section.objects.get(code="C-LAT"), name="CNC lathe"
    )
    masters.add_rate(m, effective_from=TODAY, rate="3000")
    return m


def draft(user, customer, *lines, **values):
    return services.save(
        user,
        None,
        customer=customer,
        division=Division.objects.get(code="WS"),
        lines=list(lines)
        or [
            LineInput(
                description="Shaft",
                quantity="10",
                unit_price="1500",
                breaks=[BreakInput("50", "1200")],
            )
        ],
        **values,
    )


def cost(user, q, line_no=1, minutes="20"):
    """20 minutes at LKR 3,000/h = 1,000; + 15% = cost 1,150 a piece."""
    return costing.save(
        user, q, line_no, CostingInput(operations=[OperationInput(_lathe(), minutes)])
    )


def _lathe():
    from apps.masters.models import Machine

    return Machine.objects.select_related("section").get(code="C-LAT-01")


@pytest.fixture
def approved(executive, director, unilever, lathe):
    q = draft(executive, unilever)
    cost(executive, q)
    workflow.submit(executive, q)
    return workflow.approve(director, q)


# --- Approval by the Director -----------------------------------------------------------


def test_the_director_approves_every_quotation(executive, director, unilever, lathe):
    q = draft(executive, unilever)
    assert not workflow.is_final(q)  # a draft prints only as NOT APPROVED (P15-07)
    cost(executive, q)
    q = workflow.submit(executive, q, "Repeat customer")
    assert q.status == S.AWAITING_APPROVAL
    state = approvals.state_of("quotation", q.pk)
    assert [step["role"] for step in state.route] == ["director"]
    assert Notification.objects.filter(user=director, event="approval_waiting").exists()
    assert workflow.can_approve(director, q)
    q = workflow.approve(director, q, "Fine")
    assert (q.status, workflow.is_final(q)) == (S.APPROVED, True)
    assert q.approved_at is not None
    assert Notification.objects.filter(user=executive, event="document_approved").exists()


def test_the_sales_manager_does_not_approve_in_the_directors_place(
    executive, manager, unilever, lathe
):
    q = workflow.submit(executive, draft(executive, unilever))
    assert not workflow.can_approve(manager, q)
    with pytest.raises(SalesError, match="approved by the Director"):
        workflow.approve(manager, q)


def test_nobody_approves_a_quotation_they_made(unilever, lathe):
    both = person("both@sml.lk", "sales_executive", "director", all_divisions=True)
    q = workflow.submit(both, draft(both, unilever))
    assert not workflow.can_approve(both, q)
    with pytest.raises(SalesError, match="cannot approve a document you created"):
        workflow.approve(both, q)


def test_only_the_creator_submits_a_draft(executive, unilever, lathe):
    other = person("sales2@sml.lk", "sales_executive", all_divisions=True)
    q = draft(executive, unilever)
    with pytest.raises(SalesError, match="Only the person who made"):
        workflow.submit(other, q)


def test_a_returned_quotation_is_changed_and_sent_again(executive, director, unilever, lathe):
    q = workflow.submit(executive, draft(executive, unilever))
    with pytest.raises(SalesError, match="Give a reason"):
        workflow.send_back(director, q, "")
    q = workflow.send_back(director, q, "Price too low for 10 pieces")
    assert q.status == S.DRAFT and services.can_edit(executive, q)
    first = q.lines.get()
    services.save(
        executive,
        q,
        lines=[LineInput(id=first.id, description="Shaft", quantity="10", unit_price="1800")],
    )
    q = workflow.submit(executive, q)
    assert approvals.state_of("quotation", q.pk).round == 2
    assert workflow.approve(director, q).status == S.APPROVED


def test_a_quotation_past_its_validity_is_not_sent_for_approval(executive, unilever, lathe):
    q = draft(executive, unilever)
    old = TODAY - timedelta(days=10)
    Quotation.objects.filter(pk=q.pk).update(quote_date=old, valid_until=old)
    q.refresh_from_db()
    with pytest.raises(SalesError, match="validity date has passed"):
        workflow.submit(executive, q)


# --- Warnings for the Director ----------------------------------------------------------


def test_the_director_is_warned_but_not_blocked(executive, director, unilever, lathe):
    q = draft(
        executive,
        unilever,
        LineInput(description="Shaft", quantity="10", unit_price="1300"),
        LineInput(description="Bush", quantity="5", unit_price="800"),
    )
    cost(executive, q)  # cost 1,150 a piece; quoted 1,300: margin 13.04%
    found = workflow.review(q)
    assert found["margin_pct"] == Decimal("13.04")
    assert "Line 2 has no costing." in found["warnings"]
    assert "No confirmed quotation limits for WS" in " ".join(found["warnings"])
    admin = person("admin@sml.lk", "system_admin", all_divisions=True)
    limit = limits.propose(
        user=admin,
        division=Division.objects.get(code="WS"),
        effective_from=TODAY,
        min_margin_pct="20",
        director_above_lkr="15000",
        reason="Policy",
    )
    limits.confirm(director, limit)
    found = workflow.review(q)
    assert "Margin 13.04% is below the minimum of 20.00%." in found["warnings"]
    assert "Value LKR 17,000.00 is above the limit of LKR 15,000.00." in found["warnings"]
    workflow.submit(executive, q)
    assert workflow.approve(director, q).status == S.APPROVED  # warnings never block


def test_a_price_below_cost_is_a_warning(executive, unilever, lathe):
    q = draft(executive, unilever)  # 10 at 1,500 and 50 at 1,200
    cost(executive, q, minutes="25")  # 1,250 + 15% = 1,437.50 at 10; same per piece at 50
    assert workflow.review(q)["warnings"][0] == "Line 1: the price for 50 is below cost."


# --- Sent, won, lost, expired -----------------------------------------------------------


def test_only_an_approved_quotation_is_sent(executive, director, manager, unilever, lathe):
    q = draft(executive, unilever)
    with pytest.raises(SalesError, match="Only an approved quotation"):
        workflow.mark_sent(executive, q)
    workflow.submit(executive, q)
    q = workflow.approve(director, q)
    q = workflow.mark_sent(manager, q)
    assert q.status == S.SENT and q.sent_by == manager and q.sent_at is not None


def test_won_or_lost_with_the_reason(approved, executive):
    with pytest.raises(SalesError, match="reason the quotation was lost"):
        workflow.record_outcome(executive, approved, accepted=False)
    with pytest.raises(SalesError, match="other reason"):
        workflow.record_outcome(executive, approved, accepted=False, reason="other")
    lost = workflow.record_outcome(
        executive, approved, accepted=False, reason="price", note="Local shop 15% cheaper"
    )
    assert (lost.status, lost.outcome_reason, lost.outcome_by) == (S.LOST, "price", executive)
    assert AuditEvent.objects.filter(event="quotation_lost").exists()
    with pytest.raises(SalesError, match="approved, sent or expired"):
        workflow.record_outcome(executive, lost, accepted=True)


def test_a_won_quotation_is_accepted(approved, manager):
    won = workflow.record_outcome(manager, approved, accepted=True, reason="lead_time")
    assert won.status == S.ACCEPTED and workflow.is_final(won)


def test_quotations_expire_after_their_validity(approved, executive, unilever):
    still_draft = draft(executive, unilever)
    assert workflow.expire_due(approved.valid_until) == 0  # still valid on its last day
    assert workflow.expire_due(approved.valid_until + timedelta(days=1)) == 1
    approved.refresh_from_db()
    still_draft.refresh_from_db()
    assert (approved.status, still_draft.status) == (S.EXPIRED, S.DRAFT)
    assert tasks.expire_quotations() == 0  # the daily job; nothing more is due today


# --- Never changed after the draft: revisions -------------------------------------------


def test_the_database_refuses_changes_after_the_draft(approved):
    with pytest.raises(DatabaseError, match="make a revision"), transaction.atomic():
        Quotation.objects.filter(pk=approved.pk).update(total_amount=Decimal("1.00"))
    line = approved.lines.get()
    with pytest.raises(DatabaseError, match="make a revision"), transaction.atomic():
        QuotationLine.objects.filter(pk=line.pk).update(unit_price=Decimal("1.00"))
    with pytest.raises(DatabaseError, match="make a revision"), transaction.atomic():
        QuotationCosting.objects.filter(line=line).update(margin_pct=Decimal("50"))
    with pytest.raises(DatabaseError, match="make a revision"), transaction.atomic():
        line.breaks.all().delete()


def test_a_revision_keeps_the_number_and_the_history(approved, executive):
    new = workflow.revise(executive, approved)
    approved.refresh_from_db()
    assert (new.number, new.revision, new.parent_id) == (approved.number, 1, approved.pk)
    assert (new.status, approved.status) == (S.DRAFT, S.REVISED)
    assert new.quote_date == TODAY and new.label == f"{approved.number} Rev 1"
    line = new.lines.get()
    assert (line.description, line.unit_price) == ("Shaft", Decimal("1500.00"))
    assert [b.quantity for b in line.breaks.all()] == [Decimal("50.000")]
    assert line.costing.operations.get().rate == Decimal("3000.00")
    assert approved.lines.get().costing.pk != line.costing.pk
    assert [r.revision for r in workflow.revisions(new)] == [0, 1]
    with pytest.raises(SalesError, match="change a draft directly"):
        workflow.revise(executive, new)
    with pytest.raises(SalesError, match="Only an approved"):
        workflow.revise(executive, approved)  # already replaced


def test_drawings_are_copied_to_the_revision(executive, director, unilever, lathe):
    q = draft(executive, unilever)
    services.add_file(executive, q, SimpleUploadedFile("shaft.pdf", b"%PDF-1 shaft"), 1)
    workflow.submit(executive, q)
    workflow.approve(director, q)
    new = workflow.revise(executive, q)
    assert [(f.file_name, f.line_no) for f in new.files.all()] == [("shaft.pdf", 1)]


def test_only_the_creator_revises(approved, manager):
    with pytest.raises(SalesError, match="Only the person who made"):
        workflow.revise(manager, approved)


# --- Through the API --------------------------------------------------------------------


def test_the_api_takes_a_quotation_from_draft_to_won(
    executive, director, manager, accountant, unilever, lathe
):
    q = draft(executive, unilever)
    cost(executive, q)
    sales = as_user(executive)
    base = f"/api/v1/quotations/{q.pk}/"
    detail = sales.get(base).json()
    assert (detail["can_submit"], detail["is_final"], detail["approval"]) == (True, False, None)
    assert detail["review"]["margin_pct"] == "30.43"
    assert sales.post(f"{base}submit/", {"comment": "Urgent"}, format="json").status_code == 200

    boss = as_user(director)
    waiting = boss.get("/api/v1/quotations/?waiting=me").json()
    assert [row["id"] for row in waiting] == [q.pk]
    seen = boss.get(base).json()
    assert seen["can_approve"] and seen["approval"]["waiting_with"] == "Director"
    assert "review" in seen
    assert as_user(manager).post(f"{base}approve/", {}, format="json").status_code == 400
    assert sales.post(f"{base}approve/", {}, format="json").status_code == 403  # Sales: Enter
    approved = boss.post(f"{base}approve/", {"comment": "OK"}, format="json").json()
    assert approved["status"] == "approved" and approved["is_final"] is True
    assert [h["action"] for h in approved["approval"]["history"]] == ["submit", "approve"]

    assert sales.post(f"{base}sent/", {}, format="json").json()["status"] == "sent"
    no_reason = sales.post(f"{base}outcome/", {"outcome": "lost"}, format="json")
    assert no_reason.status_code == 400
    won = sales.post(f"{base}outcome/", {"outcome": "accepted", "reason": "price"}, format="json")
    assert won.json()["status"] == "accepted"
    assert won.json()["outcome"]["reason_label"] == "Price"
    assert as_user(accountant).post(f"{base}sent/", {}, format="json").status_code == 400


def test_the_api_returns_and_revises(executive, director, unilever, lathe):
    q = draft(executive, unilever)
    sales, boss = as_user(executive), as_user(director)
    base = f"/api/v1/quotations/{q.pk}/"
    sales.post(f"{base}submit/", {}, format="json")
    returned = boss.post(f"{base}return/", {"reason": "Check the lead time"}, format="json")
    assert returned.json()["status"] == "draft"
    sales.post(f"{base}submit/", {}, format="json")
    boss.post(f"{base}approve/", {}, format="json")
    revised = sales.post(f"{base}revise/", {}, format="json")
    assert revised.status_code == 201
    body = revised.json()
    assert (body["revision"], body["status"]) == (1, "draft")
    assert [(r["revision"], r["status"]) for r in body["revisions"]] == [
        (0, "revised"),
        (1, "draft"),
    ]


def test_the_warnings_are_only_for_those_who_see_costing(executive, unilever, lathe):
    q = draft(executive, unilever)
    auditor = person("auditor@sml.lk", "auditor", all_divisions=True)
    assert "review" not in as_user(auditor).get(f"/api/v1/quotations/{q.pk}/").json()
