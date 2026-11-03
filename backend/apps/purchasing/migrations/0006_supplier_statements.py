import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Supplier statements (backlog P2-10): typed in or imported and checked against our records.
# The database refuses changing or deleting a statement, or its lines, once it is checked.

FORWARD = """
CREATE OR REPLACE FUNCTION purchasing_statement_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.status = 'checked' THEN
    RAISE EXCEPTION 'Supplier statement % has been checked and never changes', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER purchasing_statement_guard
BEFORE UPDATE OR DELETE ON purchasing_supplierstatement
FOR EACH ROW EXECUTE FUNCTION purchasing_statement_guard();

CREATE OR REPLACE FUNCTION purchasing_statement_line_guard() RETURNS trigger AS $$
DECLARE
  parent_status text;
BEGIN
  SELECT status INTO parent_status FROM purchasing_supplierstatement
    WHERE id = COALESCE(NEW.statement_id, OLD.statement_id);
  IF parent_status = 'checked' THEN
    RAISE EXCEPTION 'The supplier statement has been checked: its lines never change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER purchasing_statement_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON purchasing_supplierstatementline
FOR EACH ROW EXECUTE FUNCTION purchasing_statement_line_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS purchasing_statement_line_guard ON purchasing_supplierstatementline;
DROP FUNCTION IF EXISTS purchasing_statement_line_guard();
DROP TRIGGER IF EXISTS purchasing_statement_guard ON purchasing_supplierstatement;
DROP FUNCTION IF EXISTS purchasing_statement_guard();
"""


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


def fk(to, related_name="+", null=False, on_delete=django.db.models.deletion.PROTECT):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(on_delete=on_delete, related_name=related_name, to=to, **extra)


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0005_invoice_exchange_rate"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SupplierStatement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("from_date", models.DateField(blank=True, null=True)),
                ("statement_date", models.DateField()),
                ("closing_balance", money()),
                ("notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(
                        choices=[("open", "Being checked"), ("checked", "Checked")],
                        default="open",
                        max_length=10,
                    ),
                ),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("checked_at", models.DateTimeField(blank=True, null=True)),
                ("check_note", models.TextField(blank=True)),
                ("supplier", fk("masters.supplier", "statements")),
                ("currency", fk("masters.currency")),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("checked_by", fk(settings.AUTH_USER_MODEL, null=True)),
            ],
            options={
                "ordering": ["-statement_date", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(status="open")
                        | (models.Q(checked_by__isnull=False) & models.Q(checked_at__isnull=False)),
                        name="purchasing_statement_checked",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="SupplierStatementLine",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("line_no", models.PositiveIntegerField()),
                ("date", models.DateField()),
                ("reference", models.CharField(blank=True, max_length=60)),
                ("description", models.CharField(blank=True, max_length=300)),
                ("debit", money(default=0)),
                ("credit", money(default=0)),
                (
                    "statement",
                    fk(
                        "purchasing.supplierstatement",
                        "lines",
                        on_delete=django.db.models.deletion.CASCADE,
                    ),
                ),
            ],
            options={
                "ordering": ["statement", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("statement", "line_no"), name="purchasing_stmt_line_no"
                    ),
                    models.CheckConstraint(
                        condition=(models.Q(debit__gt=0) & models.Q(credit=0))
                        | (models.Q(credit__gt=0) & models.Q(debit=0)),
                        name="purchasing_stmt_line_one_side",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
