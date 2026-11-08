from django.db import migrations

# P3-07: a plan entry is only for a released production order, and a past day's plan never
# changes (the shift reports of P3-08 are compared with it).

SQL = """
CREATE OR REPLACE FUNCTION production_plan_guard() RETURNS trigger AS $$
DECLARE
  state text;
  today date := (now() AT TIME ZONE 'Asia/Colombo')::date;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.day < today THEN
    RAISE EXCEPTION 'The plan of % has passed and never changes', OLD.day
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  IF NEW.day < today THEN
    RAISE EXCEPTION 'A plan is made for today or later'
      USING ERRCODE = 'restrict_violation';
  END IF;
  SELECT status INTO state FROM production_productionorder WHERE id = NEW.order_id;
  IF state IS DISTINCT FROM 'released' THEN
    RAISE EXCEPTION 'Only a released production order is planned'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_plan_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_planentry
FOR EACH ROW EXECUTE FUNCTION production_plan_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_plan_guard ON production_planentry;
DROP FUNCTION IF EXISTS production_plan_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("production", "0014_production_plan")]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
