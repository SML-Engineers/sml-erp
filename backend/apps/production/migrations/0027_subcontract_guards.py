from django.db import migrations

# P3-13: parts sent out and received back are never changed or deleted, and what comes back
# from a dispatch never adds up to more than was sent. Plus the "SC" number series.

SQL = """
CREATE OR REPLACE FUNCTION production_subcontract_guard() RETURNS trigger AS $$
DECLARE
  sent numeric;
  back numeric;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'Parts sent out or received back are never changed or deleted'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_TABLE_NAME = 'production_subcontractreturn' THEN
    SELECT quantity INTO sent FROM production_subcontractdispatch
      WHERE id = NEW.dispatch_id FOR UPDATE;
    SELECT COALESCE(SUM(good + rejected), 0) INTO back FROM production_subcontractreturn
      WHERE dispatch_id = NEW.dispatch_id;
    IF back + NEW.good + NEW.rejected > sent THEN
      RAISE EXCEPTION 'More is received back than was sent out'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_subcontract_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_subcontractdispatch
FOR EACH ROW EXECUTE FUNCTION production_subcontract_guard();

CREATE TRIGGER production_subcontract_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_subcontractreturn
FOR EACH ROW EXECUTE FUNCTION production_subcontract_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_subcontract_guard ON production_subcontractreturn;
DROP TRIGGER IF EXISTS production_subcontract_guard ON production_subcontractdispatch;
DROP FUNCTION IF EXISTS production_subcontract_guard();
"""


def seed(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    NumberSeries.objects.get_or_create(
        document_type="subcontract_dispatch",
        defaults={
            "name": "Parts sent out to subcontractors",
            "format": "SC{YY}{MM}{NNNN}",
            "reset_period": "monthly",
            "when_full": "grow",
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("production", "0026_subcontract"),
        ("core", "0027_company_epf_etf"),
    ]

    operations = [
        migrations.RunSQL(SQL, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
