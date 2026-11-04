from django.db import migrations, models

# Stock accounts (backlog P2-18): Raw materials used (5010) for material issued without an
# expense account of its own, a new Stock adjustments and write-offs (5070, under Cost of
# sales), and Work in progress (1220) and Finished goods (1230) marked for Phase 3.

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
    ("materials_used", "Raw materials used"),
    ("stock_adjustment", "Stock adjustments and write-offs"),
    ("work_in_progress", "Work in progress"),
    ("finished_goods", "Finished goods"),
]
# (role, starter number, name, account type, parent number)
WANTED = [
    ("materials_used", "5010", "Raw materials used", "cost_of_goods_sold", "5000"),
    ("stock_adjustment", "5070", "Stock adjustments and write-offs", "cost_of_goods_sold", "5000"),
    ("work_in_progress", "1220", "Work in progress", "other_current_asset", "1200"),
    ("finished_goods", "1230", "Finished goods", "other_current_asset", "1200"),
]


def add(apps, schema_editor):
    DetailType = apps.get_model("accounting", "DetailType")
    Account = apps.get_model("accounting", "Account")
    if not Account.objects.exists():
        return
    for role, number, name, account_type, parent in WANTED:
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
            # Accounts created above leave deferred checks pending; run them first, as the
            # table cannot be altered while they wait.
            schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            schema_editor.execute(
                "ALTER TABLE accounting_account DISABLE TRIGGER accounting_account_guard"
            )
            Account.objects.filter(pk=account.pk).update(system_role=role)
            schema_editor.execute(
                "ALTER TABLE accounting_account ENABLE TRIGGER accounting_account_guard"
            )
            schema_editor.execute("SET CONSTRAINTS ALL DEFERRED")
            continue
        detail, _ = DetailType.objects.get_or_create(account_type=account_type, name=name)
        Account.objects.create(
            number=number if not Account.objects.filter(number=number).exists() else "",
            name=name,
            account_type=account_type,
            detail_type=detail,
            parent=Account.objects.filter(number=parent, account_type=account_type).first(),
            system_role=role,
        )


class Migration(migrations.Migration):
    dependencies = [("accounting", "0014_zero_rated_code")]

    operations = [
        migrations.AlterField(
            model_name="account",
            name="system_role",
            field=models.CharField(blank=True, choices=ROLES, max_length=30),
        ),
        migrations.RunPython(add, migrations.RunPython.noop),
    ]
