import django.db.models.deletion
from django.db import migrations, models

# Each company bank or cash account is linked to its ledger account (backlog P0-15).


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0002_starter_chart"),
        ("masters", "0007_company_accounts"),
    ]

    operations = [
        migrations.AddField(
            model_name="companyaccount",
            name="ledger_account",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="company_account",
                to="accounting.account",
            ),
        ),
    ]
