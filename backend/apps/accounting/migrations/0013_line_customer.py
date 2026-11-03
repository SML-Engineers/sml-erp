import django.db.models.deletion
from django.db import migrations, models

# The customer on accounts receivable lines (backlog P2-05): tax invoices post Dr Accounts
# receivable with the customer, so customer balances, statements and aging (P2-07, P2-08) come
# from the ledger.


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0012_recurring_journals"),
        ("masters", "0011_limit_no_maximum"),
    ]

    operations = [
        migrations.AddField(
            model_name="journalline",
            name="customer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="journal_lines",
                to="masters.customer",
            ),
        ),
    ]
