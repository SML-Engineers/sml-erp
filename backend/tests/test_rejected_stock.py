# ruff: noqa: F811 (pytest fixtures imported from test_supplier_returns)
"""Rejected goods waiting to go back to the supplier (owner, 22 Nov 2026, from his testing:
return within 14 days, with a list and a reminder of anything waiting longer)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.core.models import Notification
from apps.inventory import rejected
from apps.purchasing import returns

from .test_access import as_user, person
from .test_supplier_returns import (  # noqa: F401
    buyer,
    director,
    give_back,
    inspect,
    line,
    lot,
    memory_storage,
    qc,
    stores,
)

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
URL = "/api/v1/purchasing-reports/rejected-stock/"


@pytest.fixture
def later(monkeypatch):
    """Move "today" forward for the list and the reminder."""

    def move(days):
        class Clock:
            @staticmethod
            def localdate():
                return TODAY + timedelta(days=days)

        monkeypatch.setattr(rejected, "timezone", Clock)

    return move


def test_rejected_goods_are_listed_with_the_days_they_have_waited(stores, qc, line, later):
    inspect(qc, line, accepted="80")  # 20 rejected
    later(15)
    rows = as_user(stores).get(URL).json()
    assert len(rows) == 1
    row = rows[0]
    assert (row["store"], row["lot_no"], row["quantity"], row["unit"]) == (
        "IM-REJ",
        lot(line),
        "20",
        "pcs",
    )
    assert (row["since"], row["days"], row["over"]) == (TODAY.isoformat(), 15, True)
    assert (row["grn"], row["supplier"]) == (line.receipt.number, "Inserts Lanka")


def test_14_days_is_still_within_the_target(stores, qc, line, later):
    inspect(qc, line, accepted="80")
    later(14)
    row = as_user(stores).get(URL).json()[0]
    assert (row["days"], row["over"]) == (14, False)
    assert as_user(stores).get(URL + "?over=1").json() == []


def test_goods_returned_to_the_supplier_leave_the_list(stores, qc, line):
    inspect(qc, line, accepted="80")
    returns.confirm(stores, give_back(stores, line, "rejected", "15"))
    assert as_user(stores).get(URL).json()[0]["quantity"] == "5"  # the rest still waits
    returns.confirm(stores, give_back(stores, line, "rejected", "5"))
    assert as_user(stores).get(URL).json() == []


def test_accepted_goods_are_not_listed(stores, qc, line):
    inspect(qc, line, accepted="100")
    assert as_user(stores).get(URL).json() == []


def test_people_outside_the_division_or_purchasing_see_nothing(stores, qc, line):
    inspect(qc, line, accepted="80")
    workshop = person("ws-stores@sml.lk", "store_supervisor", divisions=("WS",))
    assert as_user(workshop).get(URL).json() == []
    sales = person("sales@sml.lk", "sales_executive", divisions=("IM",))
    assert as_user(sales).get(URL).status_code == 403


def test_the_list_downloads_as_excel(stores, qc, line):
    inspect(qc, line, accepted="80")
    response = as_user(stores).get(URL + "?export=xlsx")
    assert response.status_code == 200
    assert "spreadsheet" in response["Content-Type"]


def test_the_stores_person_and_purchasing_are_told_once_after_14_days(
    stores, qc, buyer, line, later
):
    inspect(qc, line, accepted="80")
    later(14)
    assert rejected.remind() == 0
    later(15)
    assert rejected.remind() == 1
    told = Notification.objects.filter(event="rejected_stock_waiting")
    assert {n.user.email for n in told} >= {"stores@sml.lk", "buyer@sml.lk"}
    note = told.first()
    assert note.title == f"M8-INSERT lot {lot(line)} has waited over 14 days in IM-REJ"
    assert "20 pcs of Insert" in note.body and line.receipt.number in note.body
    assert note.link == "/purchasing/reports?tab=rejected"
    later(16)
    assert rejected.remind() == 0  # once per lot
    assert Notification.objects.filter(event="rejected_stock_waiting").count() == told.count()


def test_nobody_is_told_about_goods_already_returned(stores, qc, line, later):
    inspect(qc, line, accepted="80")
    returns.confirm(stores, give_back(stores, line, "rejected", "20"))
    later(30)
    assert rejected.remind() == 0
