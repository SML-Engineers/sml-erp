from django.db import migrations, models

# Quotation limits may have no maximum value (owner's decision, 2 Nov 2026; backlog P16-16).


class Migration(migrations.Migration):
    dependencies = [("masters", "0010_costing_rates")]

    operations = [
        migrations.RemoveConstraint(model_name="quotationlimit", name="masters_limit_value_positive"),
        migrations.AlterField(
            model_name="quotationlimit",
            name="director_above_lkr",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=18,
                null=True,
                verbose_name="Director approves above (LKR)",
            ),
        ),
        migrations.AddConstraint(
            model_name="quotationlimit",
            constraint=models.CheckConstraint(
                condition=models.Q(("director_above_lkr__isnull", True))
                | models.Q(("director_above_lkr__gt", 0)),
                name="masters_limit_value_positive",
            ),
        ),
    ]
