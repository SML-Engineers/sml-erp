import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Month-end revaluation (backlog P2-21): a new system account, Unrealised exchange gain or
# loss (8020, other expense), and the months revalued with their lines. A posted month and its
# lines never change (database guard).

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
]
ROLE, NUMBER, NAME, TYPE = (
    "unrealised_exchange",
    "8020",
    "Unrealised exchange gain or loss",
    "other_expense",
)


def add(apps, schema_editor):
    DetailType = apps.get_model("accounting", "DetailType")
    Account = apps.get_model("accounting", "Account")
    if not Account.objects.exists() or Account.objects.filter(system_role=ROLE).exists():
        return
    found = (
        Account.objects.filter(number=NUMBER, account_type=TYPE, system_role="", is_active=True)
        .first()
        or Account.objects.filter(name=NAME, account_type=TYPE, system_role="", is_active=True)
        .first()
    )
    if found is not None:
        # Accounts created before leave deferred checks pending; run them first, as the table
        # cannot be altered while they wait.
        schema_editor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        schema_editor.execute(
            "ALTER TABLE accounting_account DISABLE TRIGGER accounting_account_guard"
        )
        Account.objects.filter(pk=found.pk).update(system_role=ROLE)
        schema_editor.execute("ALTER TABLE accounting_account ENABLE TRIGGER accounting_account_guard")
        schema_editor.execute("SET CONSTRAINTS ALL DEFERRED")
        return
    detail, _ = DetailType.objects.get_or_create(account_type=TYPE, name=NAME)
    Account.objects.create(
        number=NUMBER if not Account.objects.filter(number=NUMBER).exists() else "",
        name=NAME,
        account_type=TYPE,
        detail_type=detail,
        parent=Account.objects.filter(number="8000", account_type=TYPE).first(),
        system_role=ROLE,
    )


FORWARD = """
CREATE OR REPLACE FUNCTION accounting_revaluation_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.status = 'posted' THEN
    RAISE EXCEPTION 'The revaluation of % is posted and never changes', OLD.month_end
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_revaluation_guard
BEFORE UPDATE OR DELETE ON accounting_revaluation
FOR EACH ROW EXECUTE FUNCTION accounting_revaluation_guard();

CREATE OR REPLACE FUNCTION accounting_revaluation_line_guard() RETURNS trigger AS $$
DECLARE
  run_status text;
BEGIN
  SELECT status INTO run_status FROM accounting_revaluation
    WHERE id = COALESCE(NEW.revaluation_id, OLD.revaluation_id);
  IF run_status = 'posted' THEN
    RAISE EXCEPTION 'The lines of a posted revaluation never change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_revaluation_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON accounting_revaluationline
FOR EACH ROW EXECUTE FUNCTION accounting_revaluation_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS accounting_revaluation_line_guard ON accounting_revaluationline;
DROP FUNCTION IF EXISTS accounting_revaluation_line_guard();
DROP TRIGGER IF EXISTS accounting_revaluation_guard ON accounting_revaluation;
DROP FUNCTION IF EXISTS accounting_revaluation_guard();
"""


def _money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0015_stock_roles"),
        ("core", "0025_credit_terms_action"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="account",
            name="system_role",
            field=models.CharField(blank=True, choices=ROLES, max_length=30),
        ),
        migrations.RunPython(add, migrations.RunPython.noop),
        migrations.CreateModel(
            name="Revaluation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("month_end", models.DateField(unique=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("draft", "Worked out, to check"), ("posted", "Posted")],
                        default="draft",
                        max_length=10,
                    ),
                ),
                ("open_items_total", _money(default=0)),
                ("balances_total", _money(default=0)),
                ("prepared_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("posted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "journal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.journalentry",
                    ),
                ),
                (
                    "reversal_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.journalentry",
                    ),
                ),
                (
                    "balances_entry",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.journalentry",
                    ),
                ),
                (
                    "prepared_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "posted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-month_end"]},
        ),
        migrations.CreateModel(
            name="RevaluationLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("receivable", "Customer invoice"),
                            ("payable", "Supplier invoice"),
                            ("balance", "Bank or cash balance"),
                        ],
                        max_length=12,
                    ),
                ),
                ("document", models.CharField(max_length=60)),
                ("link", models.CharField(blank=True, max_length=100)),
                ("open_amount", _money()),
                ("carried_lkr", _money()),
                ("rate", models.DecimalField(decimal_places=6, max_digits=18)),
                ("rate_date", models.DateField()),
                ("revalued_lkr", _money()),
                ("difference", _money()),
                ("balance_from", models.CharField(blank=True, max_length=100)),
                (
                    "revaluation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="accounting.revaluation",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="masters.customer",
                    ),
                ),
                (
                    "supplier",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="masters.supplier",
                    ),
                ),
                (
                    "company_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="masters.companyaccount",
                    ),
                ),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.division",
                    ),
                ),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="masters.currency",
                    ),
                ),
            ],
            options={"ordering": ["revaluation", "kind", "document", "id"]},
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
