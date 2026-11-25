"""Bought-out parts on their own inventory account, 1215 (owner, 22 Nov 2026, from his
testing: not 1210 Raw materials)."""

import importlib

import pytest
from django.apps import apps as django_apps

from apps.accounting.models import Account, JournalLine
from apps.inventory import items, receipts

from .test_access import person
from .test_stock import approved_po, inspect

pytestmark = pytest.mark.django_db

PART = {
    "code": "M8-INSERT",
    "name": "M8 brass insert",
    "category": "bought_out",
    "unit": "pcs",
}


def received(buyer, director, stores, item, qty, price):
    order = approved_po(buyer, director, item, qty, price)
    return receipts.confirm(stores, receipts.create(stores, order)).lines.get()


@pytest.fixture
def accountant():
    return person("accountant@sml.lk", "accountant", all_divisions=True)


@pytest.fixture
def buyer():
    return person("buyer@sml.lk", "purchasing_officer", all_divisions=True)


@pytest.fixture
def director():
    return person("director@sml.lk", "director", all_divisions=True)


@pytest.fixture
def stores():
    return person("stores@sml.lk", "store_supervisor", divisions=("IM",))


@pytest.fixture
def qc():
    return person("qc@sml.lk", "qc_inspector", divisions=("IM",))


def test_the_account_is_an_inventory_account_under_1200():
    account = Account.objects.get(number="1215")
    assert account.name == "Bought-out parts"
    assert account.account_type == "other_current_asset"
    assert account.parent.number == "1200"
    assert account.is_active


def test_a_new_bought_out_part_goes_to_1215_and_a_raw_material_stays_on_1210(buyer):
    part = items.create_item(buyer, PART)
    resin = items.create_item(
        buyer, {"code": "PP-H", "name": "PP", "category": "raw_material", "unit": "kg"}
    )
    assert part.inventory_account.number == "1215"
    assert resin.inventory_account.number == "1210"


def test_accepted_bought_out_parts_are_valued_on_1215(buyer, director, stores, qc):
    part = items.create_item(buyer, PART)
    inspect(qc, received(buyer, director, stores, part, "50", "12.50"))
    posted = JournalLine.objects.filter(account__number="1215")
    assert posted.count() == 1 and posted.get().debit == 625  # 50 pcs × 12.50
    assert not JournalLine.objects.filter(account__number="1210").exists()


def test_the_migration_moves_only_unused_bought_out_parts(buyer, director, stores, accountant):
    unused = items.create_item(buyer, PART)
    used = items.create_item(buyer, {**PART, "code": "M6-INSERT", "name": "M6 brass insert"})
    resin = items.create_item(
        buyer, {"code": "PP-H", "name": "PP", "category": "raw_material", "unit": "kg"}
    )
    for item in (unused, used):
        items.update_item(accountant, item, {"inventory_account": "1210"})
    received(buyer, director, stores, used, "10", "10")  # in quarantine: a movement

    importlib.import_module("apps.inventory.migrations.0015_bought_out_on_1215").move(
        django_apps, None
    )

    for item in (unused, used, resin):
        item.refresh_from_db()
    assert unused.inventory_account.number == "1215"
    assert used.inventory_account.number == "1210"  # has stock valued on 1210: stays
    assert resin.inventory_account.number == "1210"  # not a bought-out part
