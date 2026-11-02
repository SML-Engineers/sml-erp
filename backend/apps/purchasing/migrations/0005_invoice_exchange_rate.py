from django.db import migrations, models

# A supplier invoice in a foreign currency is posted at the rate of its date (IAS 21; backlog
# P16-19). Posted invoices never change (purchasing 0002), so the rate is set when posting.


class Migration(migrations.Migration):
    dependencies = [("purchasing", "0004_supplier_returns")]

    operations = [
        migrations.AddField(
            model_name="supplierinvoice",
            name="exchange_rate",
            field=models.DecimalField(blank=True, decimal_places=6, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name="supplierinvoice",
            name="rate_date",
            field=models.DateField(blank=True, null=True),
        ),
    ]
