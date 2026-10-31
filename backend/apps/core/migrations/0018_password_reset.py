import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Password resets (owner's decision, 31 Oct 2026): the Admin requests, the Director approves,
# then the Admin makes a temporary password shown once.


class Migration(migrations.Migration):
    dependencies = [("core", "0017_receipt_action")]

    operations = [
        migrations.CreateModel(
            name="PasswordReset",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("with_authenticator", models.BooleanField(default=False)),
                ("reason", models.TextField()),
                ("requested_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("approved", models.BooleanField(blank=True, null=True)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_reason", models.TextField(blank=True, default="")),
                ("issued_at", models.DateTimeField(blank=True, null=True)),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="password_resets",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-requested_at", "-id"]},
        ),
    ]
