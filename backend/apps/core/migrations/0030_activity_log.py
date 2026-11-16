import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Owner, 14 Nov 2026: the activity log level and the record of views and downloads. Like the
# audit log, the record is evidence: once written, a row can never be changed or removed
# (reuses the refusal function of migration 0002).
FORWARD = """
CREATE TRIGGER core_activityevent_insert_only
BEFORE UPDATE OR DELETE ON core_activityevent
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
"""

BACKWARD = "DROP TRIGGER IF EXISTS core_activityevent_insert_only ON core_activityevent;"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0029_role_requests"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="activity_log_level",
            field=models.CharField(
                choices=[
                    ("changes", "Changes and sign-ins only"),
                    ("sensitive", "Sensitive views and every download"),
                    ("everything", "Everything"),
                ],
                default="sensitive",
                max_length=12,
                verbose_name="Activity log level",
            ),
        ),
        migrations.CreateModel(
            name="ActivityEvent",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "occurred_at",
                    models.DateTimeField(db_index=True, default=django.utils.timezone.now),
                ),
                ("user_email", models.CharField(blank=True, default="", max_length=254)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "kind",
                    models.CharField(
                        choices=[("view", "Viewed"), ("download", "Downloaded")], max_length=10
                    ),
                ),
                (
                    "category",
                    models.CharField(
                        choices=[
                            ("payslip", "Payslips"),
                            ("salary", "Salaries and pay"),
                            ("bank", "Bank details"),
                            ("other", "Other"),
                        ],
                        max_length=10,
                    ),
                ),
                ("path", models.CharField(max_length=300)),
                ("file_name", models.CharField(blank=True, default="", max_length=255)),
                ("level", models.CharField(max_length=12)),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-occurred_at", "-id"]},
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
