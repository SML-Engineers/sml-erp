import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Company bank and cash accounts, cheque books (backlog P0-14).
# - A used cheque number is kept for good (insert-only, core_refuse_change).
# - An account used on a payment keeps its code and cannot be deleted (masters_code_guard).
FORWARD = """
CREATE TRIGGER masters_chequeleaf_insert_only
BEFORE UPDATE OR DELETE ON masters_chequeleaf
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE TRIGGER masters_companyaccount_guard
BEFORE UPDATE OR DELETE ON masters_companyaccount
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS masters_companyaccount_guard ON masters_companyaccount;
DROP TRIGGER IF EXISTS masters_chequeleaf_insert_only ON masters_chequeleaf;
"""


def big_id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


def user_fk():
    return models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_invoice_numbering"),
        ("masters", "0006_suppliers"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CompanyAccount",
            fields=[
                ("id", big_id()),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("current", "Bank current account"),
                            ("savings", "Bank savings account"),
                            ("cash", "Cash"),
                            ("petty_cash", "Petty cash"),
                        ],
                        max_length=20,
                    ),
                ),
                ("bank_name", models.CharField(blank=True, max_length=100)),
                ("branch", models.CharField(blank=True, max_length=100)),
                ("account_number", models.CharField(blank=True, max_length=34)),
                (
                    "float_amount",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="company_accounts",
                        to="masters.currency",
                    ),
                ),
                ("custodian", user_fk()),
                (
                    "division",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="company_accounts",
                        to="core.division",
                    ),
                ),
            ],
            options={
                "ordering": ["code"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("account_number", ""), _negated=True),
                        fields=("bank_name", "account_number"),
                        name="masters_companyaccount_unique_number",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("float_amount__isnull", True),
                            ("float_amount__gt", 0),
                            _connector="OR",
                        ),
                        name="masters_companyaccount_float_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DivisionBankDefault",
            fields=[
                ("id", big_id()),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="default_for",
                        to="masters.companyaccount",
                    ),
                ),
                (
                    "division",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bank_default",
                        to="core.division",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="ChequeBook",
            fields=[
                ("id", big_id()),
                ("first_number", models.PositiveIntegerField()),
                ("last_number", models.PositiveIntegerField()),
                ("digits", models.PositiveSmallIntegerField(default=6)),
                ("received_on", models.DateField(default=django.utils.timezone.localdate)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cheque_books",
                        to="masters.companyaccount",
                    ),
                ),
                ("created_by", user_fk()),
            ],
            options={
                "ordering": ["account", "first_number"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("last_number__gte", models.F("first_number"))),
                        name="masters_chequebook_range_in_order",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="ChequeLeaf",
            fields=[
                ("id", big_id()),
                ("number", models.PositiveIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[("issued", "Issued"), ("spoiled", "Spoiled")], max_length=10
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("used_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "account",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cheques",
                        to="masters.companyaccount",
                    ),
                ),
                (
                    "book",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="leaves",
                        to="masters.chequebook",
                    ),
                ),
                ("used_by", user_fk()),
            ],
            options={
                "ordering": ["account", "number"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("account", "number"), name="masters_cheque_once"
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
