import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Bank statement import (backlog P2-15). Templates per bank, kept by the Accountant. An
# imported statement and its lines never change (a wrong import is deleted whole and imported
# again); the same file is imported once per account. The Commercial Bank PDF template is
# loaded to start with.

FORWARD = """
CREATE OR REPLACE FUNCTION banking_statement_guard() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'An imported bank statement never changes; delete it and import it again'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER banking_statement_guard
BEFORE UPDATE ON banking_bankstatement
FOR EACH ROW EXECUTE FUNCTION banking_statement_guard();

CREATE TRIGGER banking_statement_line_guard
BEFORE UPDATE ON banking_bankstatementline
FOR EACH ROW EXECUTE FUNCTION banking_statement_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS banking_statement_line_guard ON banking_bankstatementline;
DROP TRIGGER IF EXISTS banking_statement_guard ON banking_bankstatement;
DROP FUNCTION IF EXISTS banking_statement_guard();
"""


def seed(apps, schema_editor):
    Template = apps.get_model("banking", "StatementTemplate")
    Template.objects.get_or_create(
        code="COMBANK-PDF",
        defaults={
            "bank_name": "Commercial Bank of Ceylon",
            "file_kind": "pdf",
            "date_format": "%d/%m/%Y",
            "notes": "The account statement PDF (JasperReports): date, description, debit, "
            "credit, balance with Cr/Dr. Lines without a date continue the description.",
        },
    )


ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


def money(null=False):
    if null:
        return models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True)
    return models.DecimalField(decimal_places=2, default=0, max_digits=18)


class Migration(migrations.Migration):
    dependencies = [
        ("banking", "0001_initial"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StatementTemplate",
            fields=[
                ("id", ID.clone()),
                ("code", models.CharField(max_length=20, unique=True)),
                ("bank_name", models.CharField(max_length=100)),
                (
                    "file_kind",
                    models.CharField(
                        choices=[
                            ("excel", "Excel (.xlsx)"),
                            ("csv", "CSV"),
                            ("pdf", "PDF with text"),
                        ],
                        max_length=10,
                    ),
                ),
                ("date_format", models.CharField(default="%d/%m/%Y", max_length=20)),
                ("date_column", models.CharField(blank=True, default="Date", max_length=60)),
                (
                    "description_column",
                    models.CharField(blank=True, default="Description", max_length=60),
                ),
                ("reference_column", models.CharField(blank=True, max_length=60)),
                ("out_column", models.CharField(blank=True, default="Debit", max_length=60)),
                ("in_column", models.CharField(blank=True, default="Credit", max_length=60)),
                ("amount_column", models.CharField(blank=True, max_length=60)),
                ("negative_is_out", models.BooleanField(default=True)),
                ("balance_column", models.CharField(blank=True, default="Balance", max_length=60)),
                ("checked", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["bank_name", "code"]},
        ),
        migrations.CreateModel(
            name="BankStatement",
            fields=[
                ("id", ID.clone()),
                ("file_name", models.CharField(max_length=200)),
                ("sha256", models.CharField(max_length=64)),
                ("from_date", models.DateField()),
                ("to_date", models.DateField()),
                ("opening_balance", money(null=True)),
                ("closing_balance", money(null=True)),
                ("skipped", models.PositiveIntegerField(default=0)),
                ("imported_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="statements",
                        to="masters.companyaccount",
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="banking.statementtemplate",
                    ),
                ),
                (
                    "imported_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-to_date", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("account", "sha256"), name="banking_statement_file_once"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(to_date__gte=models.F("from_date")),
                        name="banking_statement_dates",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="BankStatementLine",
            fields=[
                ("id", ID.clone()),
                ("line_no", models.PositiveIntegerField()),
                ("date", models.DateField()),
                ("description", models.CharField(blank=True, max_length=500)),
                ("reference", models.CharField(blank=True, max_length=60)),
                ("money_out", money()),
                ("money_in", money()),
                ("balance", money(null=True)),
                (
                    "statement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="banking.bankstatement",
                    ),
                ),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="statement_lines",
                        to="masters.companyaccount",
                    ),
                ),
            ],
            options={
                "ordering": ["statement", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("statement", "line_no"), name="banking_statement_line_no"
                    ),
                    models.CheckConstraint(
                        condition=(models.Q(money_out__gt=0) & models.Q(money_in=0))
                        | (models.Q(money_in__gt=0) & models.Q(money_out=0)),
                        name="banking_statement_line_one_side",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
