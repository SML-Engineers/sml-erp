import django.db.models.deletion
from django.db import migrations, models

# Invoices open in QuickBooks at go-live (backlog P2-28): no sales order, marked "opening".


class Migration(migrations.Migration):
    dependencies = [("sales", "0017_invoice_tracking")]

    operations = [
        migrations.AlterField(
            model_name="taxinvoice",
            name="order",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="invoices",
                to="sales.salesorder",
            ),
        ),
        migrations.AddField(
            model_name="taxinvoice",
            name="opening",
            field=models.BooleanField(default=False),
        ),
    ]
