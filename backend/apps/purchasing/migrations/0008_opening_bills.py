from django.db import migrations, models

# Bills open in QuickBooks at go-live (backlog P2-28), marked "opening".


class Migration(migrations.Migration):
    dependencies = [("purchasing", "0007_purchase_requests")]

    operations = [
        migrations.AddField(
            model_name="supplierinvoice",
            name="opening",
            field=models.BooleanField(default=False),
        ),
    ]
