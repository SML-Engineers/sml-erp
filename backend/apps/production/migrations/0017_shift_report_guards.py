from django.db import migrations

# P3-08: a shift report is never deleted and keeps its section, day and shift; a submitted
# report is locked (only the Production Manager's approval or return moves it, P3-09); its
# runs, rejects, downtime, material and manpower change only while it is a draft or returned.
# Runs on one machine never overlap, nor does downtime on one machine.

SQL = """
CREATE OR REPLACE FUNCTION production_shift_report_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A shift report is never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF NEW.section_id <> OLD.section_id OR NEW.day <> OLD.day OR NEW.shift_id <> OLD.shift_id THEN
    RAISE EXCEPTION 'A shift report keeps its section, day and shift'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status IN ('submitted', 'approved') AND NOT (
       OLD.status = 'submitted' AND NEW.status IN ('approved', 'returned')) THEN
    RAISE EXCEPTION 'The shift report is % and locked', OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.status <> OLD.status AND NOT (
       (OLD.status IN ('draft', 'returned') AND NEW.status = 'submitted')
       OR (OLD.status = 'submitted' AND NEW.status IN ('approved', 'returned'))) THEN
    RAISE EXCEPTION 'A shift report cannot go from % to %', OLD.status, NEW.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_shift_report_guard
BEFORE UPDATE OR DELETE ON production_shiftreport
FOR EACH ROW EXECUTE FUNCTION production_shift_report_guard();

CREATE OR REPLACE FUNCTION production_shift_line_guard() RETURNS trigger AS $$
DECLARE
  row_report bigint;
  state text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME = 'production_rejectentry' THEN
    SELECT report_id INTO row_report FROM production_mouldingrun
      WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.run_id ELSE NEW.run_id END;
  ELSIF TG_OP = 'DELETE' THEN
    row_report := OLD.report_id;
  ELSE
    row_report := NEW.report_id;
  END IF;
  SELECT status INTO state FROM production_shiftreport WHERE id = row_report;
  IF state IS NOT NULL AND state NOT IN ('draft', 'returned') THEN
    RAISE EXCEPTION 'The shift report is % and locked', state
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  IF TG_TABLE_NAME IN ('production_mouldingrun', 'production_downtimeentry') THEN
    IF TG_TABLE_NAME = 'production_mouldingrun' AND EXISTS (
         SELECT 1 FROM production_mouldingrun r
         WHERE r.machine_id = NEW.machine_id AND r.id <> NEW.id
           AND tstzrange(r.started_at, r.ended_at) && tstzrange(NEW.started_at, NEW.ended_at))
    OR TG_TABLE_NAME = 'production_downtimeentry' AND EXISTS (
         SELECT 1 FROM production_downtimeentry d
         WHERE d.machine_id = NEW.machine_id AND d.id <> NEW.id
           AND tstzrange(d.started_at, d.ended_at) && tstzrange(NEW.started_at, NEW.ended_at))
    THEN
      RAISE EXCEPTION 'Times on one machine never overlap'
        USING ERRCODE = 'exclusion_violation';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

TABLES = [
    "production_mouldingrun",
    "production_rejectentry",
    "production_downtimeentry",
    "production_materialentry",
    "production_manpowerentry",
]

SQL += "".join(
    f"""
CREATE TRIGGER production_shift_line_guard
BEFORE INSERT OR UPDATE OR DELETE ON {table}
FOR EACH ROW EXECUTE FUNCTION production_shift_line_guard();
"""
    for table in TABLES
)

BACKWARD = (
    "".join(f"DROP TRIGGER IF EXISTS production_shift_line_guard ON {t};\n" for t in TABLES)
    + """
DROP FUNCTION IF EXISTS production_shift_line_guard();
DROP TRIGGER IF EXISTS production_shift_report_guard ON production_shiftreport;
DROP FUNCTION IF EXISTS production_shift_report_guard();
"""
)


class Migration(migrations.Migration):
    dependencies = [("production", "0016_shift_reports")]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
