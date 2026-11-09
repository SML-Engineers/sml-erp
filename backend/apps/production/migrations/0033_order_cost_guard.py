from django.db import migrations

# P3-16: order cost entries are insert-only; a change is an adjusting entry.

SQL = """
CREATE OR REPLACE FUNCTION production_order_cost_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Order cost entries are never changed or deleted; add an adjusting entry'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_order_cost_guard
BEFORE UPDATE OR DELETE ON production_ordercost
FOR EACH ROW EXECUTE FUNCTION production_order_cost_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_order_cost_guard ON production_ordercost;
DROP FUNCTION IF EXISTS production_order_cost_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("production", "0032_order_costs")]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
