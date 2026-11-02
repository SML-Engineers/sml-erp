from django.db import migrations, models

# Invoice price differences adjust the value of goods still in stock (IAS 2; backlog P16-18):
# a value-only movement, the one kind of movement with no quantity.


class Migration(migrations.Migration):
    dependencies = [("inventory", "0007_opening_stock")]

    operations = [
        migrations.AlterField(
            model_name="stockmovement",
            name="kind",
            field=models.CharField(
                choices=[
                    ("received", "Received into quarantine"),
                    ("damaged", "Received damaged"),
                    ("accepted", "Accepted by QC"),
                    ("rejected", "Rejected by QC"),
                    ("reversed", "GRN reversed"),
                    ("returned", "Returned to the supplier"),
                    ("opening", "Opening stock"),
                    ("price_diff", "Invoice price difference"),
                ],
                max_length=10,
            ),
        ),
        migrations.RemoveConstraint(model_name="stockmovement", name="inventory_movement_not_zero"),
        migrations.AddConstraint(
            model_name="stockmovement",
            constraint=models.CheckConstraint(
                condition=~models.Q(("quantity", 0))
                | (models.Q(("kind", "price_diff")) & ~models.Q(("value", 0))),
                name="inventory_movement_not_zero",
            ),
        ),
    ]
