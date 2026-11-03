import django.db.models.deletion
from django.db import migrations, models

# Withholding tax on payments (backlog P2-12): a voucher line may carry a "withheld" tax
# component, its rate and the tax kept back; the voucher keeps the total. Existing rows get
# no WHT. Built switched off: nothing is withheld until the tax has a confirmed rate.


class Migration(migrations.Migration):
    dependencies = [
        ("vouchers", "0010_advance_payments"),
        ("accounting", "0014_zero_rated_code"),
    ]

    operations = [
        migrations.AddField(
            model_name="voucher",
            name="wht_total",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AddField(
            model_name="voucherline",
            name="wht_component",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="accounting.taxcomponent",
            ),
        ),
        migrations.AddField(
            model_name="voucherline",
            name="wht_rate",
            field=models.DecimalField(decimal_places=4, default=0, max_digits=7),
        ),
        migrations.AddField(
            model_name="voucherline",
            name="wht_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=18),
        ),
        migrations.AddConstraint(
            model_name="voucher",
            constraint=models.CheckConstraint(
                condition=models.Q(wht_total__gte=0)
                & models.Q(wht_total__lte=models.F("total_amount")),
                name="vouchers_voucher_wht",
            ),
        ),
        migrations.AddConstraint(
            model_name="voucherline",
            constraint=models.CheckConstraint(
                condition=models.Q(wht_amount__gte=0)
                & models.Q(wht_amount__lte=models.F("amount")),
                name="vouchers_line_wht",
            ),
        ),
        migrations.AddConstraint(
            model_name="voucherline",
            constraint=models.CheckConstraint(
                condition=models.Q(wht_component__isnull=False) | models.Q(wht_amount=0),
                name="vouchers_line_wht_component",
            ),
        ),
    ]
