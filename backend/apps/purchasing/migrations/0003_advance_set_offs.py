import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Advances set off against supplier invoices (backlog P16-11a): insert-only, like the
# journal entries they post.

FORWARD = """
CREATE OR REPLACE FUNCTION purchasing_setoff_guard() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'An advance set-off is never changed or deleted; post a correction'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION purchasing_setoff_limits() RETURNS trigger AS $$
DECLARE
  inv RECORD;
  line_total numeric;
  used_line numeric;
  used_invoice numeric;
  on_vouchers numeric;
BEGIN
  SELECT * INTO inv FROM purchasing_supplierinvoice WHERE id = NEW.invoice_id FOR UPDATE;
  SELECT l.amount + l.tax_amount INTO line_total FROM vouchers_voucherline l
   WHERE l.id = NEW.voucher_line_id;
  SELECT coalesce(sum(amount), 0) INTO used_line FROM purchasing_advancesetoff
   WHERE voucher_line_id = NEW.voucher_line_id;
  SELECT coalesce(sum(amount), 0) INTO used_invoice FROM purchasing_advancesetoff
   WHERE invoice_id = NEW.invoice_id;
  SELECT coalesce(sum(l.amount + l.tax_amount), 0) INTO on_vouchers
    FROM vouchers_voucherline l JOIN vouchers_voucher v ON v.id = l.voucher_id
   WHERE l.supplier_invoice_id = NEW.invoice_id
     AND v.status NOT IN ('deleted', 'rejected', 'amended', 'cancelled');
  IF used_line + NEW.amount > line_total
     OR used_invoice + on_vouchers + NEW.amount > inv.total_lkr THEN
    RAISE EXCEPTION 'The set-off is more than the advance or the invoice still owes'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER purchasing_setoff_limits
BEFORE INSERT ON purchasing_advancesetoff
FOR EACH ROW EXECUTE FUNCTION purchasing_setoff_limits();

CREATE TRIGGER purchasing_setoff_guard
BEFORE UPDATE OR DELETE ON purchasing_advancesetoff
FOR EACH ROW EXECUTE FUNCTION purchasing_setoff_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS purchasing_setoff_guard ON purchasing_advancesetoff;
DROP TRIGGER IF EXISTS purchasing_setoff_limits ON purchasing_advancesetoff;
DROP FUNCTION IF EXISTS purchasing_setoff_limits();
DROP FUNCTION IF EXISTS purchasing_setoff_guard();
"""


def fk(to, related_name="+"):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to
    )


class Migration(migrations.Migration):
    dependencies = [
        ("purchasing", "0002_supplier_invoices"),
        ("vouchers", "0010_advance_payments"),
        ("accounting", "0007_supplier_advances_role"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AdvanceSetOff",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("created_by", fk(settings.AUTH_USER_MODEL)),
                ("invoice", fk("purchasing.supplierinvoice", "set_offs")),
                ("journal_entry", fk("accounting.journalentry")),
                ("voucher_line", fk("vouchers.voucherline", "set_offs")),
            ],
            options={
                "ordering": ["created_at", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("amount__gt", 0)), name="purchasing_setoff_amount"
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
