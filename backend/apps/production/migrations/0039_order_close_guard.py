from django.db import migrations

# P3-18: an order's close report is the record of how it finished; never changed or deleted.

SQL = """
CREATE OR REPLACE FUNCTION production_close_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'An order''s close report is never changed or deleted'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_close_guard
BEFORE UPDATE OR DELETE ON production_orderclose
FOR EACH ROW EXECUTE FUNCTION production_close_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_close_guard ON production_orderclose;
DROP FUNCTION IF EXISTS production_close_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("production", "0038_order_close")]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
