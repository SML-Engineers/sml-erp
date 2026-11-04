import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# The cash flow planner's "what-if" items (backlog P2-25): never posted.


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0018_close"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CashPlanItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("description", models.CharField(max_length=200)),
                ("on_date", models.DateField()),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["on_date", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("amount", 0), _negated=True),
                        name="accounting_cashplanitem_not_zero",
                    )
                ],
            },
        ),
    ]
