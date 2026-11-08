from django.db import migrations

# P3-10: mould maintenance records are never changed or deleted.

SQL = """
CREATE OR REPLACE FUNCTION production_mould_maintenance_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'A mould maintenance record is never changed or deleted; add a new one'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_mould_maintenance_guard
BEFORE UPDATE OR DELETE ON production_mouldmaintenance
FOR EACH ROW EXECUTE FUNCTION production_mould_maintenance_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_mould_maintenance_guard ON production_mouldmaintenance;
DROP FUNCTION IF EXISTS production_mould_maintenance_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("production", "0020_mould_maintenance")]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
