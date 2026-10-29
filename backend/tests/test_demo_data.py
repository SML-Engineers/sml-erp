"""Demo data for trying the ERP (backlog P1-12): loads through the normal services, never on
production, once only."""

import io
import re

import pytest
from django.core.management import CommandError, call_command

from apps.core import crypto
from apps.core.models import User
from apps.payments.models import SupplierPayment
from apps.vouchers.models import Voucher

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def memory_storage(settings):
    settings.STORAGES = {
        **settings.STORAGES,
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


def test_demo_data_covers_every_stage(settings, monkeypatch):
    settings.DEBUG = True
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    out = io.StringIO()
    call_command("load_demo_data", stdout=out)
    text = out.getvalue()

    people = User.objects.filter(email__endswith="@demo.sml.lk")
    assert sorted(people.values_list("email", flat=True)) == [
        "accountant@demo.sml.lk",
        "cashier@demo.sml.lk",
        "clerk@demo.sml.lk",
        "director@demo.sml.lk",
    ]
    secret = re.search(r"Key: ([A-Z2-7]{32})", text).group(1)
    assert {crypto.decrypt(u.totp_secret_encrypted) for u in people} == {secret}
    assert all(u.check_password("Demo-SML-2026!") for u in people)

    statuses = sorted(Voucher.objects.values_list("status", flat=True))
    assert statuses == sorted(
        [
            "draft",
            "submitted",
            "submitted",
            "returned",
            "accountant_approved",
            "director_approved",
            "partly_paid",
            "paid",
        ]
    )
    assert SupplierPayment.objects.count() == 2
    assert all(v.attachments.exists() for v in Voucher.objects.exclude(status="draft"))
    with pytest.raises(CommandError, match="already loaded"):
        call_command("load_demo_data", stdout=io.StringIO())


def test_never_on_production(settings, monkeypatch):
    settings.DEBUG = False
    monkeypatch.setenv("APP_ENVIRONMENT", "production")
    with pytest.raises(CommandError, match="never production"):
        call_command("load_demo_data", stdout=io.StringIO())
    monkeypatch.delenv("APP_ENVIRONMENT")
    with pytest.raises(CommandError, match="never production"):
        call_command("load_demo_data", stdout=io.StringIO())
    assert not User.objects.filter(email__endswith="@demo.sml.lk").exists()
