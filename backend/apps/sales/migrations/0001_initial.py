import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Quotations (backlog P15-03, spec 5.1). The number series "quotation" (QL{YY}{MM}{DD}{XX})
# was created in core migration 0010.

STATUSES = [
    ("draft", "Draft"),
    ("awaiting_approval", "Awaiting approval"),
    ("approved", "Approved"),
    ("sent", "Sent"),
    ("accepted", "Accepted"),
    ("lost", "Lost"),
    ("expired", "Expired"),
    ("revised", "Replaced by a revision"),
]


def id_field():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


def user_fk():
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("accounting", "0004_taxes"),
        ("core", "0016_sales_roles_active"),
        ("masters", "0010_costing_rates"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Quotation",
            fields=[
                ("id", id_field()),
                ("number", models.CharField(db_index=True, max_length=30)),
                ("revision", models.PositiveSmallIntegerField(default=0)),
                (
                    "enquiry_ref",
                    models.CharField(blank=True, max_length=100, verbose_name="Enquiry reference"),
                ),
                ("quote_date", models.DateField()),
                ("valid_until", models.DateField()),
                (
                    "exchange_rate",
                    models.DecimalField(decimal_places=6, default=1, max_digits=18),
                ),
                ("rate_date", models.DateField(blank=True, null=True)),
                ("payment_terms", models.CharField(blank=True, max_length=200)),
                ("delivery_lead_time", models.CharField(blank=True, max_length=100)),
                (
                    "incoterm",
                    models.CharField(blank=True, max_length=3, verbose_name="Delivery term"),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "status",
                    models.CharField(choices=STATUSES, default="draft", max_length=20),
                ),
                ("subtotal", money(default=0)),
                ("tax_total", money(default=0)),
                ("total_amount", money(default=0)),
                ("total_lkr", money(default=0, verbose_name="Total (LKR)")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "contact",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="masters.customercontact",
                    ),
                ),
                ("created_by", user_fk()),
                (
                    "currency",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="masters.currency",
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="quotations",
                        to="masters.customer",
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
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revisions",
                        to="sales.quotation",
                    ),
                ),
            ],
            options={
                "ordering": ["-quote_date", "-number", "-revision"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("number", "revision"), name="sales_quotation_number_revision"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("valid_until__gte", models.F("quote_date"))),
                        name="sales_quotation_valid_after_date",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("exchange_rate__gt", 0)),
                        name="sales_quotation_rate_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="QuotationLine",
            fields=[
                ("id", id_field()),
                ("line_no", models.PositiveSmallIntegerField()),
                ("description", models.TextField()),
                (
                    "drawing_no",
                    models.CharField(blank=True, max_length=50, verbose_name="Drawing no."),
                ),
                (
                    "drawing_rev",
                    models.CharField(blank=True, max_length=20, verbose_name="Drawing revision"),
                ),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=18)),
                ("unit", models.CharField(default="pcs", max_length=20)),
                (
                    "min_order_qty",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        max_digits=18,
                        null=True,
                        verbose_name="Minimum order quantity",
                    ),
                ),
                ("unit_price", money()),
                ("amount", money()),
                ("tax_amount", money(default=0)),
                ("total", money()),
                (
                    "quotation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="sales.quotation",
                    ),
                ),
                (
                    "tax_code",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.taxcode",
                    ),
                ),
            ],
            options={
                "ordering": ["quotation", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("quotation", "line_no"), name="sales_line_no_unique"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0)) & models.Q(("unit_price__gte", 0)),
                        name="sales_line_quantity_price",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="QuotationQtyBreak",
            fields=[
                ("id", id_field()),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=18)),
                ("unit_price", money()),
                (
                    "line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="breaks",
                        to="sales.quotationline",
                    ),
                ),
            ],
            options={
                "ordering": ["line", "quantity"],
                "constraints": [
                    models.UniqueConstraint(fields=("line", "quantity"), name="sales_break_unique"),
                    models.CheckConstraint(
                        condition=models.Q(("quantity__gt", 0)) & models.Q(("unit_price__gte", 0)),
                        name="sales_break_quantity_price",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="QuotationFile",
            fields=[
                ("id", id_field()),
                ("line_no", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("file", models.FileField(upload_to="quotations/%Y/%m/")),
                ("file_name", models.CharField(max_length=200)),
                ("content_type", models.CharField(max_length=100)),
                ("size", models.PositiveIntegerField()),
                ("sha256", models.CharField(db_index=True, max_length=64)),
                ("uploaded_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "quotation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="files",
                        to="sales.quotation",
                    ),
                ),
                ("uploaded_by", user_fk()),
            ],
            options={"ordering": ["line_no", "uploaded_at", "id"]},
        ),
    ]
