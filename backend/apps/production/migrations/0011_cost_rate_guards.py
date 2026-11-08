from django.db import migrations

# P3-05: a cost rate in force (from today or earlier) never changes and is never deleted
# (rule 11); a future one can be replaced until its date. Only company moulds are amortised
# (owner, 7 Nov 2026), and a machine's overhead rate is kept under the machine's own section.

SQL = """
CREATE OR REPLACE FUNCTION production_cost_rate_guard() RETURNS trigger AS $$
DECLARE
  owner text;
  home bigint;
BEGIN
  IF TG_OP IN ('UPDATE', 'DELETE') THEN
    -- Saving a row unchanged is allowed (tests reload their starting data this way).
    IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
      RETURN NEW;
    END IF;
    IF OLD.effective_from <= (now() AT TIME ZONE 'Asia/Colombo')::date THEN
      RAISE EXCEPTION 'A cost rate in force since % never changes; add a new one',
        OLD.effective_from USING ERRCODE = 'restrict_violation';
    END IF;
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  END IF;
  IF NEW.kind = 'mould' THEN
    SELECT m.owner INTO owner FROM production_mould m WHERE m.id = NEW.mould_id;
    IF owner IS DISTINCT FROM 'company' THEN
      RAISE EXCEPTION 'Only company moulds are amortised'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  IF NEW.machine_id IS NOT NULL THEN
    SELECT section_id INTO home FROM masters_machine WHERE id = NEW.machine_id;
    IF home IS DISTINCT FROM NEW.section_id THEN
      RAISE EXCEPTION 'A machine''s rate is kept under its own section'
        USING ERRCODE = 'check_violation';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_cost_rate_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_costrate
FOR EACH ROW EXECUTE FUNCTION production_cost_rate_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_cost_rate_guard ON production_costrate;
DROP FUNCTION IF EXISTS production_cost_rate_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("production", "0010_cost_rates")]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
