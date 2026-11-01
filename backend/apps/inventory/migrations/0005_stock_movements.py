import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Stock movements (backlog P16-09, spec 5A.3): insert-only. Balances are sums of movements;
# a movement is never changed or deleted, by anyone.

FORWARD = """
CREATE OR REPLACE FUNCTION inventory_movement_guard() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Stock movements are never changed or deleted; record another movement'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inventory_movement_guard
BEFORE UPDATE OR DELETE ON inventory_stockmovement
FOR EACH ROW EXECUTE FUNCTION inventory_movement_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS inventory_movement_guard ON inventory_stockmovement;
DROP FUNCTION IF EXISTS inventory_movement_guard();
"""


def fk(to, related_name="+", null=False):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0004_incoming_inspection"),
        ("accounting", "0005_grni_account"),
        ("core", "0019_purchasing_roles"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StockMovement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("lot_no", models.CharField(max_length=40)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("received", "Received into quarantine"),
                            ("damaged", "Received damaged"),
                            ("accepted", "Accepted by QC"),
                            ("rejected", "Rejected by QC"),
                            ("reversed", "GRN reversed"),
                        ],
                        max_length=10,
                    ),
                ),
                ("movement_date", models.DateField()),
                ("quantity", models.DecimalField(decimal_places=3, max_digits=18)),
                ("value", models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("division", fk("core.division")),
                ("item", fk("inventory.item", "movements")),
                ("store", fk("inventory.store", "movements")),
                ("journal_entry", fk("accounting.journalentry", null=True)),
                ("receipt_line", fk("inventory.goodsreceiptline", "movements", null=True)),
            ],
            options={
                "ordering": ["movement_date", "id"],
                "indexes": [
                    models.Index(fields=["item", "store", "lot_no"], name="inventory_mv_balance")
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("quantity", 0), _negated=True),
                        name="inventory_movement_not_zero",
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
