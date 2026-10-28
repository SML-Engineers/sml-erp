from django.db import migrations

# Starting sections (spec 3A.1) and the database guards for the factory structure.
#
# The database refuses, whatever the application does:
# - changing the code of a section or machine used on a transaction, clearing its "first
#   used" date, or deleting it (rule 9);
# - changing or removing a machine rate once its date has arrived (Sri Lanka time); a new
#   rate with a later date replaces it (rule 11).

WORKSHOP_SECTIONS_V1 = [
    ("M-MIL", "Manual Milling", "manual"),
    ("M-LAT", "Manual Lathe", "manual"),
    ("M-DRL", "Manual Drilling", "manual"),
    ("M-SHP", "Manual Shaping", "manual"),
    ("M-GRD", "Manual Grinding", "manual"),
    ("M-POL", "Manual Polishing", "manual"),
    ("M-EDM", "Manual EDM", "manual"),
    ("M-WED", "Manual Wire EDM", "manual"),
    ("M-BSW", "Manual Bandsaw", "manual"),
    ("C-MIL", "CNC Milling", "cnc"),
    ("C-LAT", "CNC Lathe", "cnc"),
    ("C-DRL", "CNC Drilling", "cnc"),
    ("C-SHP", "CNC Shaping", "cnc"),
    ("C-GRD", "CNC Grinding", "cnc"),
    ("C-POL", "CNC Polishing", "cnc"),
    ("C-EDM", "CNC EDM", "cnc"),
    ("C-WED", "Wire EDM", "cnc"),
    ("C-BSW", "CNC Bandsaw", "cnc"),
]

# One section to hold the moulding machines; the Admin adds more if needed.
MOULDING_SECTIONS_V1 = [("IM-MLD", "Injection Moulding Machines")]


def load(apps, schema_editor):
    Division = apps.get_model("core", "Division")
    Section = apps.get_model("masters", "Section")
    workshop = Division.objects.filter(code="WS").first()
    if workshop:
        for code, name, category in WORKSHOP_SECTIONS_V1:
            Section.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "division": workshop,
                    "category": category,
                    "section_type": "machining",
                },
            )
    moulding = Division.objects.filter(code="IM").first()
    if moulding:
        for code, name in MOULDING_SECTIONS_V1:
            Section.objects.get_or_create(
                code=code,
                defaults={"name": name, "division": moulding, "section_type": "moulding"},
            )


FORWARD = """
CREATE OR REPLACE FUNCTION masters_code_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.first_used_at IS NULL THEN
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION '% % has been used: it cannot be deleted, only made inactive',
      TG_TABLE_NAME, OLD.code USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.code IS DISTINCT FROM OLD.code THEN
    RAISE EXCEPTION '% % has been used: its code cannot change', TG_TABLE_NAME, OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.first_used_at IS DISTINCT FROM OLD.first_used_at THEN
    RAISE EXCEPTION '% %: the date it was first used cannot change', TG_TABLE_NAME, OLD.code
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER masters_section_guard
BEFORE UPDATE OR DELETE ON masters_section
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();

CREATE TRIGGER masters_machine_guard
BEFORE UPDATE OR DELETE ON masters_machine
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();

CREATE OR REPLACE FUNCTION masters_rate_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.effective_from <= (now() AT TIME ZONE 'Asia/Colombo')::date THEN
    RAISE EXCEPTION 'A rate in force since % cannot be changed or removed; add a new rate instead',
      OLD.effective_from USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER masters_machinerate_guard
BEFORE UPDATE OR DELETE ON masters_machinerate
FOR EACH ROW EXECUTE FUNCTION masters_rate_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS masters_machinerate_guard ON masters_machinerate;
DROP FUNCTION IF EXISTS masters_rate_guard();
DROP TRIGGER IF EXISTS masters_machine_guard ON masters_machine;
DROP TRIGGER IF EXISTS masters_section_guard ON masters_section;
DROP FUNCTION IF EXISTS masters_code_guard();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("masters", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(load, migrations.RunPython.noop),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
