import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Petty cash (backlog P2-17). Expenses paid from a float, numbered PE{YY}{MM}{NNNN}. Once an
# expense is on a replenishment voucher, what it says never changes (database guard); it is
# never deleted after that.

FORWARD = """
CREATE OR REPLACE FUNCTION banking_petty_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.voucher_id IS NULL THEN
    IF TG_OP = 'DELETE' THEN
      RETURN OLD;
    END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Petty cash expense % is on a voucher and is never deleted', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number
     OR NEW.account_id IS DISTINCT FROM OLD.account_id
     OR NEW.expense_date IS DISTINCT FROM OLD.expense_date
     OR NEW.paid_to IS DISTINCT FROM OLD.paid_to
     OR NEW.description IS DISTINCT FROM OLD.description
     OR NEW.amount IS DISTINCT FROM OLD.amount
     OR NEW.slip IS DISTINCT FROM OLD.slip
     OR NEW.slip_sha256 IS DISTINCT FROM OLD.slip_sha256 THEN
    RAISE EXCEPTION 'Petty cash expense % is on a voucher and never changes', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER banking_petty_guard
BEFORE UPDATE OR DELETE ON banking_pettyexpense
FOR EACH ROW EXECUTE FUNCTION banking_petty_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS banking_petty_guard ON banking_pettyexpense;
DROP FUNCTION IF EXISTS banking_petty_guard();
"""

SERIES = ("petty_expense", "Petty cash expenses", "PE{YY}{MM}{NNNN}", "monthly", "grow")


def load_series(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    document_type, name, number_format, reset, when_full = SERIES
    NumberSeries.objects.get_or_create(
        document_type=document_type,
        defaults={
            "name": name,
            "format": number_format,
            "reset_period": reset,
            "when_full": when_full,
        },
    )


def fk(to, null=False, related_name="+"):
    return models.ForeignKey(
        blank=null,
        null=null,
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name,
        to=to,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("banking", "0003_reconciliation"),
        ("vouchers", "0011_withholding_tax"),
        ("accounting", "0014_zero_rated_code"),
        ("core", "0025_credit_terms_action"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PettyExpense",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("number", models.CharField(max_length=30, unique=True)),
                ("expense_date", models.DateField()),
                ("paid_to", models.CharField(max_length=150)),
                ("description", models.CharField(max_length=500)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("slip", models.FileField(upload_to="petty-cash/%Y/%m/")),
                ("slip_name", models.CharField(max_length=200)),
                ("slip_type", models.CharField(max_length=100)),
                ("slip_size", models.PositiveIntegerField()),
                ("slip_sha256", models.CharField(max_length=64)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("account", fk("masters.companyaccount", related_name="petty_expenses")),
                ("ledger", fk("accounting.account", null=True)),
                ("division", fk("core.division", null=True)),
                ("voucher", fk("vouchers.voucher", null=True, related_name="petty_expenses")),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-expense_date", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(amount__gt=0), name="banking_petty_amount_positive"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(load_series, migrations.RunPython.noop),
    ]
