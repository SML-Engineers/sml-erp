from django.db import migrations

# Bought-out parts get their own inventory account, 1215 under 1200 Inventory, instead of
# sharing 1210 Raw materials (owner, 22 Nov 2026, from his testing). The starter chart
# (catalogue STARTER_CHART_V1, migration 0002) is left as it was; this adds the account
# wherever a chart exists. The Accountant can rename it like any other account.

NUMBER, NAME, KIND, PARENT = "1215", "Bought-out parts", "other_current_asset", "1200"


def add(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    DetailType = apps.get_model("accounting", "DetailType")
    if not Account.objects.exists() or Account.objects.filter(number=NUMBER).exists():
        return
    detail, _ = DetailType.objects.get_or_create(account_type=KIND, name=NAME)
    Account.objects.create(
        number=NUMBER,
        name=NAME,
        account_type=KIND,
        detail_type=detail,
        parent=Account.objects.filter(number=PARENT, account_type=KIND).first(),
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0026_wip_ledger"),
    ]

    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
