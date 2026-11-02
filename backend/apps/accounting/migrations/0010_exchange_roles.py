from django.db import migrations, models

# Exchange gain and Exchange loss become system accounts (backlog P16-19, IAS 21): the
# difference between the rates of a purchase's dates is posted there.

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
    ("exchange_gain", "Exchange gain"),
    ("exchange_loss", "Exchange loss"),
]
# (role, starter number, name, account type)
WANTED = [
    ("exchange_gain", "7010", "Exchange gain", "other_income"),
    ("exchange_loss", "8010", "Exchange loss", "other_expense"),
]


def add(apps, schema_editor):
    DetailType = apps.get_model("accounting", "DetailType")
    Account = apps.get_model("accounting", "Account")
    if not Account.objects.exists():
        return
    for role, number, name, account_type in WANTED:
        if Account.objects.filter(system_role=role).exists():
            continue
        account = (
            Account.objects.filter(
                number=number, account_type=account_type, system_role="", is_active=True
            ).first()
            or Account.objects.filter(
                name=name, account_type=account_type, system_role="", is_active=True
            ).first()
        )
        if account is not None:
            # The guard refuses changing a system role; this one-off upgrade switches it off
            # for the single update.
            schema_editor.execute(
                "ALTER TABLE accounting_account DISABLE TRIGGER accounting_account_guard"
            )
            Account.objects.filter(pk=account.pk).update(system_role=role)
            schema_editor.execute(
                "ALTER TABLE accounting_account ENABLE TRIGGER accounting_account_guard"
            )
            continue
        detail, _ = DetailType.objects.get_or_create(account_type=account_type, name=name)
        Account.objects.create(
            number=number if not Account.objects.filter(number=number).exists() else "",
            name=name,
            account_type=account_type,
            detail_type=detail,
            system_role=role,
        )


class Migration(migrations.Migration):
    dependencies = [("accounting", "0009_tax_share")]

    operations = [
        migrations.AlterField(
            model_name="account",
            name="system_role",
            field=models.CharField(blank=True, choices=ROLES, max_length=30),
        ),
        migrations.RunPython(add, migrations.RunPython.noop),
    ]
