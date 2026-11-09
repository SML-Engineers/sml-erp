from django.db import migrations

# P3-16 part 2: order cost entries stay insert-only, except that an entry made before the
# ledger existed (part 1) is posted once: its ledger, credit account and journal are filled
# in, from empty, and nothing else changes. A job's completion is never changed or deleted.

SQL = """
CREATE OR REPLACE FUNCTION production_order_cost_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.ledger = '' AND OLD.journal_entry_id IS NULL
     AND (NEW.job_id, NEW.production_order_id, NEW.division_id, NEW.element, NEW.day,
          NEW.source, NEW.quantity, NEW.unit, NEW.rate, NEW.amount, NEW.description,
          NEW.adjusts, NEW.created_at)
         IS NOT DISTINCT FROM
         (OLD.job_id, OLD.production_order_id, OLD.division_id, OLD.element, OLD.day,
          OLD.source, OLD.quantity, OLD.unit, OLD.rate, OLD.amount, OLD.description,
          OLD.adjusts, OLD.created_at) THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'Order cost entries are never changed or deleted; add an adjusting entry'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION production_completion_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'A job completion is never changed or deleted'
    USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_completion_guard
BEFORE UPDATE OR DELETE ON production_jobcompletion
FOR EACH ROW EXECUTE FUNCTION production_completion_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_completion_guard ON production_jobcompletion;
DROP FUNCTION IF EXISTS production_completion_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("production", "0034_wip_ledger")]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
