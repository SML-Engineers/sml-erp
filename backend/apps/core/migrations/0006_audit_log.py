import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# The audit log is evidence: once written, a row can never be changed or removed. Reuses the
# refusal function created for the sign-in history (migration 0002).
FORWARD = """
CREATE TRIGGER core_auditevent_insert_only
BEFORE UPDATE OR DELETE ON core_auditevent
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
"""

BACKWARD = "DROP TRIGGER IF EXISTS core_auditevent_insert_only ON core_auditevent;"


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_access_overrides_reviews"),
    ]

    operations = [
        migrations.CreateModel(
            name="AuditEvent",
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
                ("actor_email", models.CharField(blank=True, default="", max_length=254)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("create", "Created"),
                            ("update", "Changed"),
                            ("delete", "Deleted"),
                        ],
                        max_length=10,
                    ),
                ),
                ("object_type", models.CharField(max_length=100)),
                ("object_id", models.CharField(max_length=64)),
                ("object_repr", models.CharField(blank=True, default="", max_length=255)),
                ("event", models.CharField(blank=True, default="", max_length=50)),
                ("reason", models.TextField(blank=True, default="")),
                ("changes", models.JSONField(blank=True, default=dict)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "related_user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audit_events",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-occurred_at", "-id"],
                "indexes": [
                    models.Index(fields=["object_type", "object_id"], name="core_audit_object")
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
