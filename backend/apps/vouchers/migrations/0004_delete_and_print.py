import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Deleting and printing vouchers (backlog P1-04b, spec 4.4). The database also refuses:
# - deleting a voucher that has been paid in part or in full (the payments task, P1-07, adds
#   the same check against the payments themselves);
# - any change to a voucher once it is marked Deleted;
# - changing or removing a print record.

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
  IF NEW.status = 'deleted' AND OLD.status IN ('partly_paid', 'paid') THEN
    RAISE EXCEPTION 'Voucher % has payments and cannot be deleted', OLD.number
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vouchers_print_insert_only
BEFORE UPDATE OR DELETE ON vouchers_voucherprint
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS vouchers_print_insert_only ON vouchers_voucherprint;
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
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("vouchers", "0003_coding"),
        ("core", "0014_approval_withdraw_send_down"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="voucher",
            name="deleted_at",
            field=models.DateTimeField(blank=True, editable=False, null=True),
        ),
        migrations.AddField(
            model_name="voucher",
            name="deleted_by",
            field=models.ForeignKey(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="voucher",
            name="delete_reason",
            field=models.CharField(blank=True, editable=False, max_length=500),
        ),
        migrations.AddConstraint(
            model_name="voucher",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(("status", "deleted"), _negated=True),
                    models.Q(("deleted_at__isnull", False), ("deleted_by__isnull", False)),
                    _connector="OR",
                ),
                name="vouchers_voucher_deleted_who",
            ),
        ),
        migrations.CreateModel(
            name="VoucherPrint",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("printed_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "paper",
                    models.CharField(choices=[("A4", "A4"), ("A5", "A5")], default="A4", max_length=2),
                ),
                ("is_copy", models.BooleanField(default=False)),
                (
                    "printed_by",
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
                        related_name="prints",
                        to="vouchers.voucher",
                    ),
                ),
            ],
            options={"ordering": ["printed_at", "id"]},
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
