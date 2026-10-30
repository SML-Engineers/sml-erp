import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Customers and their contacts (backlog P15-01, spec 5.4, 5.5).
# - Customer codes come from the number series "customer": C0001, C0002, ...
# - A customer used on a document keeps its code and cannot be deleted
#   (masters_code_guard, migration 0002).

INCOTERMS = [
    ("EXW", "EXW – Ex works"),
    ("FCA", "FCA – Free carrier"),
    ("FAS", "FAS – Free alongside ship"),
    ("FOB", "FOB – Free on board"),
    ("CFR", "CFR – Cost and freight"),
    ("CIF", "CIF – Cost, insurance and freight"),
    ("CPT", "CPT – Carriage paid to"),
    ("CIP", "CIP – Carriage and insurance paid to"),
    ("DAP", "DAP – Delivered at place"),
    ("DPU", "DPU – Delivered at place unloaded"),
    ("DDP", "DDP – Delivered duty paid"),
]


def load(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    NumberSeries.objects.get_or_create(
        document_type="customer",
        defaults={
            "name": "Customers",
            "format": "C{NNNN}",
            "reset_period": "never",
            "when_full": "grow",
        },
    )


FORWARD = """
CREATE TRIGGER masters_customer_guard
BEFORE UPDATE OR DELETE ON masters_customer
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();
"""

BACKWARD = "DROP TRIGGER IF EXISTS masters_customer_guard ON masters_customer;"


def user_fk():
    return models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
    )


def id_field():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0015_approval_reminders"),
        ("masters", "0008_company_account_ledger"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Customer",
            fields=[
                ("id", id_field()),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("billing_address", models.TextField(blank=True)),
                ("delivery_address", models.TextField(blank=True)),
                ("phone", models.CharField(blank=True, max_length=50)),
                ("email", models.EmailField(blank=True, max_length=254)),
                (
                    "vat_no",
                    models.CharField(blank=True, max_length=50, verbose_name="VAT registration no."),
                ),
                ("tin", models.CharField(blank=True, max_length=20, verbose_name="TIN")),
                ("payment_terms_days", models.PositiveSmallIntegerField(default=30)),
                (
                    "credit_limit",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=18,
                        null=True,
                        verbose_name="Credit limit",
                    ),
                ),
                ("is_export", models.BooleanField(default=False, verbose_name="Export customer")),
                ("country", models.CharField(blank=True, max_length=60)),
                ("incoterm", models.CharField(blank=True, choices=INCOTERMS, max_length=3)),
                ("port_of_destination", models.CharField(blank=True, max_length=100)),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("created_by", user_fk()),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="customers",
                        to="masters.currency",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "indexes": [models.Index(fields=["vat_no"], name="masters_customer_vat")],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("credit_limit__isnull", True))
                        | models.Q(("credit_limit__gte", 0)),
                        name="masters_customer_credit_not_negative",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="CustomerContact",
            fields=[
                ("id", id_field()),
                ("name", models.CharField(max_length=100)),
                ("position", models.CharField(blank=True, max_length=100)),
                ("phone", models.CharField(blank=True, max_length=50)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("is_main", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", user_fk()),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="contacts",
                        to="masters.customer",
                    ),
                ),
            ],
            options={
                "ordering": ["customer", "-is_main", "name"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("is_main", True)),
                        fields=("customer",),
                        name="masters_customer_one_main_contact",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("is_main", False)) | models.Q(("is_active", True)),
                        name="masters_customer_main_contact_active",
                    ),
                ],
            },
        ),
        migrations.RunPython(load, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
