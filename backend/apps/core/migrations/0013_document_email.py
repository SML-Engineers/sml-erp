import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

from apps.core.email_catalogue import DEFAULT_TEMPLATES_V1

# Sending documents and reports by email (spec 3B, backlog P0-19): the sending mailbox, the
# default messages, and the record of every email sent, which nobody can change or delete.

FORWARD = """
CREATE TRIGGER core_sentemail_insert_only
BEFORE UPDATE OR DELETE ON core_sentemail
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS core_sentemail_insert_only ON core_sentemail;
"""


def load(apps, schema_editor):
    MailAccount = apps.get_model("core", "MailAccount")
    EmailTemplate = apps.get_model("core", "EmailTemplate")
    MailAccount.objects.get_or_create(pk=1)
    for kind, (subject, body) in DEFAULT_TEMPLATES_V1.items():
        EmailTemplate.objects.get_or_create(
            document_type=kind, defaults={"subject": subject, "body": body}
        )


def big_id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_notifications"),
    ]

    operations = [
        migrations.CreateModel(
            name="MailAccount",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("from_name", models.CharField(blank=True, max_length=100)),
                ("from_address", models.EmailField(blank=True, max_length=254)),
                ("reply_to", models.EmailField(blank=True, max_length=254)),
                ("copy_to", models.EmailField(blank=True, max_length=254)),
                ("host", models.CharField(blank=True, max_length=200)),
                ("port", models.PositiveIntegerField(default=587)),
                (
                    "security",
                    models.CharField(
                        choices=[
                            ("starttls", "STARTTLS (usually port 587)"),
                            ("ssl", "SSL/TLS (usually port 465)"),
                            ("none", "None (only for a mail server on the same machine)"),
                        ],
                        default="starttls",
                        max_length=10,
                    ),
                ),
                ("username", models.CharField(blank=True, max_length=200)),
                ("password_encrypted", models.TextField(blank=True)),
                ("last_test_at", models.DateTimeField(blank=True, null=True)),
                ("last_test_ok", models.BooleanField(blank=True, null=True)),
                ("last_test_error", models.CharField(blank=True, max_length=500)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("id", 1)), name="core_mailaccount_single_row"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="EmailTemplate",
            fields=[
                ("id", big_id()),
                ("document_type", models.SlugField(max_length=30, unique=True)),
                ("subject", models.CharField(max_length=200)),
                ("body", models.TextField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "updated_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["document_type"]},
        ),
        migrations.CreateModel(
            name="SentEmail",
            fields=[
                ("id", big_id()),
                ("document_type", models.SlugField(max_length=30)),
                ("document_id", models.BigIntegerField(blank=True, null=True)),
                ("document_label", models.CharField(max_length=200)),
                ("from_address", models.CharField(max_length=300)),
                ("to", models.TextField()),
                ("cc", models.TextField(blank=True)),
                ("bcc", models.TextField(blank=True)),
                ("subject", models.CharField(max_length=200)),
                ("body", models.TextField()),
                (
                    "attachment",
                    models.FileField(blank=True, upload_to="sent-emails/%Y/%m/"),
                ),
                ("attachment_name", models.CharField(blank=True, max_length=200)),
                ("attachment_sha256", models.CharField(blank=True, max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[("sent", "Sent"), ("failed", "Failed")], max_length=10
                    ),
                ),
                ("error", models.CharField(blank=True, max_length=500)),
                ("sent_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "sent_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-sent_at", "-id"],
                "indexes": [
                    models.Index(
                        fields=["document_type", "document_id"], name="core_sentemail_doc"
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(load, migrations.RunPython.noop),
    ]
