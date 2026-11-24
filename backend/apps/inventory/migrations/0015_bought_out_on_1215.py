from django.db import migrations

# Bought-out part items still on 1210 Raw materials move to 1215 Bought-out parts (owner,
# 22 Nov 2026), but only those with no stock movement yet: an item with stock keeps its
# account, so the value already posted to 1210 and the stock stay in step. The Accountant
# can move such an item later with a stock adjustment.


def move(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    Item = apps.get_model("inventory", "Item")
    StockMovement = apps.get_model("inventory", "StockMovement")
    old = Account.objects.filter(number="1210").first()
    new = Account.objects.filter(number="1215", is_active=True).first()
    if old is None or new is None:
        return
    used = StockMovement.objects.values("item_id")
    Item.objects.filter(category="bought_out", inventory_account=old).exclude(pk__in=used).update(
        inventory_account=new
    )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0014_wip_ledger"),
        ("accounting", "0027_bought_out_parts_account"),
    ]

    operations = [migrations.RunPython(move, migrations.RunPython.noop)]
