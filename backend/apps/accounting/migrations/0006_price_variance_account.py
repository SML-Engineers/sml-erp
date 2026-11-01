from django.db import migrations, models

# Purchase price variance (backlog P16-10): when the Director approves a supplier invoice
# whose price or tax differs from the PO, the difference is posted here (5060, under 5000
# Cost of sales), not to inventory, so the stock value stays at the PO price.

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
    ("price_variance", "Purchase price variance"),
]
NAME = "Purchase price variance"


def add(apps, schema_editor):
    DetailType = apps.get_model("accounting", "DetailType")
    Account = apps.get_model("accounting", "Account")
    detail, _ = DetailType.objects.get_or_create(account_type="cost_of_goods_sold", name=NAME)
    if not Account.objects.exists() or Account.objects.filter(system_role="price_variance").exists():
        return
    number = "5060" if not Account.objects.filter(number="5060").exists() else ""
    Account.objects.create(
        number=number,
        name=NAME,
        account_type="cost_of_goods_sold",
        detail_type=detail,
        parent=Account.objects.filter(number="5000", account_type="cost_of_goods_sold").first(),
        system_role="price_variance",
    )


class Migration(migrations.Migration):
    dependencies = [("accounting", "0005_grni_account")]

    operations = [
        migrations.AlterField(
            model_name="account",
            name="system_role",
            field=models.CharField(blank=True, choices=ROLES, max_length=30),
        ),
        migrations.RunPython(add, migrations.RunPython.noop),
    ]
