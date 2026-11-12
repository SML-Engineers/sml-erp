"""The shared approval engine (backlog P0-17, spec 3 and 4.3)."""

from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError

from apps.core import approvals
from apps.core.approvals import ApprovalError
from apps.core.models import ApprovalLog, ApprovalRule, ApprovalState, AuditEvent, Division, Role

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

V = "voucher"


@pytest.fixture
def clerk():
    return person("clerk@sml.lk", "clerk", all_divisions=True)


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


def submit(user, doc_id=1, amount="25000.00", **extra):
    return approvals.submit(
        user,
        V,
        doc_id,
        created_by=user,
        amount=amount,
        division=Division.objects.get(code="WS"),
        **extra,
    )


# --- The route --------------------------------------------------------------------------


def test_every_voucher_goes_to_the_accountant_then_the_director():
    for amount in ("1.00", "250000000.00", None):
        route = approvals.route_for(V, amount=amount, subtype="petty_cash")
        assert [(s["level"], s["role"]) for s in route] == [(2, "accountant"), (3, "director")]


def test_a_voucher_is_approved_level_by_level_and_logged(clerk, accountant, director):
    state = submit(clerk)
    assert (state.status, state.current_level, state.round) == ("in_progress", 2, 1)
    state = approvals.approve(accountant, V, 1, comment="coded to 6210")
    assert state.current_level == 3
    state = approvals.approve(director, V, 1)
    assert (state.status, state.current_level) == ("approved", None)
    log = list(approvals.history(V, 1))
    assert [(r.level, r.action, r.user) for r in log] == [
        (1, "submit", clerk),
        (2, "approve", accountant),
        (3, "approve", director),
    ]
    assert log[1].reason == "coded to 6210"


def test_only_the_role_of_the_waiting_level_can_act(clerk, accountant, director):
    submit(clerk)
    approvals.approve(accountant, V, 1)
    with pytest.raises(ApprovalError, match="Level 3 is approved by the Director"):
        approvals.approve(accountant, V, 1)
    other_clerk = person("clerk2@sml.lk", "clerk", all_divisions=True)
    with pytest.raises(ApprovalError, match="approved by the Director"):
        approvals.approve(other_clerk, V, 1)


def test_the_director_cannot_act_before_the_accountant(clerk, director):
    submit(clerk)
    with pytest.raises(ApprovalError, match="Level 2 is approved by the Accountant"):
        approvals.approve(director, V, 1)
    with pytest.raises(ApprovalError, match="Level 2 is approved by the Accountant"):
        approvals.send_back(director, V, 1, reason="missing invoice")


# --- Segregation of duties --------------------------------------------------------------


def test_the_creator_cannot_approve_their_own_document(director):
    maker = person("maker@sml.lk", "clerk", "accountant", all_divisions=True)
    submit(maker)
    with pytest.raises(ApprovalError, match="created or submitted"):
        approvals.approve(maker, V, 1)
    with pytest.raises(DatabaseError, match="created or submitted"), transaction.atomic():
        ApprovalLog.objects.create(
            document_type=V, document_id=1, round=1, level=2, action="approve", user=maker
        )
    assert approvals.waiting_for(maker) == []


def test_only_the_creator_submits(clerk, accountant):
    with pytest.raises(ApprovalError, match="Only the person who created"):
        approvals.submit(accountant, V, 1, created_by=clerk, amount="10.00")


def test_the_same_user_cannot_approve_at_two_levels(clerk):
    both = person("both@sml.lk", "accountant", "director", all_divisions=True)
    submit(clerk)
    approvals.approve(both, V, 1)
    with pytest.raises(ApprovalError, match="another level"):
        approvals.approve(both, V, 1)
    with pytest.raises(DatabaseError, match="two levels"), transaction.atomic():
        ApprovalLog.objects.create(
            document_type=V, document_id=1, round=1, level=3, action="approve", user=both
        )
    assert ApprovalState.objects.get(document_id=1).current_level == 3


# --- Return, reject, resubmit -----------------------------------------------------------


def test_return_and_reject_need_a_reason(clerk, accountant):
    submit(clerk)
    for act in (approvals.send_back, approvals.reject):
        with pytest.raises(ApprovalError, match="Give a reason"):
            act(accountant, V, 1, reason="   ")
    for action in ("return", "reject"):
        with pytest.raises(DatabaseError), transaction.atomic():
            ApprovalLog.objects.create(
                document_type=V,
                document_id=1,
                round=1,
                level=2,
                action=action,
                reason="  ",
                user=accountant,
            )


def test_a_returned_document_is_resubmitted_and_approval_restarts_at_l2(
    clerk, accountant, director
):
    submit(clerk)
    approvals.approve(accountant, V, 1)
    state = approvals.send_back(director, V, 1, reason="wrong account")
    assert (state.status, state.current_level) == ("returned", None)
    with pytest.raises(ApprovalError, match="returned"):
        approvals.approve(accountant, V, 1)
    state = submit(clerk, amount="24000.00")
    assert (state.round, state.current_level, state.amount) == (2, 2, Decimal("24000.00"))
    approvals.approve(accountant, V, 1)  # the same level again is allowed
    state = approvals.approve(director, V, 1)
    assert state.status == "approved"
    assert [r.round for r in approvals.history(V, 1)] == [1, 1, 1, 2, 2, 2]


