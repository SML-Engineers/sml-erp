import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Costing rates (backlog P15-02, spec 5.1, rule 11).
# - Material codes are fixed once a quotation uses them (masters_code_guard, migration 0002).
# - A material rate or division costing rate whose date has arrived cannot be changed or
#   removed (masters_rate_guard, migration 0002); a later rate replaces it.

FORWARD = """
CREATE TRIGGER masters_material_guard
BEFORE UPDATE OR DELETE ON masters_material
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();

CREATE TRIGGER masters_materialrate_guard
BEFORE UPDATE OR DELETE ON masters_materialrate
FOR EACH ROW EXECUTE FUNCTION masters_rate_guard();

CREATE TRIGGER masters_costingrate_guard
BEFORE UPDATE OR DELETE ON masters_costingrate
FOR EACH ROW EXECUTE FUNCTION masters_rate_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS masters_costingrate_guard ON masters_costingrate;
DROP TRIGGER IF EXISTS masters_materialrate_guard ON masters_materialrate;
DROP TRIGGER IF EXISTS masters_material_guard ON masters_material;
"""


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
        ("core", "0016_sales_roles_active"),
        ("masters", "0009_customers"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Material",
            fields=[
                ("id", id_field()),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("metal", "Metal"),
                            ("resin", "Plastic resin"),
                            ("masterbatch", "Masterbatch"),
                            ("other", "Other"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "form",
                    models.CharField(
                        choices=[
                            ("round_bar", "Round bar"),
                            ("hex_bar", "Hexagon bar"),
                            ("flat_bar", "Flat or square bar"),
                            ("plate", "Plate or sheet"),
                            ("tube", "Tube or pipe"),
                            ("granules", "Granules"),
                            ("other", "Other"),
                        ],
                        default="other",
                        max_length=20,
                    ),
                ),
                ("grade", models.CharField(blank=True, max_length=50)),
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
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("created_by", user_fk()),
            ],
            options={
                "ordering": ["kind", "code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("density__isnull", True))
                        | models.Q(("density__gt", 0)),
                        name="masters_material_density_positive",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="MaterialRate",
            fields=[
                ("id", id_field()),
                ("effective_from", models.DateField()),
                (
                    "rate",
                    models.DecimalField(
                        decimal_places=2, max_digits=18, verbose_name="Price per kg (LKR)"
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", user_fk()),
                (
                    "material",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rates",
                        to="masters.material",
                    ),
                ),
            ],
            options={
                "ordering": ["material", "-effective_from"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("material", "effective_from"),
                        name="masters_materialrate_one_per_day",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("rate__gte", 0)),
                        name="masters_materialrate_not_negative",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CostingRate",
            fields=[
                ("id", id_field()),
                ("effective_from", models.DateField()),
                (
                    "overhead_pct",
                    models.DecimalField(decimal_places=2, max_digits=5, verbose_name="Overhead %"),
                ),
                (
                    "margin_pct",
                    models.DecimalField(
                        decimal_places=2, max_digits=5, verbose_name="Default margin %"
                    ),
                ),
                (
                    "setup_rate",
                    models.DecimalField(
                        decimal_places=2, max_digits=18, verbose_name="Setup rate per hour (LKR)"
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", user_fk()),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="costing_rates",
                        to="core.division",
                    ),
                ),
            ],
            options={
                "ordering": ["division", "-effective_from"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("division", "effective_from"),
                        name="masters_costingrate_one_per_day",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("overhead_pct__gte", 0))
                        & models.Q(("margin_pct__gte", 0))
                        & models.Q(("setup_rate__gte", 0)),
                        name="masters_costingrate_not_negative",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
