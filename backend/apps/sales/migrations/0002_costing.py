import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Machining costing per quotation line (backlog P15-04, spec 5.1). Internal only: it is never
# shown to the customer. The rates used are copied onto the costing (rule 11).


def id_field():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


def size(**extra):
    return models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True, **extra)


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0010_costing_rates"),
        ("sales", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="QuotationCosting",
            fields=[
                ("id", id_field()),
                (
                    "method",
                    models.CharField(
                        choices=[("machining", "Machining")], default="machining", max_length=20
                    ),
                ),
                ("rates_date", models.DateField()),
                (
                    "material_rate",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        max_digits=18,
                        null=True,
                        verbose_name="Material price per kg (LKR)",
                    ),
                ),
                (
                    "density",
                    models.DecimalField(
                        blank=True,
                        decimal_places=3,
                        max_digits=6,
                        null=True,
                        verbose_name="Density (g/cm³)",
                    ),
                ),
                ("form", models.CharField(blank=True, max_length=20)),
                ("size_a_mm", size()),
                ("size_b_mm", size()),
                ("length_mm", size()),
                (
                    "cutting_allowance_mm",
                    models.DecimalField(decimal_places=2, default=0, max_digits=8),
                ),
                (
                    "entered_weight_kg",
                    models.DecimalField(
                        blank=True,
                        decimal_places=4,
                        max_digits=12,
                        null=True,
                        verbose_name="Weight per piece entered (kg)",
                    ),
                ),
                (
                    "weight_kg",
                    models.DecimalField(
                        decimal_places=4,
                        default=0,
                        max_digits=12,
                        verbose_name="Weight per piece used (kg)",
                    ),
                ),
                ("setup_hours", models.DecimalField(decimal_places=2, default=0, max_digits=8)),
                (
                    "setup_rate",
                    models.DecimalField(
                        decimal_places=2, max_digits=18, verbose_name="Setup rate per hour (LKR)"
                    ),
                ),
                (
                    "overhead_pct",
                    models.DecimalField(decimal_places=2, max_digits=5, verbose_name="Overhead %"),
                ),
                (
                    "margin_pct",
                    models.DecimalField(decimal_places=2, max_digits=5, verbose_name="Margin %"),
                ),
                ("notes", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "line",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="costing",
                        to="sales.quotationline",
                    ),
                ),
                (
                    "material",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="masters.material",
                    ),
                ),
                (
                    "updated_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("setup_hours__gte", 0),
                            ("setup_rate__gte", 0),
                            ("overhead_pct__gte", 0),
                            ("margin_pct__gte", 0),
                            ("weight_kg__gte", 0),
                            ("cutting_allowance_mm__gte", 0),
                        ),
                        name="sales_costing_not_negative",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="QuotationCostingOperation",
            fields=[
                ("id", id_field()),
                ("seq", models.PositiveSmallIntegerField()),
                ("description", models.CharField(blank=True, max_length=100)),
                (
                    "minutes",
                    models.DecimalField(
                        decimal_places=3, max_digits=10, verbose_name="Minutes per piece"
                    ),
                ),
                (
                    "rate",
                    models.DecimalField(
                        decimal_places=2, max_digits=18, verbose_name="Hourly rate (LKR)"
                    ),
                ),
                (
                    "costing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="operations",
                        to="sales.quotationcosting",
                    ),
                ),
                (
                    "machine",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="masters.machine",
                    ),
                ),
            ],
            options={
                "ordering": ["costing", "seq"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("costing", "seq"), name="sales_costing_op_seq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("minutes__gt", 0), ("rate__gte", 0)),
                        name="sales_costing_op_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="QuotationCostingExtra",
            fields=[
                ("id", id_field()),
                ("seq", models.PositiveSmallIntegerField()),
                ("description", models.CharField(max_length=100)),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2, max_digits=18, verbose_name="Amount (LKR)"
                    ),
                ),
                ("per_order", models.BooleanField(default=False)),
                (
                    "costing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="extras",
                        to="sales.quotationcosting",
                    ),
                ),
            ],
            options={
                "ordering": ["costing", "seq"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("costing", "seq"), name="sales_costing_extra_seq"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("amount__gte", 0)),
                        name="sales_costing_extra_amount",
                    ),
                ],
            },
        ),
    ]
