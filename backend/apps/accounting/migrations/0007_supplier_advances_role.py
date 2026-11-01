from django.db import migrations, models

# Advances to suppliers becomes a system account (backlog P16-11a): advance payments on a
# purchase order are posted there and set off against the supplier's invoice.

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
    ("supplier_advances", "Advances to suppliers"),
]
NAME = "Advances to suppliers"


def add(apps, schema_editor):
    DetailType = apps.get_model("accounting", "DetailType")
    Account = apps.get_model("accounting", "Account")
    if not Account.objects.exists() or Account.objects.filter(system_role="supplier_advances").exists():
        return
    account = Account.objects.filter(
        number="1320", account_type="other_current_asset", system_role="", is_active=True
    ).first()
    if account is None:
        account = Account.objects.filter(
            name=NAME, account_type="other_current_asset", system_role="", is_active=True
        ).first()
    if account is not None:
        # The guard refuses changing a system role; this one-off upgrade switches it off for
        # the single update.
        schema_editor.execute("ALTER TABLE accounting_account DISABLE TRIGGER accounting_account_guard")
        Account.objects.filter(pk=account.pk).update(system_role="supplier_advances")
        schema_editor.execute("ALTER TABLE accounting_account ENABLE TRIGGER accounting_account_guard")
        return
    detail, _ = DetailType.objects.get_or_create(account_type="other_current_asset", name=NAME)
    number = "1320" if not Account.objects.filter(number="1320").exists() else ""
    Account.objects.create(
        number=number,
        name=NAME,
        account_type="other_current_asset",
        detail_type=detail,
        system_role="supplier_advances",
    )


class Migration(migrations.Migration):
    dependencies = [("accounting", "0006_price_variance_account")]

    operations = [
        migrations.AlterField(
            model_name="account",
            name="system_role",
            field=models.CharField(blank=True, choices=ROLES, max_length=30),
        ),
        migrations.RunPython(add, migrations.RunPython.noop),
    ]
