"""Sales orders (backlog P15-10, spec 5.3)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.accounting import services as chart
from apps.accounting.models import DetailType, JournalEntry
from apps.core import approvals
from apps.core.models import Division, Notification
from apps.masters import banking, customers
from apps.sales import advances, orders, proformas, services, workflow
from apps.sales.models import DeliverySchedule, SalesOrder
from apps.sales.orders import Delivery, LineInput
from apps.sales.services import BreakInput, SalesError
from apps.sales.services import LineInput as QuoteLine

from .test_access import as_user, person

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
S = SalesOrder.Status


@pytest.fixture
def executive():
    return person("sales@sml.lk", "sales_executive", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def unilever(executive):
    customer = customers.create_customer(
        executive, {"name": "Unilever Sri Lanka", "delivery_address": "Grandpass, Colombo 14"}
    )
    customers.add_contact(executive, customer, {"name": "Nimali"})
    return customer


@pytest.fixture
def won(executive, director, unilever):
    """Caps at 2.35 for 10,000, 2.10 for 50,000."""
    q = services.save(
        executive,
        None,
        customer=unilever,
        division=Division.objects.get(code="IM"),
        lines=[
            QuoteLine(
                description="Cap, PP, white",
                quantity="10000",
                unit_price="2.35",
                breaks=[BreakInput("50000", "2.10")],
            )
        ],
    )
    workflow.submit(executive, q)
    workflow.approve(director, q)
    return workflow.record_outcome(executive, q, accepted=True, reason="price")


@pytest.fixture
def from_quote(executive, won):
    return orders.from_quotation(executive, won)


def call_offs(order, *deliveries, quantity=None):
    """The order's first line at `quantity`, called off on the given (days, quantity)."""
    line = order.lines.get(line_no=1)
    return [
        LineInput(
            quantity=quantity or line.quantity,
            quotation_line=line.quotation_line,
            schedule=[Delivery(TODAY + timedelta(days=d), q) for d, q in deliveries],
        )
    ]


# --- Making orders ---------------------------------------------------------------------


def test_an_order_from_an_accepted_quotation(from_quote, won):
    assert from_quote.number == f"SO{TODAY:%y%m%d}01"
    assert (from_quote.source, from_quote.status, from_quote.quotation) == (
        "quotation",
        S.DRAFT,
        won,
    )
    assert from_quote.delivery_address == "Grandpass, Colombo 14"
    line = from_quote.lines.get()
    assert (line.quantity, line.unit_price) == (Decimal("10000.000"), Decimal("2.35"))
    assert [(d.due_date, d.quantity) for d in line.schedule.all()] == [(TODAY, line.quantity)]
    assert from_quote.total_amount == won.total_amount


def test_only_an_accepted_quotation(executive, director, unilever):
    q = services.save(
        executive,
        None,
        customer=unilever,
        division=Division.objects.get(code="WS"),
        lines=[QuoteLine(description="Shaft", quantity="1", unit_price="100")],
    )
    with pytest.raises(SalesError, match="mark it won first"):
        orders.from_quotation(executive, q)


def test_one_click_from_an_issued_proforma(executive, won):
    proforma = proformas.create(executive, won)
    with pytest.raises(SalesError, match="issued proforma"):
        orders.from_proforma(executive, proforma)
    proformas.save(
        executive,
        proforma,
        lines=[proformas.LineInput(won.lines.get(), "60000")],
        customer_po="UL/PO/7781",
    )
    proforma = proformas.issue(executive, proforma)
    order = orders.from_proforma(executive, proforma)
    assert (order.source, order.proforma, order.quotation) == ("proforma", proforma, won)
    assert order.customer_po == "UL/PO/7781"
    line = order.lines.get()
    assert (line.quantity, line.unit_price) == (Decimal("60000.000"), Decimal("2.10"))


# --- Delivery schedule (moulding call-offs) ----------------------------------------------


def test_call_offs_add_up_to_the_line(from_quote, executive):
    order = orders.save(
        executive,
        from_quote,
        lines=call_offs(from_quote, (7, "20000"), (37, "20000"), (67, "20000"), quantity="60000"),
        customer_po="UL/PO/7781",
    )
    line = order.lines.get()
    assert line.unit_price == Decimal("2.10")  # the 50,000 price applies to 60,000
    assert [d.quantity for d in line.schedule.all()] == [Decimal("20000.000")] * 3
    with pytest.raises(SalesError, match="add up to 50000, not the line's 60000"):
        orders.save(
            executive,
            order,
            lines=call_offs(order, (7, "25000"), (37, "25000"), quantity="60000"),
        )
    with pytest.raises(SalesError, match="delivery date"):
        orders.save(executive, order, lines=call_offs(order))


