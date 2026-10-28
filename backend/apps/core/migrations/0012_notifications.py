import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Notifications (backlog P0-18): the bell, emails and each user's choices; and the title and
# link by which notifications name a document waiting for approval.


def big_id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0011_approval_engine"),
    ]

    operations = [
        migrations.AddField(
            model_name="approvalstate",
            name="title",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="approvalstate",
            name="link",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", big_id()),
                ("event", models.SlugField(max_length=40)),
                ("title", models.CharField(max_length=200)),
                ("body", models.TextField(blank=True)),
                ("link", models.CharField(blank=True, max_length=200)),
                ("document_type", models.SlugField(blank=True, max_length=30)),
                ("document_id", models.BigIntegerField(blank=True, null=True)),
                ("in_app", models.BooleanField(default=True)),
                ("email", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("emailed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "indexes": [
                    models.Index(fields=["user", "read_at"], name="core_notification_unread"),
                ],
            },
        ),
        migrations.CreateModel(
            name="NotificationPreference",
            fields=[
                ("id", big_id()),
                ("event", models.SlugField(max_length=40)),
                ("in_app", models.BooleanField(default=True)),
                ("email", models.BooleanField(default=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_preferences",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "event"), name="core_notificationpref_unique"
                    ),
                ],
            },
        ),
    ]
