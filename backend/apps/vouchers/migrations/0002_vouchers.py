import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Vouchers, their lines and scanned attachments (backlog P1-02, spec 4.5). The database
# refuses:
# - changing a voucher's number, or deleting a voucher (a deleted voucher keeps its row and
#   number with the status Deleted, P1-04b);
# - changing an attachment, or removing one once the voucher has left Draft or Returned.

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
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vouchers_voucher_guard
BEFORE UPDATE OR DELETE ON vouchers_voucher
FOR EACH ROW EXECUTE FUNCTION vouchers_voucher_guard();

CREATE OR REPLACE FUNCTION vouchers_attachment_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    RAISE EXCEPTION 'An attachment cannot be changed; upload a new file'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF EXISTS (
    SELECT 1 FROM vouchers_voucher v
    WHERE v.id = OLD.voucher_id AND v.status NOT IN ('draft', 'returned')
  ) THEN
    RAISE EXCEPTION 'Attachments can only be removed while the voucher is a draft or returned'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER vouchers_attachment_guard
BEFORE UPDATE OR DELETE ON vouchers_voucherattachment
FOR EACH ROW EXECUTE FUNCTION vouchers_attachment_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS vouchers_attachment_guard ON vouchers_voucherattachment;
DROP FUNCTION IF EXISTS vouchers_attachment_guard();
DROP TRIGGER IF EXISTS vouchers_voucher_guard ON vouchers_voucher;
DROP FUNCTION IF EXISTS vouchers_voucher_guard();
"""

STATUSES = [
    ("draft", "Draft"),
    ("submitted", "Submitted"),
    ("accountant_approved", "Accountant approved"),
    ("director_approved", "Director approved"),
    ("returned", "Returned"),
    ("rejected", "Rejected"),
    ("partly_paid", "Partly paid"),
    ("paid", "Paid"),
    ("cancelled", "Cancelled"),
    ("deleted", "Deleted"),
]


def big_id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


def user_fk(related_name):
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name=related_name,
        to=settings.AUTH_USER_MODEL,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("vouchers", "0001_initial"),
        ("core", "0013_document_email"),
        ("masters", "0008_company_account_ledger"),
        ("accounting", "0004_taxes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Voucher",
            fields=[
                ("id", big_id()),
                ("number", models.CharField(max_length=40, unique=True)),
                ("voucher_date", models.DateField()),
                ("description", models.CharField(blank=True, max_length=500)),
                (
                    "total_amount",
                    models.DecimalField(decimal_places=2, default=0, max_digits=18),
                ),
                ("status", models.CharField(choices=STATUSES, default="draft", max_length=30)),
                ("revision", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("submitted_at", models.DateTimeField(blank=True, null=True)),
                ("created_by", user_fk("vouchers_created")),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vouchers",
                        to="core.division",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revisions",
                        to="vouchers.voucher",
                    ),
                ),
                (
                    "payee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vouchers",
                        to="masters.supplier",
                    ),
                ),
                (
                    "transfer_to",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="incoming_vouchers",
                        to="masters.companyaccount",
                    ),
                ),
                (
                    "voucher_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="vouchers",
                        to="vouchers.vouchertype",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("status", "draft"), ("total_amount__gt", 0), _connector="OR"
                        ),
                        name="vouchers_voucher_total_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="VoucherLine",
            fields=[
                ("id", big_id()),
                ("line_no", models.PositiveSmallIntegerField()),
                ("invoice_no", models.CharField(blank=True, max_length=50)),
                ("invoice_date", models.DateField(blank=True, null=True)),
                ("description", models.CharField(blank=True, max_length=500)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                (
                    "tax_amount",
                    models.DecimalField(decimal_places=2, default=0, max_digits=18),
                ),
                (
                    "account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.account",
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
                (
                    "tax_code",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounting.taxcode",
                    ),
                ),
                (
                    "voucher",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="vouchers.voucher",
                    ),
                ),
            ],
            options={
                "ordering": ["voucher", "line_no"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("voucher", "line_no"), name="vouchers_line_unique_no"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("amount__gt", 0)), name="vouchers_line_amount"
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("tax_amount__gte", 0)), name="vouchers_line_tax"
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="VoucherAttachment",
            fields=[
                ("id", big_id()),
                ("file", models.FileField(upload_to="vouchers/%Y/%m/")),
                ("file_name", models.CharField(max_length=200)),
                ("content_type", models.CharField(max_length=100)),
                ("size", models.PositiveIntegerField()),
                ("sha256", models.CharField(db_index=True, max_length=64)),
                ("uploaded_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("uploaded_by", user_fk("+")),
                (
                    "voucher",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="attachments",
                        to="vouchers.voucher",
                    ),
                ),
            ],
            options={"ordering": ["uploaded_at", "id"]},
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
