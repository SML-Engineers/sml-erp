import django.db.models.deletion
from django.db import migrations, models

# The Accountant's coding (backlog P1-03): a job or production order reference per line, and
# division splits of shared bills.


class Migration(migrations.Migration):
    dependencies = [
        ("vouchers", "0002_vouchers"),
    ]

    operations = [
        migrations.AddField(
            model_name="voucherline",
            name="job_ref",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.CreateModel(
            name="VoucherLineSplit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                (
                    "percent",
                    models.DecimalField(blank=True, decimal_places=4, max_digits=7, null=True),
                ),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.division",
                    ),
                ),
                (
                    "line",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="splits",
                        to="vouchers.voucherline",
                    ),
                ),
            ],
            options={
                "ordering": ["line", "id"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("line", "division"), name="vouchers_split_division"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("amount__gt", 0)), name="vouchers_split_amount"
                    ),
                ],
            },
        ),
    ]
