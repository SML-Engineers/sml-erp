from django.db import migrations, models

# Goods returned to the supplier leave the store as "returned" movements (backlog P16-12).


class Migration(migrations.Migration):
    dependencies = [("inventory", "0005_stock_movements")]

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
                ],
                max_length=10,
            ),
        ),
    ]
