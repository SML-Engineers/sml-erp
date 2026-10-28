import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# The shared approval engine (backlog P0-17, spec 3).
#
# The database itself refuses, whatever the application does:
# - changing or removing an approval log row (rule 7);
# - a Return or Reject without a reason;
# - an approval by the document's creator, by someone who submitted it, or by someone who
#   already approved it at another level (rule 5).
#
# Starting matrix: vouchers go to the Accountant (L2), then the Director (L3), whatever
# their type or amount (rule 6).

FORWARD = """
CREATE TRIGGER core_approvallog_insert_only
BEFORE UPDATE OR DELETE ON core_approvallog
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE OR REPLACE FUNCTION core_approval_duties() RETURNS trigger AS $$
BEGIN
  IF NEW.action <> 'approve' THEN
    RETURN NEW;
  END IF;
  IF EXISTS (
    SELECT 1 FROM core_approvalstate s
    WHERE s.document_type = NEW.document_type AND s.document_id = NEW.document_id
      AND s.created_by_id = NEW.user_id
  ) OR EXISTS (
    SELECT 1 FROM core_approvallog l
    WHERE l.document_type = NEW.document_type AND l.document_id = NEW.document_id
      AND l.user_id = NEW.user_id AND l.action = 'submit'
  ) THEN
    RAISE EXCEPTION 'A user cannot approve a document they created or submitted'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  IF EXISTS (
    SELECT 1 FROM core_approvallog l
    WHERE l.document_type = NEW.document_type AND l.document_id = NEW.document_id
      AND l.user_id = NEW.user_id AND l.action = 'approve' AND l.level <> NEW.level
  ) THEN
    RAISE EXCEPTION 'A user cannot approve the same document at two levels'
      USING ERRCODE = 'insufficient_privilege';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER core_approvallog_duties
BEFORE INSERT ON core_approvallog
FOR EACH ROW EXECUTE FUNCTION core_approval_duties();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS core_approvallog_duties ON core_approvallog;
DROP FUNCTION IF EXISTS core_approval_duties();
DROP TRIGGER IF EXISTS core_approvallog_insert_only ON core_approvallog;
"""

MATRIX_V1 = [("voucher", 2, "accountant"), ("voucher", 3, "director")]


def load(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    for document_type, level, role_code in MATRIX_V1:
        role = Role.objects.filter(code=role_code).first()
        if role and not ApprovalRule.objects.filter(
            document_type=document_type, level=level
        ).exists():
            ApprovalRule.objects.create(document_type=document_type, level=level, role=role)


def big_id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_invoice_numbering"),
    ]

    operations = [
        migrations.CreateModel(
            name="ApprovalRule",
            fields=[
                ("id", big_id()),
                ("document_type", models.SlugField(max_length=30)),
                ("level", models.PositiveSmallIntegerField()),
                (
                    "min_amount",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
                ),
                (
                    "max_amount",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
                ),
                ("subtype", models.CharField(blank=True, max_length=30)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "division",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approval_rules",
                        to="core.division",
                    ),
                ),
                (
                    "role",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="approval_rules",
                        to="core.role",
                    ),
                ),
            ],
            options={
                "ordering": ["document_type", "level", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("level__gte", 2), ("level__lte", 9)),
                        name="core_approvalrule_level_range",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("min_amount__isnull", True),
                            ("max_amount__isnull", True),
                            ("min_amount__lte", models.F("max_amount")),
                            _connector="OR",
                        ),
                        name="core_approvalrule_amount_range",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ApprovalState",
            fields=[
                ("id", big_id()),
                ("document_type", models.SlugField(max_length=30)),
                ("document_id", models.BigIntegerField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("in_progress", "Waiting for approval"),
                            ("approved", "Approved"),
                            ("returned", "Returned"),
                            ("rejected", "Rejected"),
                        ],
                        max_length=20,
                    ),
                ),
                ("current_level", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("route", models.JSONField(default=list)),
                ("round", models.PositiveSmallIntegerField(default=1)),
                (
                    "amount",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
                ),
                ("subtype", models.CharField(blank=True, max_length=30)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "division",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.division",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("document_type", "document_id"), name="core_approvalstate_unique"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("current_level__isnull", False), ("status", "in_progress")),
                            models.Q(
                                models.Q(("status", "in_progress"), _negated=True),
                                ("current_level__isnull", True),
                            ),
                            _connector="OR",
                        ),
                        name="core_approvalstate_level_when_waiting",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ApprovalLog",
            fields=[
                ("id", big_id()),
                ("document_type", models.SlugField(max_length=30)),
                ("document_id", models.BigIntegerField()),
                ("round", models.PositiveSmallIntegerField()),
                ("level", models.PositiveSmallIntegerField()),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("submit", "Submitted"),
                            ("approve", "Approved"),
                            ("return", "Returned"),
                            ("reject", "Rejected"),
                        ],
                        max_length=10,
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("acted_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["acted_at", "id"],
                "indexes": [
                    models.Index(
                        fields=["document_type", "document_id"], name="core_approvallog_doc"
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("action__in", ["return", "reject"]), _negated=True),
                            ("reason__regex", "\\S"),
                            _connector="OR",
                        ),
                        name="core_approvallog_reason_required",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(load, migrations.RunPython.noop),
    ]
