import django.db.models.deletion
import django.db.models.functions.text
import django.utils.timezone
from django.db import migrations, models

# Chart of accounts (backlog P0-15). The database itself refuses:
# - deleting an account that has been used, or one the system needs (rule 9, spec 3);
# - changing the number of a used account once it has one (rule 9);
# - changing or removing a system account's role, type or active state;
# - undoing or redirecting a merge.

FORWARD = """
CREATE OR REPLACE FUNCTION accounting_account_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.first_used_at IS NOT NULL THEN
      RAISE EXCEPTION 'Account % has been used: it cannot be deleted, only made inactive',
        OLD.name USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.system_role <> '' THEN
      RAISE EXCEPTION 'Account % is needed by the system and cannot be deleted', OLD.name
        USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.first_used_at IS NOT NULL THEN
    IF NEW.first_used_at IS DISTINCT FROM OLD.first_used_at THEN
      RAISE EXCEPTION 'Account %: the date it was first used cannot change', OLD.name
        USING ERRCODE = 'restrict_violation';
    END IF;
    IF OLD.number <> '' AND NEW.number IS DISTINCT FROM OLD.number THEN
      RAISE EXCEPTION 'Account % has been used: its number cannot change', OLD.number
        USING ERRCODE = 'restrict_violation';
    END IF;
  END IF;
  IF NEW.system_role IS DISTINCT FROM OLD.system_role THEN
    RAISE EXCEPTION 'The system role of account % cannot change', OLD.name
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.system_role <> '' AND (NOT NEW.is_active OR NEW.account_type <> OLD.account_type) THEN
    RAISE EXCEPTION 'Account % is needed by the system: it stays active and keeps its type',
      OLD.name USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.merged_into_id IS NOT NULL AND (
      NEW.merged_into_id IS DISTINCT FROM OLD.merged_into_id
      OR NEW.merged_at IS DISTINCT FROM OLD.merged_at
      OR NEW.is_active) THEN
    RAISE EXCEPTION 'Account % was merged; a merge cannot be undone', OLD.name
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_account_guard
BEFORE UPDATE OR DELETE ON accounting_account
FOR EACH ROW EXECUTE FUNCTION accounting_account_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS accounting_account_guard ON accounting_account;
DROP FUNCTION IF EXISTS accounting_account_guard();
"""

TYPE_CHOICES = [
    ("bank", "Bank"),
    ("accounts_receivable", "Accounts receivable"),
    ("other_current_asset", "Other current asset"),
    ("fixed_asset", "Fixed asset"),
    ("other_asset", "Other asset"),
    ("accounts_payable", "Accounts payable"),
    ("credit_card", "Credit card"),
    ("other_current_liability", "Other current liability"),
    ("long_term_liability", "Long-term liability"),
    ("equity", "Equity"),
    ("income", "Income"),
    ("other_income", "Other income"),
    ("cost_of_goods_sold", "Cost of goods sold"),
    ("expense", "Expense"),
    ("other_expense", "Other expense"),
]
SYSTEM_ROLE_CHOICES = [
    ("accounts_receivable", "Accounts receivable"),
    ("accounts_payable", "Accounts payable"),
    ("retained_earnings", "Retained earnings"),
    ("opening_balance_equity", "Opening balance equity"),
    ("undeposited_funds", "Undeposited funds"),
    ("customer_advances", "Customer advances"),
    ("vat_payable", "VAT payable"),
    ("vat_receivable", "VAT receivable"),
]
NUMBER_REGEX = r"^[A-Z0-9][A-Z0-9.-]{0,19}$"


def big_id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0010_invoice_numbering"),
    ]

    operations = [
        migrations.CreateModel(
            name="DetailType",
            fields=[
                ("id", big_id()),
                ("account_type", models.CharField(choices=TYPE_CHOICES, max_length=30)),
                ("name", models.CharField(max_length=100)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "ordering": ["account_type", "name"],
                "constraints": [
                    models.UniqueConstraint(
                        models.F("account_type"),
                        django.db.models.functions.text.Lower("name"),
                        name="accounting_detailtype_unique_name",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="Account",
            fields=[
                ("id", big_id()),
                ("number", models.CharField(blank=True, max_length=20)),
                ("name", models.CharField(max_length=100)),
                ("account_type", models.CharField(choices=TYPE_CHOICES, max_length=30)),
                ("description", models.CharField(blank=True, max_length=500)),
                (
                    "system_role",
                    models.CharField(blank=True, choices=SYSTEM_ROLE_CHOICES, max_length=30),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("merged_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
                (
                    "default_division",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="default_accounts",
                        to="core.division",
                    ),
                ),
                (
                    "detail_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="accounts",
                        to="accounting.detailtype",
                    ),
                ),
                (
                    "merged_into",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="merged_accounts",
                        to="accounting.account",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="children",
                        to="accounting.account",
                    ),
                ),
            ],
            options={
                "ordering": ["number", "name"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("number", ""), _negated=True),
                        fields=("number",),
                        name="accounting_account_unique_number",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("number", ""), ("number__regex", NUMBER_REGEX), _connector="OR"),
                        name="accounting_account_number_format",
                    ),
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        models.F("parent"),
                        condition=models.Q(("parent__isnull", False)),
                        name="accounting_account_unique_sub_name",
                    ),
                    models.UniqueConstraint(
                        django.db.models.functions.text.Lower("name"),
                        condition=models.Q(("parent__isnull", True)),
                        name="accounting_account_unique_top_name",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("system_role", ""), _negated=True),
                        fields=("system_role",),
                        name="accounting_account_one_per_system_role",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("parent", models.F("id")), _negated=True),
                        name="accounting_account_not_own_parent",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("merged_into__isnull", True),
                            models.Q(
                                ("is_active", False),
                                ("merged_at__isnull", False),
                                ("system_role", ""),
                                models.Q(("merged_into", models.F("id")), _negated=True),
                            ),
                            _connector="OR",
                        ),
                        name="accounting_account_merged_is_inactive",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
