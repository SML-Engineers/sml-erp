import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# Reminders for documents waiting too long for approval (backlog P1-09, spec 4.3): one
# setting per document type, kept by the Admin on the approval matrix page. Vouchers and
# voucher cancellations start with reminders on, after 3 days.

STARTING = [("voucher", True, 3), ("voucher_cancellation", True, 3)]


def seed(apps, schema_editor):
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    for document_type, enabled, days in STARTING:
        ApprovalReminder.objects.get_or_create(
            document_type=document_type, defaults={"enabled": enabled, "after_days": days}
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0014_approval_withdraw_send_down"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ApprovalReminder",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("document_type", models.SlugField(max_length=30, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("after_days", models.PositiveSmallIntegerField(default=3)),
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
            options={
                "ordering": ["document_type"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("after_days__gte", 1), ("after_days__lte", 60)),
                        name="core_approvalreminder_days",
                    ),
                ],
            },
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
