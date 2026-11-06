from django.db import migrations, models

# Gratuity (backlog P2B-19): the monthly provision, Dr Gratuity (6015, expense) Cr Provision
# for gratuity (2520, long-term liability); both new.
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
    ("unrealised_exchange", "Unrealised exchange gain or loss"),
    ("materials_used", "Raw materials used"),
    ("stock_adjustment", "Stock adjustments and write-offs"),
    ("work_in_progress", "Work in progress"),
    ("finished_goods", "Finished goods"),
    ("salaries_expense", "Salaries and wages"),
    ("epf_etf_expense", "EPF and ETF contributions"),
    ("epf_payable", "EPF payable"),
    ("etf_payable", "ETF payable"),
    ("apit_payable", "APIT payable"),
    ("salaries_payable", "Salaries payable"),
    ("payroll_deductions", "Payroll deductions payable"),
    ("staff_loans", "Staff loans and advances"),
    ("staff_loan_interest", "Interest from staff loans"),
    ("gratuity_expense", "Gratuity"),
    ("gratuity_provision", "Provision for gratuity"),
]

# role, number, name, account type, detail type
NEW = [
    ("gratuity_expense", "6015", "Gratuity", "expense", "Gratuity"),
    (
        "gratuity_provision",
        "2520",
        "Provision for gratuity",
        "long_term_liability",
        "Provision for gratuity",
    ),
]


def add(apps, schema_editor):
    DetailType = apps.get_model("accounting", "DetailType")
    Account = apps.get_model("accounting", "Account")
    if not Account.objects.exists():
        return
    for role, number, name, kind, detail_name in NEW:
        if Account.objects.filter(system_role=role).exists():
            continue
        found = (
            Account.objects.filter(
                number=number, account_type=kind, system_role="", is_active=True
            ).first()
            or Account.objects.filter(
                name=name, account_type=kind, system_role="", is_active=True
            ).first()
        )
        if found is not None:
            # The account guard refuses a change of system role; it is switched off for this
            # one update (as in 0016), with pending deferred checks run first.
            schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")
            schema_editor.execute(
                "ALTER TABLE accounting_account DISABLE TRIGGER accounting_account_guard"
            )
            Account.objects.filter(pk=found.pk).update(system_role=role)
            schema_editor.execute(
                "ALTER TABLE accounting_account ENABLE TRIGGER accounting_account_guard"
            )
            schema_editor.execute("SET CONSTRAINTS ALL DEFERRED")
            continue
        detail, _ = DetailType.objects.get_or_create(account_type=kind, name=detail_name)
        Account.objects.create(
            number=number if not Account.objects.filter(number=number).exists() else "",
            name=name,
            account_type=kind,
            detail_type=detail,
            system_role=role,
        )


class Migration(migrations.Migration):
    dependencies = [("accounting", "0023_staff_loan_roles")]

    operations = [
        migrations.AlterField(
            model_name="account",
            name="system_role",
            field=models.CharField(blank=True, choices=ROLES, max_length=30),
        ),
        migrations.RunPython(add, migrations.RunPython.noop),
    ]
