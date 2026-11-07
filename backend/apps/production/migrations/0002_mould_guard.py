from django.db import migrations

# A mould's code is fixed once a production document uses it, and a used mould is retired,
# never deleted (rule 9): the same guard as sections and machines (masters 0002).
SQL = """
CREATE TRIGGER production_mould_guard
BEFORE UPDATE OR DELETE ON production_mould
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();
"""

BACKWARD = "DROP TRIGGER IF EXISTS production_mould_guard ON production_mould;"


class Migration(migrations.Migration):
    dependencies = [
        ("production", "0001_initial"),
        ("masters", "0002_seed_and_guards"),
    ]

    operations = [migrations.RunSQL(SQL, BACKWARD)]
