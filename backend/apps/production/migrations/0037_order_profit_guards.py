from django.db import migrations

# P3-17: an order's daily profit snapshot and its alerts are records of what was seen and
# sent; neither is ever changed or deleted.

SQL = """
CREATE OR REPLACE FUNCTION production_profit_record_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Profit snapshots and alerts are never changed or deleted'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_snapshot_guard
BEFORE UPDATE OR DELETE ON production_orderprofitsnapshot
FOR EACH ROW EXECUTE FUNCTION production_profit_record_guard();

CREATE TRIGGER production_alert_guard
BEFORE UPDATE OR DELETE ON production_profitalert
FOR EACH ROW EXECUTE FUNCTION production_profit_record_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_snapshot_guard ON production_orderprofitsnapshot;
DROP TRIGGER IF EXISTS production_alert_guard ON production_profitalert;
DROP FUNCTION IF EXISTS production_profit_record_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("production", "0036_order_profit")]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
