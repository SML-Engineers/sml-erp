from django.db import migrations

# Sign-in history is evidence: once written, a row can never be changed or removed, by the
# application or by anyone with direct database access through the application's account.
FORWARD = """
CREATE OR REPLACE FUNCTION core_refuse_change() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION '% is insert-only: % is not allowed', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER core_loginevent_insert_only
BEFORE UPDATE OR DELETE ON core_loginevent
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS core_loginevent_insert_only ON core_loginevent;
DROP FUNCTION IF EXISTS core_refuse_change();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
