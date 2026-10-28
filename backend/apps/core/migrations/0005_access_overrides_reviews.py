import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_standard_roles_and_divisions"),
    ]

    operations = [
        migrations.CreateModel(
            name="AccessOverride",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("area", models.CharField(blank=True, default="", max_length=40)),
                ("level", models.CharField(blank=True, default="", max_length=10)),
                ("action", models.CharField(blank=True, default="", max_length=40)),
                (
                    "effect",
                    models.CharField(
                        choices=[("grant", "Grant"), ("remove", "Remove")], max_length=10
                    ),
                ),
                ("reason", models.TextField()),
                ("ends_on", models.DateField(blank=True, null=True)),
                ("is_sensitive", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("confirmed_at", models.DateTimeField(blank=True, null=True)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                ("revoke_reason", models.TextField(blank=True, default="")),
                ("expiry_notified_at", models.DateTimeField(blank=True, null=True)),
                (
                    "confirmed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "revoked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_overrides",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="AccessReview",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("period", models.CharField(max_length=7)),
                ("reviewed_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "outcome",
                    models.CharField(
                        choices=[
                            ("confirmed", "Confirmed as correct"),
                            ("changed", "Changed during review"),
                        ],
                        max_length=20,
                    ),
                ),
                ("note", models.TextField(blank=True, default="")),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="access_reviews",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "period"), name="core_accessreview_unique"
                    )
                ],
            },
        ),
    ]