# --- Confirming, completing, cancelling ----------------------------------------------------


def test_confirming_needs_the_customers_po_and_then_nothing_changes(from_quote, executive):
    with pytest.raises(SalesError, match="customer's PO number"):
        orders.confirm(executive, from_quote)
    orders.save(executive, from_quote, lines=call_offs(from_quote, (14, "10000")), customer_po="P1")
    order = orders.confirm(executive, from_quote)
    assert order.status == S.OPEN and order.confirmed_at is not None
    with pytest.raises(SalesError, match="Only the person who made a draft"):
        orders.save(executive, order, lines=call_offs(order, (14, "10000")))
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        SalesOrder.objects.filter(pk=order.pk).update(customer_po="OTHER")
    with pytest.raises(DatabaseError, match="cannot change"), transaction.atomic():
        DeliverySchedule.objects.filter(line__order=order).update(quantity=Decimal("1"))
    assert JournalEntry.objects.count() == 0  # an order is not a sale yet


def test_completed_and_cancelled(from_quote, executive):
    orders.save(executive, from_quote, lines=call_offs(from_quote, (14, "10000")), customer_po="P1")
    order = orders.confirm(executive, from_quote)
    with pytest.raises(SalesError, match="Give a reason"):
        orders.cancel(executive, order, "")
    done = orders.complete(executive, order)
    assert done.status == S.COMPLETED
    with pytest.raises(SalesError, match="draft or open"):
        orders.cancel(executive, done, "Too late")
    with pytest.raises(DatabaseError, match="for good"), transaction.atomic():
        SalesOrder.objects.filter(pk=done.pk).update(status=S.OPEN)


def test_an_order_with_an_advance_is_not_cancelled(from_quote, executive, unilever):
    orders.save(executive, from_quote, lines=call_offs(from_quote, (14, "10000")), customer_po="P1")
    order = orders.confirm(executive, from_quote)
    accountant = person("accountant@sml.lk", "accountant", all_divisions=True)
    cashier = person("cashier@sml.lk", "cashier", all_divisions=True)
    ledger = chart.create_account(
        accountant,
        name="Bank",
        account_type="bank",
        detail_type=DetailType.objects.get(name="Current account"),
        number="1030",
    )
    bank = banking.create_account(
        accountant,
        code="bank",
        kind="current",
        name="Bank",
        bank_name="HNB",
        account_number="1000123456",
        ledger_account=ledger.pk,
    )
    advance = advances.record(
        cashier,
        customer=unilever,
        account=bank,
        method="transfer",
        amount="10000",
        receipt_date=TODAY,
        reference="CEFT 3",
        sales_order=order,
    )
    assert (advance.sales_order, advance.quotation, advance.division) == (
        order,
        order.quotation,
        order.division,
    )
    advances.approve(accountant, advance)
    with pytest.raises(SalesError, match="advance has been received"):
        orders.cancel(executive, order, "Customer cancelled")


# --- Repeat orders typed in: the Director approves -----------------------------------------


def repeat(executive, unilever, **extra):
    return orders.direct(
        executive,
        customer=unilever,
        division=Division.objects.get(code="IM"),
        lines=[
            LineInput(
                quantity="20000",
                description="Cap, PP, white (repeat)",
                unit_price="2.30",
                schedule=[Delivery(TODAY + timedelta(days=10), "20000")],
            )
        ],
        customer_po="UL/PO/8001",
        **extra,
    )


def test_a_repeat_order_goes_to_the_director(executive, director, unilever):
    order = repeat(executive, unilever, discount_pct="2")
    assert (order.source, order.discount_pct) == ("direct", Decimal("2.00"))
    assert order.subtotal == Decimal("45080.00")  # 20,000 × 2.30 less 2%
    order = orders.confirm(executive, order)
    assert order.status == S.AWAITING_APPROVAL
    state = approvals.state_of("sales_order", order.pk)
    assert [step["role"] for step in state.route] == ["director"]
    assert Notification.objects.filter(user=director, event="approval_waiting").exists()
    order = orders.approve(director, order, "Same price as last time")
    assert order.status == S.OPEN