def test_a_rejected_document_is_final(clerk, accountant):
    submit(clerk)
    approvals.reject(accountant, V, 1, reason="duplicate invoice")
    with pytest.raises(ApprovalError, match="rejected"):
        submit(clerk)
    with pytest.raises(ApprovalError, match="rejected"):
        approvals.approve(accountant, V, 1)


def test_the_approval_log_is_insert_only(clerk):
    submit(clerk)
    row = ApprovalLog.objects.get()
    with pytest.raises(DatabaseError), transaction.atomic():
        ApprovalLog.objects.filter(pk=row.pk).update(reason="changed")
    with pytest.raises(DatabaseError), transaction.atomic():
        ApprovalLog.objects.filter(pk=row.pk).delete()


def test_each_approver_sees_what_waits_for_them(clerk, accountant, director):
    submit(clerk, doc_id=1)
    submit(clerk, doc_id=2)
    assert sorted(s.document_id for s in approvals.waiting_for(accountant, V)) == [1, 2]
    assert approvals.waiting_for(director) == []
    approvals.approve(accountant, V, 2)
    assert [s.document_id for s in approvals.waiting_for(director)] == [2]
    assert [s.document_id for s in approvals.waiting_for(accountant)] == [1]


def test_the_dashboard_counts_what_waits_for_each_person(clerk, accountant, director):
    """Owner, 12 Nov 2026: a "waiting for your approval" panel on every dashboard."""
    submit(clerk, doc_id=1)
    submit(clerk, doc_id=2)
    url = "/api/v1/approvals/waiting/"
    assert as_user(accountant).get(url).json() == [
        {"document_type": "voucher", "label": "Payment voucher", "count": 2}
    ]
    assert as_user(director).get(url).json() == []
    approvals.approve(accountant, V, 2)
    assert as_user(director).get(url).json()[0]["count"] == 1
    # The maker never sees their own documents waiting.
    assert as_user(clerk).get(url).json() == []


# --- The matrix -------------------------------------------------------------------------


@pytest.fixture
def chief():
    return Role.objects.create(code="chief_accountant", name="Chief Accountant")


def test_the_admin_adds_a_conditional_level_and_the_route_follows_it(admin, clerk, chief):
    submit(clerk, doc_id=1, amount="2000000.00")  # submitted before the change
    approvals.add_rule(
        admin, document_type=V, level=2, role=chief, min_amount="1000000.00", reason="big ones"
    )
    big = approvals.route_for(V, amount="2000000.00")
    small = approvals.route_for(V, amount="999999.99")
    assert [s["role"] for s in big] == ["chief_accountant", "director"]
    assert [s["role"] for s in small] == ["accountant", "director"]
    # a document already submitted keeps the route it was given
    assert [s["role"] for s in ApprovalState.objects.get(document_id=1).route] == [
        "accountant",
        "director",
    ]
    assert AuditEvent.objects.filter(event="approval_rule_added").exists()


@pytest.mark.parametrize(
    "change, why",
    [
        ({"level": 4, "role": "accountant"}, "must always be the Director"),
        ({"level": 2, "role": "clerk"}, "only one rule that always applies"),
        ({"level": 1, "role": "accountant"}, "from 2"),
        ({"level": 2, "role": "accountant", "min_amount": "10.00", "max_amount": "5.00"}, "above"),
    ],
)
def test_the_matrix_never_lets_a_voucher_skip_the_director(admin, change, why):
    role = Role.objects.get(code=change.pop("role"))
    with pytest.raises(ApprovalError, match=why):
        approvals.add_rule(admin, document_type=V, role=role, **change)


def test_the_director_rule_cannot_be_switched_off(admin):
    rule = ApprovalRule.objects.get(document_type=V, level=3)
    with pytest.raises(ApprovalError, match="needs at least 2 levels"):
        approvals.switch_off_rule(admin, rule, reason="test")
    assert ApprovalRule.objects.get(pk=rule.pk).is_active


def test_a_conditional_rule_is_switched_off_with_a_reason(admin, chief):
    rule = approvals.add_rule(admin, document_type=V, level=2, role=chief, subtype="transfer")
    assert approvals.route_for(V, subtype="transfer")[0]["role"] == "chief_accountant"
    with pytest.raises(ApprovalError, match="reason"):
        approvals.switch_off_rule(admin, rule, reason="")
    approvals.switch_off_rule(admin, rule, reason="no longer needed")
    assert approvals.route_for(V, subtype="transfer")[0]["role"] == "accountant"


def test_only_the_admin_changes_the_matrix(accountant, admin):
    client = as_user(accountant)
    assert client.get("/api/v1/settings/approval-matrix/").status_code == 200
    body = {"document_type": V, "level": 2, "role": "director", "subtype": "cash"}
    assert client.post("/api/v1/settings/approval-matrix/", body, format="json").status_code == 403
    with pytest.raises(ApprovalError, match="Only the Admin"):
        approvals.add_rule(
            accountant, document_type=V, level=2, role=Role.objects.get(code="director")
        )
    response = as_user(admin).post("/api/v1/settings/approval-matrix/", body, format="json")
    assert response.status_code == 201, response.json()
    [added] = [r for r in response.json()["rules"] if r["subtype"] == "cash"]
    assert (added["level"], added["role"]["code"], added["is_active"]) == (2, "director", True)
    route = (
        as_user(admin)
        .get("/api/v1/settings/approval-matrix/route/?document_type=voucher&subtype=cash")
        .json()
    )
    assert [s["role"] for s in route] == ["director", "director"]
    unknown = as_user(admin).get("/api/v1/settings/approval-matrix/route/?document_type=nothing")
    assert unknown.status_code == 400
