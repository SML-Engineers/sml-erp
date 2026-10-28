from django.db import migrations, models

# Tax invoice and quotation numbering (backlog P0-08b).
#
# - Each division gets a tax invoice code (the QQQQ of YYMMM_QQQQ_XXXXX, Gazette 2481/22).
# - A series can carry on past its digits instead of stopping (tax invoices must never stop).
# - The starting series for tax invoices, quotations and proforma invoices.
# - The division guard also refuses changing a tax invoice code once an invoice number used it.

SERIES_V2 = [
    ("tax_invoice", "Tax invoices", "{YY}{MMM}_{IC}_{XX}", "monthly", "grow"),
    ("quotation", "Quotations", "QL{YY}{MM}{DD}{XX}", "daily", "grow"),
    ("proforma", "Proforma invoices", "PI-{YYYY}-{NNNN}", "yearly", "grow"),
]


def load(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    for document_type, name, number_format, reset, when_full in SERIES_V2:
        NumberSeries.objects.get_or_create(
            document_type=document_type,
            defaults={
                "name": name,
                "format": number_format,
                "reset_period": reset,
                "when_full": when_full,
            },
        )


FORWARD = """
CREATE OR REPLACE FUNCTION core_division_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE'
     AND NEW.tax_invoice_code IS DISTINCT FROM OLD.tax_invoice_code
     AND EXISTS (
       SELECT 1 FROM core_issuednumber i
       JOIN core_numberseries s ON s.id = i.series_id
       WHERE i.division_id = OLD.id AND s.format LIKE '%{IC}%'
     ) THEN
    RAISE EXCEPTION 'Division %: its tax invoice code % has been used on invoices and cannot change',
      OLD.code, OLD.tax_invoice_code USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.first_used_at IS NULL THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Division % has been used on documents: it cannot be deleted, only deactivated', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.code IS DISTINCT FROM OLD.code THEN
    RAISE EXCEPTION 'Division % has been used on documents: its code cannot change', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.first_used_at IS DISTINCT FROM OLD.first_used_at THEN
    RAISE EXCEPTION 'Division %: the date it was first used cannot change', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

# Back to the guard of migration 0007.
BACKWARD = """
CREATE OR REPLACE FUNCTION core_division_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.first_used_at IS NULL THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Division % has been used on documents: it cannot be deleted, only deactivated', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.code IS DISTINCT FROM OLD.code THEN
    RAISE EXCEPTION 'Division % has been used on documents: its code cannot change', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.first_used_at IS DISTINCT FROM OLD.first_used_at THEN
    RAISE EXCEPTION 'Division %: the date it was first used cannot change', OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_user_all_sections"),
    ]

    operations = [
        migrations.AddField(
            model_name="division",
            name="tax_invoice_code",
            field=models.CharField(blank=True, max_length=15),
        ),
        migrations.AddConstraint(
            model_name="division",
            constraint=models.CheckConstraint(
                condition=models.Q(("tax_invoice_code__regex", "^[A-Z0-9]{0,15}$")),
                name="core_division_tax_invoice_code_format",
            ),
        ),
        migrations.AddConstraint(
            model_name="division",
            constraint=models.UniqueConstraint(
                condition=models.Q(("tax_invoice_code", ""), _negated=True),
                fields=("tax_invoice_code",),
                name="core_division_tax_invoice_code_unique",
            ),
        ),
        migrations.AddField(
            model_name="numberseries",
            name="when_full",
            field=models.CharField(
                choices=[
                    ("stop", "Stop and ask the Admin to widen it"),
                    ("grow", "Carry on with more digits"),
                ],
                default="stop",
                max_length=10,
            ),
        ),
        migrations.RunPython(load, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