def test_a_returned_repeat_order_is_a_draft_again(executive, director, unilever):
    order = orders.confirm(executive, repeat(executive, unilever))
    with pytest.raises(SalesError, match="Give a reason"):
        orders.send_back(director, order, "")
    order = orders.send_back(director, order, "Price went up in October")
    assert order.status == S.DRAFT and orders.can_edit(executive, order)


def test_repeat_order_lines_are_checked(executive, unilever):
    with pytest.raises(SalesError, match="description is required"):
        orders.direct(
            executive,
            customer=unilever,
            division=Division.objects.get(code="IM"),
            lines=[LineInput(quantity="1", unit_price="1", schedule=[Delivery(TODAY, "1")])],
        )
    with pytest.raises(SalesError, match="production division"):
        orders.direct(
            executive,
            customer=unilever,
            division=Division.objects.get(code="HO"),
            lines=[LineInput(quantity="1", description="X", unit_price="1")],
        )


# --- Through the API -----------------------------------------------------------------------


def test_the_api_makes_confirms_and_lists_orders(executive, won, director):
    client = as_user(executive)
    made = client.post("/api/v1/sales-orders/", {"quotation": won.pk}, format="json")
    assert made.status_code == 201, made.json()
    body = made.json()
    url = f"/api/v1/sales-orders/{body['id']}/"
    line = body["lines"][0]
    changed = client.put(
        url,
        {
            "customer_po": "UL/PO/7781",
            "lines": [
                {
                    "quotation_line": line["quotation_line"],
                    "quantity": "10000",
                    "schedule": [
                        {"due_date": str(TODAY + timedelta(days=7)), "quantity": "4000"},
                        {"due_date": str(TODAY + timedelta(days=21)), "quantity": "6000"},
                    ],
                }
            ],
        },
        format="json",
    )
    assert changed.status_code == 200, changed.json()
    assert len(changed.json()["lines"][0]["schedule"]) == 2
    opened = client.post(f"{url}confirm/", {}, format="json").json()
    assert opened["status"] == "open"
    assert opened["next_delivery"] == str(TODAY + timedelta(days=7))
    quote = client.get(f"/api/v1/quotations/{won.pk}/").json()
    assert [o["number"] for o in quote["sales_orders"]] == [body["number"]]
    listing = as_user(director).get("/api/v1/sales-orders/?status=open").json()
    assert [row["number"] for row in listing] == [body["number"]]


def test_the_api_takes_a_repeat_order(executive, unilever):
    answer = as_user(executive).post(
        "/api/v1/sales-orders/",
        {
            "customer": unilever.pk,
            "division": "IM",
            "customer_po": "UL/PO/8001",
            "lines": [
                {
                    "description": "Cap, PP, white",
                    "quantity": "1000",
                    "unit_price": "2.30",
                    "schedule": [{"due_date": str(TODAY), "quantity": "1000"}],
                }
            ],
        },
        format="json",
    )
    assert answer.status_code == 201, answer.json()
    assert (answer.json()["source"], answer.json()["total_amount"]) == ("direct", "2300.00")


def test_who_cancelled_and_when_is_kept(from_quote, executive):
    # Owner, 16 Nov 2026: "mention who cancelled the sales order".
    orders.save(executive, from_quote, lines=call_offs(from_quote, (14, "10000")), customer_po="P1")
    order = orders.confirm(executive, from_quote)
    before = timezone.now()
    cancelled = orders.cancel(executive, order, "Wrong quantity")
    assert cancelled.cancelled_by_id == executive.pk and cancelled.cancelled_at >= before
    row = next(
        r for r in as_user(executive).get("/api/v1/sales-orders/").json() if r["id"] == order.pk
    )
    assert row["cancelled_by"] == executive.full_name
    page = as_user(executive).get(f"/api/v1/sales-orders/{order.pk}/").json()
    assert (page["cancelled_by"], page["cancel_reason"]) == (executive.full_name, "Wrong quantity")
    assert page["cancelled_at"] is not None
    # Once kept, who and when cannot be changed.
    other = person("other@sml.lk", "sales_executive", all_divisions=True)
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        SalesOrder.objects.filter(pk=order.pk).update(cancelled_by=other)
    with pytest.raises(DatabaseError, match="cannot be changed"), transaction.atomic():
        SalesOrder.objects.filter(pk=order.pk).update(cancelled_at=before)


