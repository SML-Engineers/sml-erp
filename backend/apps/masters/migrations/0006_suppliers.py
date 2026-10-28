import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Suppliers and payees (backlog P0-13, spec 4.1).
# - Payee codes come from the number series "payee": S0001, S0002, ...
# - A payee used on a voucher keeps its code and cannot be deleted (masters_code_guard,
#   migration 0002).


def load(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    NumberSeries.objects.get_or_create(
        document_type="payee",
        defaults={
            "name": "Payees",
            "format": "S{NNNN}",
            "reset_period": "never",
            "when_full": "grow",
        },
    )


FORWARD = """
CREATE TRIGGER masters_supplier_guard
BEFORE UPDATE OR DELETE ON masters_supplier
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();
"""

BACKWARD = "DROP TRIGGER IF EXISTS masters_supplier_guard ON masters_supplier;"


def user_fk(**extra):
    return models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
        **extra,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_invoice_numbering"),
        ("masters", "0005_quotation_limits"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Supplier",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=200)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("supplier", "Supplier"),
                            ("utility", "Utility"),
                            ("bank_card", "Bank or credit card"),
                            ("government", "Government"),
                            ("employee", "Employee"),
                            ("other", "Other"),
                        ],
                        default="supplier",
                        max_length=20,
                    ),
                ),
                ("address", models.TextField(blank=True)),
                ("phone", models.CharField(blank=True, max_length=50)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("contact_person", models.CharField(blank=True, max_length=100)),
                ("contact_phone", models.CharField(blank=True, max_length=50)),
                (
                    "vat_no",
                    models.CharField(blank=True, max_length=50, verbose_name="VAT registration no."),
                ),
                ("tin", models.CharField(blank=True, max_length=20, verbose_name="TIN")),
                ("payment_terms_days", models.PositiveSmallIntegerField(default=30)),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("bank_changed_at", models.DateTimeField(blank=True, editable=False, null=True)),
                (
                    "bank_change_acknowledged_at",
                    models.DateTimeField(blank=True, editable=False, null=True),
                ),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("bank_changed_by", user_fk()),
                ("created_by", user_fk()),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="suppliers",
                        to="masters.currency",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "indexes": [models.Index(fields=["vat_no"], name="masters_supplier_vat")],
            },
        ),
        migrations.CreateModel(
            name="SupplierBankAccount",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("bank_name", models.CharField(max_length=100)),
                ("branch", models.CharField(blank=True, max_length=100)),
                ("account_name", models.CharField(max_length=200)),
                ("account_number", models.CharField(max_length=34)),
                (
                    "swift_code",
                    models.CharField(blank=True, max_length=11, verbose_name="SWIFT / BIC"),
                ),
                ("is_default", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", user_fk()),
                (
                    "supplier",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="bank_accounts",
                        to="masters.supplier",
                    ),
                ),
            ],
            options={
                "ordering": ["supplier", "-is_default", "bank_name"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("is_default", True)),
                        fields=("supplier",),
                        name="masters_supplier_one_default_account",
                    )
                ],
            },
        ),
        migrations.RunPython(load, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
