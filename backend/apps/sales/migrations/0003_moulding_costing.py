import django.db.models.deletion
from django.db import migrations, models

# Moulding costing and tooling (backlog P15-05, spec 5.1): resin and masterbatch, the press
# and its cycle, rejects, packing and the mould; tooling lines charged once.


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0010_costing_rates"),
        ("sales", "0002_costing"),
    ]

    operations = [
        migrations.AddField(
            model_name="quotationline",
            name="is_tooling",
            field=models.BooleanField(default=False, verbose_name="Tooling (charged once)"),
        ),
        migrations.AlterField(
            model_name="quotationcosting",
            name="method",
            field=models.CharField(
                choices=[("machining", "Machining"), ("moulding", "Moulding")],
                default="machining",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="masterbatch",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="masters.material",
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="masterbatch_rate",
            field=money(blank=True, null=True, verbose_name="Masterbatch price per kg (LKR)"),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="masterbatch_pct",
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=5, verbose_name="Masterbatch %"
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="part_weight_g",
            field=models.DecimalField(
                blank=True, decimal_places=3, max_digits=12, null=True, verbose_name="Part weight (g)"
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="runner_weight_g",
            field=models.DecimalField(
                blank=True,
                decimal_places=3,
                max_digits=12,
                null=True,
                verbose_name="Runner weight per shot (g)",
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="cavities",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="machine",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="masters.machine",
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="machine_rate",
            field=money(blank=True, null=True, verbose_name="Machine hourly rate (LKR)"),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="cycle_time_s",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=8, null=True, verbose_name="Cycle time (s)"
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="reject_pct",
            field=models.DecimalField(
                decimal_places=2, default=0, max_digits=5, verbose_name="Reject %"
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="packing_amount",
            field=money(default=0, verbose_name="Packing (LKR)"),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="packing_per",
            field=models.CharField(
                choices=[("piece", "Per piece"), ("carton", "Per carton")],
                default="piece",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="pcs_per_carton",
            field=models.PositiveIntegerField(
                blank=True, null=True, verbose_name="Pieces per carton"
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="tooling",
            field=models.CharField(
                choices=[
                    ("none", "No tooling"),
                    ("separate", "Charged once, as its own line"),
                    ("amortised", "Spread over a quantity"),
                    ("customer", "Owned by the customer"),
                ],
                default="none",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="tooling_cost",
            field=money(default=0, verbose_name="Tooling cost (LKR)"),
        ),
        migrations.AddField(
            model_name="quotationcosting",
            name="tooling_qty",
            field=models.DecimalField(
                blank=True,
                decimal_places=3,
                max_digits=18,
                null=True,
                verbose_name="Tooling spread over (pieces)",
            ),
        ),
        migrations.AddConstraint(
            model_name="quotationcosting",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("masterbatch_pct__gte", 0),
                    ("reject_pct__gte", 0),
                    ("reject_pct__lt", 100),
                    ("packing_amount__gte", 0),
                    ("tooling_cost__gte", 0),
                ),
                name="sales_costing_moulding_not_negative",
            ),
        ),
    ]