# --- A repeat order linked to an earlier quotation (owner, 16 Nov 2026) ---------------------


def test_a_repeat_order_can_be_linked_to_an_expired_quotation(executive, director, unilever):
    old = services.save(
        executive,
        None,
        customer=unilever,
        division=Division.objects.get(code="IM"),
        lines=[QuoteLine(description="Cap, PP, white", quantity="10000", unit_price="2.35")],
    )
    workflow.submit(executive, old)
    workflow.approve(director, old)
    assert workflow.expire_due(old.valid_until + timedelta(days=1)) == 1
    old.refresh_from_db()
    won = old
    order = repeat(executive, unilever, linked_quotation=won)
    assert (order.source, order.quotation_id) == ("direct", won.pk)
    assert orders.quotation_expired(order)
    # It stays a typed-in repeat order: no quotation lines are offered.
    detail = as_user(executive).get(f"/api/v1/sales-orders/{order.pk}/").json()
    assert detail["quotation"]["expired"] is True
    assert detail["quotation_lines"] == []


def test_only_this_customers_sent_quotations_can_be_linked(executive, director, won, unilever):
    other = customers.create_customer(executive, {"name": "Elephant House"})
    with pytest.raises(SalesError, match="customer's quotations"):
        orders.direct(
            executive,
            customer=other,
            division=Division.objects.get(code="IM"),
            lines=[
                LineInput(
                    quantity="1", description="X", unit_price="1", schedule=[Delivery(TODAY, "1")]
                )
            ],
            linked_quotation=won,
        )
    draft = services.save(
        executive,
        None,
        customer=unilever,
        division=Division.objects.get(code="IM"),
        lines=[QuoteLine(description="Lid", quantity="100", unit_price="1.00")],
    )
    with pytest.raises(SalesError, match="customer's quotations"):
        repeat(executive, unilever, linked_quotation=draft)


def test_an_order_from_a_quotation_keeps_its_quotation(from_quote, executive, won):
    line = from_quote.lines.get()
    kept = orders.save(
        executive,
        from_quote,
        lines=[
            LineInput(
                quantity="10000",
                quotation_line=line.quotation_line,
                schedule=[Delivery(TODAY, "10000")],
            )
        ],
        linked_quotation=None,
    )
    assert kept.quotation_id == won.pk


def test_the_api_links_and_unlinks_a_repeat_order(executive, won, unilever):
    client = as_user(executive)
    line = {
        "description": "Cap, PP, white",
        "quantity": "1000",
        "unit_price": "2.30",
        "schedule": [{"due_date": str(TODAY), "quantity": "1000"}],
    }
    made = client.post(
        "/api/v1/sales-orders/",
        {"customer": unilever.pk, "division": "IM", "linked_quotation": won.pk, "lines": [line]},
        format="json",
    )
    assert made.status_code == 201, made.json()
    body = made.json()
    assert body["quotation"]["id"] == won.pk and body["quotation"]["expired"] is False
    url = f"/api/v1/sales-orders/{body['id']}/"
    cleared = client.put(url, {"linked_quotation": None, "lines": [line]}, format="json")
    assert cleared.status_code == 200, cleared.json()
    assert cleared.json()["quotation"] is None
    kept = client.put(url, {"lines": [line]}, format="json").json()
    assert kept["quotation"] is None
    wrong = client.put(url, {"linked_quotation": 999999, "lines": [line]}, format="json")
    assert wrong.status_code == 400


# Owner, 16 Nov 2026: clear statuses ("Waiting for Ruwan (Director)", "Returned by Ruwan").
def test_the_list_and_page_say_who_a_repeat_order_waits_for(executive, director, unilever):
    order = orders.confirm(executive, repeat(executive, unilever))
    client = as_user(executive)
    row = next(r for r in client.get("/api/v1/sales-orders/").json() if r["id"] == order.pk)
    assert row["people"]["waiting"] == {"person": director.full_name, "role": "Director"}
    orders.send_back(director, order, "Price went up in October")
    page = client.get(f"/api/v1/sales-orders/{order.pk}/").json()
    assert page["people"] == {
        "waiting": None,
        "last": {"action": "return", "by": director.full_name},
    }
