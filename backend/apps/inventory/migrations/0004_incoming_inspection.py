import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Incoming inspection (backlog P16-08, spec 6A.3, 6A.4).
# - Inspection plans per item or per category, with measured or pass/fail checks.
# - One inspection per GRN line; the checks are copied from the plan when it starts.
# - Accepting material that fails a critical check is a deviation the Director approves
#   (owner, 1 Nov 2026), document type "quality_deviation".
# - A decided inspection never changes; its results, rejected packages and attachments only
#   change while it is being inspected (certificates may still be added afterwards).


def seed(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="quality_deviation").exists():
        ApprovalRule.objects.create(document_type="quality_deviation", level=2, role=director)
    ApprovalReminder.objects.get_or_create(
        document_type="quality_deviation", defaults={"enabled": True, "after_days": 1}
    )


FORWARD = """
CREATE OR REPLACE FUNCTION inventory_inspection_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.status <> 'draft' THEN
      RAISE EXCEPTION 'A decided inspection cannot be deleted' USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
  END IF;
  IF OLD.status = 'decided' THEN
    RAISE EXCEPTION 'A decided inspection cannot be changed' USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'deviation_requested' AND (
       NEW.line_id IS DISTINCT FROM OLD.line_id
    OR NEW.accepted_quantity IS DISTINCT FROM OLD.accepted_quantity
    OR NEW.rejected_quantity IS DISTINCT FROM OLD.rejected_quantity
    OR NEW.notes IS DISTINCT FROM OLD.notes
    OR NEW.reason IS DISTINCT FROM OLD.reason
    OR NEW.inspector_id IS DISTINCT FROM OLD.inspector_id
  ) THEN
    RAISE EXCEPTION 'An inspection waiting for the Director cannot be changed'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION inventory_inspection_child_guard() RETURNS trigger AS $$
DECLARE
  st TEXT;
BEGIN
  SELECT i.status INTO st FROM inventory_incominginspection i
   WHERE i.id = CASE WHEN TG_OP = 'INSERT' THEN NEW.inspection_id ELSE OLD.inspection_id END;
  IF st IS NOT NULL AND st <> 'draft' THEN
    RAISE EXCEPTION 'The results of an inspection that has left draft cannot change'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER inventory_inspection_guard
BEFORE UPDATE OR DELETE ON inventory_incominginspection
FOR EACH ROW EXECUTE FUNCTION inventory_inspection_guard();

CREATE TRIGGER inventory_inspection_result_guard
BEFORE INSERT OR UPDATE OR DELETE ON inventory_inspectionresult
FOR EACH ROW EXECUTE FUNCTION inventory_inspection_child_guard();

CREATE TRIGGER inventory_rejected_package_guard
BEFORE INSERT OR UPDATE OR DELETE ON inventory_rejectedpackage
FOR EACH ROW EXECUTE FUNCTION inventory_inspection_child_guard();

CREATE TRIGGER inventory_inspection_attachment_guard
BEFORE UPDATE OR DELETE ON inventory_inspectionattachment
FOR EACH ROW EXECUTE FUNCTION inventory_inspection_child_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS inventory_inspection_attachment_guard ON inventory_inspectionattachment;
DROP TRIGGER IF EXISTS inventory_rejected_package_guard ON inventory_rejectedpackage;
DROP TRIGGER IF EXISTS inventory_inspection_result_guard ON inventory_inspectionresult;
DROP TRIGGER IF EXISTS inventory_inspection_guard ON inventory_incominginspection;
DROP FUNCTION IF EXISTS inventory_inspection_child_guard();
DROP FUNCTION IF EXISTS inventory_inspection_guard();
"""


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


def dec(**extra):
    return models.DecimalField(blank=True, decimal_places=4, max_digits=18, null=True, **extra)


def user(null=False):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to=settings.AUTH_USER_MODEL,
        **extra,
    )


