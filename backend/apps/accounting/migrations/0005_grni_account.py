from django.db import migrations, models

# Goods received not invoiced (backlog P16-09, spec 5A.3): accepted goods are posted
# Dr Inventory, Cr GRNI at the PO price; matching the supplier's invoice (P16-10) clears it.
# The account is added to an existing chart as 2190, a system account.

ROLES = [
    ("accounts_receivable", "Accounts receivable"),
    ("accounts_payable", "Accounts payable"),
    ("retained_earnings", "Retained earnings"),
    ("opening_balance_equity", "Opening balance equity"),
    ("undeposited_funds", "Undeposited funds"),
    ("customer_advances", "Customer advances"),
    ("vat_payable", "VAT payable"),
    ("vat_receivable", "VAT receivable"),
    ("grni", "Goods received not invoiced"),
]
NAME = "Goods received not invoiced"


def add(apps, schema_editor):
    DetailType = apps.get_model("accounting", "DetailType")
    Account = apps.get_model("accounting", "Account")
    detail, _ = DetailType.objects.get_or_create(account_type="other_current_liability", name=NAME)
    if not Account.objects.exists() or Account.objects.filter(system_role="grni").exists():
        return
    number = "2190" if not Account.objects.filter(number="2190").exists() else ""
    Account.objects.create(
        number=number,
        name=NAME,
        account_type="other_current_liability",
        detail_type=detail,
        system_role="grni",
    )


class Migration(migrations.Migration):
    dependencies = [("accounting", "0004_taxes")]

    operations = [
        migrations.AlterField(
            model_name="account",
            name="system_role",
            field=models.CharField(blank=True, choices=ROLES, max_length=30),
        ),
        migrations.RunPython(add, migrations.RunPython.noop),
    ]
