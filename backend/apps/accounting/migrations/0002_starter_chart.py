from django.db import migrations

from apps.accounting.catalogue import DETAIL_TYPES_V1, STARTER_CHART_V1

# The starting detail types and the starter chart for a manufacturing company (spec 3),
# with the system accounts. The company accountant reviews and edits it before go-live.


def load(apps, schema_editor):
    DetailType = apps.get_model("accounting", "DetailType")
    Account = apps.get_model("accounting", "Account")
    for account_type, names in DETAIL_TYPES_V1.items():
        for name in names:
            DetailType.objects.get_or_create(account_type=account_type, name=name)
    if Account.objects.exists():
        return
    by_number = {}
    for number, name, parent, account_type, detail, role in STARTER_CHART_V1:
        by_number[number] = Account.objects.create(
            number=number,
            name=name,
            parent=by_number[parent] if parent else None,
            account_type=account_type,
            detail_type=DetailType.objects.get(account_type=account_type, name=detail),
            system_role=role,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
    ]