CATEGORIES = [
    ("raw_material", "Raw material"),
    ("bought_out", "Bought-out part"),
    ("consumable", "Consumable"),
    ("spare", "Spare part"),
    ("packing", "Packing material"),
]
KINDS = [("number", "Measured (min and max)"), ("pass_fail", "Pass or fail")]


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0003_receipt_packages"),
        ("core", "0019_purchasing_roles"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InspectionPlan",
            fields=[
                id_field(),
                ("name", models.CharField(max_length=100)),
                ("category", models.CharField(blank=True, choices=CATEGORIES, max_length=20)),
                (
                    "sampling",
                    models.CharField(
                        choices=[
                            ("all", "Every package"),
                            ("fixed", "A fixed number of packages"),
                            ("percent", "A percentage of the packages"),
                        ],
                        default="all",
                        max_length=10,
                    ),
                ),
                (
                    "sample_value",
                    models.DecimalField(blank=True, decimal_places=2, max_digits=7, null=True),
                ),
                ("notes", models.TextField(blank=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", user()),
                (
                    "item",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="inventory.item",
                    ),
                ),
            ],
            options={
                "ordering": ["name"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("item__isnull", False), ("category", "")),
                            models.Q(("item__isnull", True), models.Q(("category", ""), _negated=True)),
                            _connector="OR",
                        ),
                        name="inventory_plan_item_or_category",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("is_active", True), ("item__isnull", False)),
                        fields=("item",),
                        name="inventory_one_plan_per_item",
                    ),
                    models.UniqueConstraint(
                        condition=models.Q(("is_active", True), ("item__isnull", True)),
                        fields=("category",),
                        name="inventory_one_plan_per_category",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="InspectionParameter",
            fields=[
                id_field(),
                ("position", models.PositiveSmallIntegerField()),
                ("name", models.CharField(max_length=100)),
                ("kind", models.CharField(choices=KINDS, max_length=10)),
                ("minimum", dec()),
                ("maximum", dec()),
                ("unit", models.CharField(blank=True, max_length=20)),
                ("critical", models.BooleanField(default=False)),
                (
                    "plan",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="parameters",
                        to="inventory.inspectionplan",
                    ),
                ),
            ],
            options={"ordering": ["plan", "position"]},
        ),
        migrations.CreateModel(
            name="IncomingInspection",
            fields=[
                id_field(),
                ("sample_size", models.PositiveIntegerField(default=1)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Being inspected"),
                            ("deviation_requested", "Deviation waiting for the Director"),
                            ("decided", "Decided"),
                        ],
                        default="draft",
                        max_length=20,
                    ),
                ),
                (
                    "decision",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("accepted", "Accepted"),
                            ("rejected", "Rejected"),
                            ("deviation", "Accepted under deviation"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "accepted_quantity",
                    models.DecimalField(decimal_places=3, default=0, max_digits=18),
                ),
                (
                    "rejected_quantity",
                    models.DecimalField(decimal_places=3, default=0, max_digits=18),
                ),
                ("notes", models.TextField(blank=True)),
                ("reason", models.TextField(blank=True)),
                ("automatic", models.BooleanField(default=False)),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("inspector", user(null=True)),
                (
                    "line",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="inspection",
                        to="inventory.goodsreceiptline",
                    ),
                ),
                (
                    "plan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="inventory.inspectionplan",
                    ),
                ),
            ],
            options={"ordering": ["-started_at"]},
        ),
        migrations.CreateModel(
            name="InspectionResult",
            fields=[
                id_field(),
                ("position", models.PositiveSmallIntegerField()),
                ("name", models.CharField(max_length=100)),
                ("kind", models.CharField(choices=KINDS, max_length=10)),
                ("minimum", dec()),
                ("maximum", dec()),
                ("unit", models.CharField(blank=True, max_length=20)),
                ("critical", models.BooleanField(default=False)),
                ("value", dec()),
                ("passed", models.BooleanField(blank=True, null=True)),
                ("within_limits", models.BooleanField(blank=True, null=True)),
                ("notes", models.CharField(blank=True, max_length=300)),
                (
                    "inspection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="results",
                        to="inventory.incominginspection",
                    ),
                ),
            ],
            options={"ordering": ["inspection", "position"]},
        ),
        migrations.CreateModel(
            name="RejectedPackage",
            fields=[
                id_field(),
                (
                    "inspection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rejected_packages",
                        to="inventory.incominginspection",
                    ),
                ),
                (
                    "package",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rejection",
                        to="inventory.receiptpackage",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="InspectionAttachment",
            fields=[
                id_field(),
                ("file", models.FileField(upload_to="inspections/%Y/%m/")),
                ("file_name", models.CharField(max_length=200)),
                ("content_type", models.CharField(max_length=100)),
                ("size", models.PositiveIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("uploaded_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "inspection",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="attachments",
                        to="inventory.incominginspection",
                    ),
                ),
                ("uploaded_by", user()),
            ],
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
