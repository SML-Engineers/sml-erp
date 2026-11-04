import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Product pictures on a quotation for the customer (owner's request, 4 Nov 2026): at most
# three, each at most 1 MB. They change only while the quotation is a draft (database guard).

FORWARD = """
CREATE OR REPLACE FUNCTION sales_quotationimage_guard() RETURNS trigger AS $$
DECLARE
  q_status text;
BEGIN
  SELECT status INTO q_status FROM sales_quotation
    WHERE id = COALESCE(NEW.quotation_id, OLD.quotation_id);
  IF q_status IS NOT NULL AND q_status <> 'draft' THEN
    RAISE EXCEPTION 'The pictures of a quotation change only while it is a draft'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'INSERT' AND (
    SELECT count(*) FROM sales_quotationimage WHERE quotation_id = NEW.quotation_id
  ) >= 3 THEN
    RAISE EXCEPTION 'A quotation has at most three pictures'
      USING ERRCODE = 'check_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_quotationimage_guard
BEFORE INSERT OR UPDATE OR DELETE ON sales_quotationimage
FOR EACH ROW EXECUTE FUNCTION sales_quotationimage_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS sales_quotationimage_guard ON sales_quotationimage;
DROP FUNCTION IF EXISTS sales_quotationimage_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0015_returned_cheques"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="QuotationImage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("file", models.FileField(upload_to="quotation-images/%Y/%m/")),
                ("file_name", models.CharField(max_length=200)),
                ("content_type", models.CharField(max_length=100)),
                ("size", models.PositiveIntegerField()),
                ("sha256", models.CharField(max_length=64)),
                ("uploaded_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "quotation",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="sales.quotation",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["uploaded_at", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("size__gt", 0), ("size__lte", 1048576)),
                        name="sales_quotationimage_size",
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
