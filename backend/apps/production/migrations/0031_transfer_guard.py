from django.db import migrations

# P3-15: an inter-division transfer, once posted, is never changed or deleted; a mistake is
# put right with a reversing journal by the Accountant.

SQL = """
CREATE OR REPLACE FUNCTION production_transfer_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'An inter-division transfer is never changed or deleted'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_transfer_guard
BEFORE UPDATE OR DELETE ON production_interdivisiontransfer
FOR EACH ROW EXECUTE FUNCTION production_transfer_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_transfer_guard ON production_interdivisiontransfer;
DROP FUNCTION IF EXISTS production_transfer_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("production", "0030_inter_division_transfers")]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
