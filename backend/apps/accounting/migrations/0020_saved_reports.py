import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Reports saved in the report builder (backlog P2-26).


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0019_cash_plan"),
        ("core", "0026_sentemail_other_attachments"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SavedReport",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("name", models.CharField(max_length=100)),
                ("definition", models.JSONField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "shared_role",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="core.role",
                    ),
                ),
            ],
            options={"ordering": ["name", "id"]},
        ),
    ]
