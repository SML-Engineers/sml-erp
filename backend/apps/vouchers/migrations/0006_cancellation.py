import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Cancellation (backlog P1-06, spec 4.2): the Accountant requests, the Director approves
# (a new document type in the approval matrix, level 2 = Director). The database also
# refuses:
# - cancelling a voucher that has been paid in part or in full;
# - any change to a cancelled voucher other than marking it Deleted;
# - changing the lines, splits or figures of a cancelled voucher.

FORWARD = """
CREATE OR REPLACE FUNCTION vouchers_voucher_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Voucher % cannot be deleted from the database; it is marked Deleted',
      OLD.number USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.number IS DISTINCT FROM OLD.number THEN
    RAISE EXCEPTION 'Voucher numbers never change (%)', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'deleted' THEN
    RAISE EXCEPTION 'Voucher % is deleted and cannot change', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status IN ('deleted', 'cancelled') AND OLD.status IN ('partly_paid', 'paid') THEN
    RAISE EXCEPTION 'Voucher % has payments and cannot be deleted or cancelled', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'cancelled' AND NEW.status NOT IN ('cancelled', 'deleted') THEN
    RAISE EXCEPTION 'Voucher % is cancelled for good', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('director_approved', 'partly_paid', 'paid', 'amended', 'cancelled') AND (
       NEW.payee_id IS DISTINCT FROM OLD.payee_id
    OR NEW.transfer_to_id IS DISTINCT FROM OLD.transfer_to_id
    OR NEW.voucher_type_id IS DISTINCT FROM OLD.voucher_type_id
    OR NEW.division_id IS DISTINCT FROM OLD.division_id
    OR NEW.description IS DISTINCT FROM OLD.description
    OR NEW.total_amount IS DISTINCT FROM OLD.total_amount
  ) THEN
    RAISE EXCEPTION 'Voucher % is approved and cannot be edited; amend it instead', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION vouchers_line_guard() RETURNS trigger AS $$
DECLARE
  ids BIGINT[];
BEGIN
  IF TG_TABLE_NAME = 'vouchers_voucherline' THEN
    IF TG_OP = 'INSERT' THEN
      ids := ARRAY[NEW.voucher_id];
    ELSIF TG_OP = 'UPDATE' THEN
      ids := ARRAY[OLD.voucher_id, NEW.voucher_id];
    ELSE
      ids := ARRAY[OLD.voucher_id];
    END IF;
  ELSE
    IF TG_OP = 'INSERT' THEN
      SELECT ARRAY_AGG(l.voucher_id) INTO ids FROM vouchers_voucherline l WHERE l.id = NEW.line_id;
    ELSIF TG_OP = 'UPDATE' THEN
      SELECT ARRAY_AGG(l.voucher_id) INTO ids FROM vouchers_voucherline l
        WHERE l.id IN (OLD.line_id, NEW.line_id);
    ELSE
      SELECT ARRAY_AGG(l.voucher_id) INTO ids FROM vouchers_voucherline l WHERE l.id = OLD.line_id;
    END IF;
  END IF;
  IF EXISTS (
    SELECT 1 FROM vouchers_voucher v
    WHERE v.id = ANY(ids)
      AND v.status IN (
        'director_approved', 'partly_paid', 'paid', 'amended', 'cancelled', 'deleted'
      )
  ) THEN
    RAISE EXCEPTION 'The lines of an approved or closed voucher cannot change; amend it instead'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def seed_rule(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    director = Role.objects.filter(code="director").first()
    if director and not ApprovalRule.objects.filter(document_type="voucher_cancellation").exists():
        ApprovalRule.objects.create(document_type="voucher_cancellation", level=2, role=director)


class Migration(migrations.Migration):
    dependencies = [
        ("vouchers", "0005_amendments"),
        ("core", "0014_approval_withdraw_send_down"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="VoucherCancellation",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("reason", models.CharField(max_length=500)),
                ("requested_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("pending", "Waiting for the Director"),
                            ("approved", "Approved"),
                            ("rejected", "Rejected"),
                        ],
                        default="pending",
                        max_length=10,
                    ),
                ),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("decision_reason", models.CharField(blank=True, max_length=500)),
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
                    "voucher",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="cancellations",
                        to="vouchers.voucher",
                    ),
                ),
            ],
            options={
                "ordering": ["-requested_at", "-id"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("status", "pending")),
                        fields=("voucher",),
                        name="vouchers_one_pending_cancellation",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("reason__regex", "\\S")),
                        name="vouchers_cancellation_reason",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, migrations.RunSQL.noop),
        migrations.RunPython(seed_rule, migrations.RunPython.noop),
    ]
