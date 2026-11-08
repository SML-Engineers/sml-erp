from django.db import migrations

# P3-12: job card entries and their rejects are locked with their shift report (only a draft
# or returned report changes), and work on one machine never overlaps in time.

SQL = """
CREATE OR REPLACE FUNCTION production_job_entry_guard() RETURNS trigger AS $$
DECLARE
  row_report bigint;
  state text;
BEGIN
  IF TG_OP = 'UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF TG_TABLE_NAME = 'production_jobcardreject' THEN
    SELECT report_id INTO row_report FROM production_jobcardentry
      WHERE id = CASE WHEN TG_OP = 'DELETE' THEN OLD.entry_id ELSE NEW.entry_id END;
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
  IF TG_TABLE_NAME = 'production_jobcardentry' THEN
    IF EXISTS (
         SELECT 1 FROM production_jobcardentry e
         WHERE e.machine_id = NEW.machine_id AND e.id <> NEW.id
           AND tstzrange(e.started_at, e.ended_at) && tstzrange(NEW.started_at, NEW.ended_at)) THEN
      RAISE EXCEPTION 'Times on one machine never overlap'
        USING ERRCODE = 'exclusion_violation';
    END IF;
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER production_job_entry_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_jobcardentry
FOR EACH ROW EXECUTE FUNCTION production_job_entry_guard();

CREATE TRIGGER production_job_entry_guard
BEFORE INSERT OR UPDATE OR DELETE ON production_jobcardreject
FOR EACH ROW EXECUTE FUNCTION production_job_entry_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_job_entry_guard ON production_jobcardreject;
DROP TRIGGER IF EXISTS production_job_entry_guard ON production_jobcardentry;
DROP FUNCTION IF EXISTS production_job_entry_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("production", "0024_job_card_entries")]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
