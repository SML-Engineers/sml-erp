import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Items and stores (backlog P16-03, spec 5A.3, 6A). A used item or store keeps its code and is
# never deleted (masters_code_guard, masters migration 0002). Each production division gets
# its main, quarantine and rejected stores.

STORES = [
    ("MAIN", "main", "Main store"),
    ("QUAR", "quarantine", "Quarantine"),
    ("REJ", "rejected", "Rejected goods"),
]


def seed_stores(apps, schema_editor):
    Division = apps.get_model("core", "Division")
    Store = apps.get_model("inventory", "Store")
    for division in Division.objects.filter(division_type="production"):
        for suffix, kind, name in STORES:
            Store.objects.get_or_create(
                code=f"{division.code}-{suffix}",
                defaults={"name": f"{division.name}: {name}", "division": division, "kind": kind},
            )


FORWARD = """
CREATE TRIGGER inventory_item_guard
BEFORE UPDATE OR DELETE ON inventory_item
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();

CREATE TRIGGER inventory_store_guard
BEFORE UPDATE OR DELETE ON inventory_store
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS inventory_item_guard ON inventory_item;
DROP TRIGGER IF EXISTS inventory_store_guard ON inventory_store;
"""


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0019_purchasing_roles"),
        ("accounting", "0004_taxes"),
        ("masters", "0010_costing_rates"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Store",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("main", "Main store"),
                            ("quarantine", "Quarantine (waiting for QC)"),
                            ("rejected", "Rejected (to return)"),
                        ],
                        default="main",
                        max_length=12,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("first_used_at", models.DateTimeField(blank=True, null=True)),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.division",
                    ),
                ),
            ],
            options={
                "ordering": ["division__code", "kind", "code"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("kind", "main"), _negated=True),
                        fields=("division", "kind"),
                        name="inventory_one_special_store_per_division",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Item",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=150)),
                ("description", models.TextField(blank=True)),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("raw_material", "Raw material"),
                            ("bought_out", "Bought-out part"),
                            ("consumable", "Consumable"),
                            ("spare", "Spare part"),
                            ("packing", "Packing material"),
                        ],
                        max_length=20,
                    ),
                ),
                (
                    "unit",
                    models.CharField(
                        choices=[
                            ("pcs", "pcs"),
                            ("kg", "kg"),
                            ("g", "g"),
                            ("m", "m"),
                            ("mm", "mm"),
                            ("l", "l"),
                            ("set", "set"),
                            ("box", "box"),
                            ("roll", "roll"),
                            ("sheet", "sheet"),
                            ("pair", "pair"),
                        ],
                        default="pcs",
                        max_length=10,
                    ),
                ),
                ("is_stock", models.BooleanField(default=True)),
                (
                    "package_type",
                    models.CharField(
                        choices=[
                            ("none", "Not by package"),
                            ("bag", "Bags (resin, masterbatch)"),
                            ("bar", "Bars, rods, tubes"),
                            ("plate", "Plates, sheets"),
                            ("coil", "Coils"),
                            ("counted", "Counted items (boxes)"),
                        ],
                        default="none",
                        max_length=10,
                    ),
                ),
                ("inspection_required", models.BooleanField(default=True)),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("first_used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "division",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.division",
                    ),
                ),
                (
                    "expense_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="expense_items",
                        to="accounting.account",
                    ),
                ),
                (
                    "inventory_account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inventory_items",
                        to="accounting.account",
                    ),
                ),
                (
                    "material",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="items",
                        to="masters.material",
                    ),
                ),
            ],
            options={"ordering": ["code"]},
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed_stores, migrations.RunPython.noop),
    ]
