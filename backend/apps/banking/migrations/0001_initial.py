import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Cheque register and deposits (backlog P2-14). Deposit slips, their lines and cheque
# clearances are insert-only (core_refuse_change). Deposits are numbered DP{YY}{MM}{NNNN}.

FORWARD = """
CREATE TRIGGER banking_deposit_insert_only
BEFORE UPDATE OR DELETE ON banking_deposit
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
CREATE TRIGGER banking_depositline_insert_only
BEFORE UPDATE OR DELETE ON banking_depositline
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
CREATE TRIGGER banking_chequeclearance_insert_only
BEFORE UPDATE OR DELETE ON banking_chequeclearance
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS banking_chequeclearance_insert_only ON banking_chequeclearance;
DROP TRIGGER IF EXISTS banking_depositline_insert_only ON banking_depositline;
DROP TRIGGER IF EXISTS banking_deposit_insert_only ON banking_deposit;
"""

SERIES = ("deposit", "Deposit slips", "DP{YY}{MM}{NNNN}", "monthly", "grow")


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


ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


def fk(to, related_name="+"):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("sales", "0015_returned_cheques"),
        ("masters", "0011_limit_no_maximum"),
        ("accounting", "0014_zero_rated_code"),
        ("core", "0025_credit_terms_action"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Deposit",
            fields=[
                ("id", ID.clone()),
                ("number", models.CharField(max_length=30, unique=True)),
                ("deposit_date", models.DateField()),
                ("slip_no", models.CharField(blank=True, max_length=50)),
                ("total", models.DecimalField(decimal_places=2, max_digits=18)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("account", fk("masters.companyaccount", "deposits")),
                (
                    "journal_entry",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deposit",
                        to="accounting.journalentry",
                    ),
                ),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-deposit_date", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(total__gt=0), name="banking_deposit_total"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DepositLine",
            fields=[
                ("id", ID.clone()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("deposit", fk("banking.deposit", "lines")),
                (
                    "receipt",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="deposit_line",
                        to="sales.customerreceipt",
                    ),
                ),
            ],
            options={
                "ordering": ["deposit", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(amount__gt=0), name="banking_line_amount"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ChequeClearance",
            fields=[
                ("id", ID.clone()),
                ("cleared_on", models.DateField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "leaf",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="clearance",
                        to="masters.chequeleaf",
                    ),
                ),
                (
                    "deposit_line",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="clearance",
                        to="banking.depositline",
                    ),
                ),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-cleared_on", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(leaf__isnull=False, deposit_line__isnull=True)
                        | models.Q(leaf__isnull=True, deposit_line__isnull=False),
                        name="banking_clearance_one_cheque",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(load_series, migrations.RunPython.noop),
    ]
