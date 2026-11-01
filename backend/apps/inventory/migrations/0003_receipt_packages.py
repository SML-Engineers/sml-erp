import django.db.models.deletion
from decimal import Decimal

from django.db import migrations, models

# Package-by-package receiving (backlog P16-07, spec 6A.2).
# - Items get the usual tare, a weight tolerance (0.5% to start), and the kg per metre and
#   density that bars and plates are checked against; a GRN line keeps the values in force
#   when its packages were entered (rule 11).
# - One row per bag, bundle, plate, coil or box, with its own lot number. Like the lines,
#   packages cannot change once the GRN has left draft.

FORWARD = """
CREATE OR REPLACE FUNCTION inventory_grn_package_guard() RETURNS trigger AS $$
DECLARE
  st TEXT;
BEGIN
  SELECT r.status INTO st
    FROM inventory_goodsreceiptline l JOIN inventory_goodsreceipt r ON r.id = l.receipt_id
   WHERE l.id = CASE WHEN TG_OP = 'INSERT' THEN NEW.line_id ELSE OLD.line_id END;
  IF st IS NOT NULL AND st <> 'draft' THEN
    RAISE EXCEPTION 'The packages of a GRN that has left draft cannot change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inventory_grn_package_guard
BEFORE INSERT OR UPDATE OR DELETE ON inventory_receiptpackage
FOR EACH ROW EXECUTE FUNCTION inventory_grn_package_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS inventory_grn_package_guard ON inventory_receiptpackage;
DROP FUNCTION IF EXISTS inventory_grn_package_guard();
"""


def qty(**extra):
    return models.DecimalField(decimal_places=3, max_digits=18, **extra)


def dec(digits, places):
    return models.DecimalField(blank=True, decimal_places=places, max_digits=digits, null=True)


class Migration(migrations.Migration):
    dependencies = [("inventory", "0002_goods_receipts")]

    operations = [
        migrations.AddField(
            model_name="item",
            name="package_tare",
            field=models.DecimalField(decimal_places=3, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="item",
            name="weight_tolerance_pct",
            field=models.DecimalField(decimal_places=2, default=Decimal("0.5"), max_digits=5),
        ),
        migrations.AddField(model_name="item", name="standard_kg_per_m", field=dec(12, 4)),
        migrations.AddField(model_name="item", name="density", field=dec(7, 3)),
        migrations.AddField(
            model_name="goodsreceiptline",
            name="weight_tolerance_pct",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=5),
        ),
        migrations.AddField(
            model_name="goodsreceiptline", name="standard_kg_per_m", field=dec(12, 4)
        ),
        migrations.AddField(model_name="goodsreceiptline", name="density", field=dec(7, 3)),
        migrations.CreateModel(
            name="ReceiptPackage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("package_no", models.PositiveIntegerField()),
                ("lot_no", models.CharField(max_length=40, unique=True)),
                ("supplier_lot", models.CharField(blank=True, max_length=50)),
                ("gross_weight", qty(blank=True, null=True)),
                ("tare_weight", qty(default=0)),
                ("net_weight", qty(blank=True, null=True)),
                ("declared_weight", qty(blank=True, null=True)),
                ("pieces", qty(blank=True, null=True)),
                ("piece_length", dec(12, 3)),
                ("length_mm", dec(10, 2)),
                ("width_mm", dec(10, 2)),
                ("thickness_mm", dec(10, 3)),
                ("quantity", qty(blank=True, null=True)),
                ("damaged", models.BooleanField(default=False)),
                ("notes", models.CharField(blank=True, max_length=200)),
                (
                    "line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="packages",
                        to="inventory.goodsreceiptline",
                    ),
                ),
            ],
            options={
                "ordering": ["line", "package_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("line", "package_no"), name="inventory_package_no"
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
