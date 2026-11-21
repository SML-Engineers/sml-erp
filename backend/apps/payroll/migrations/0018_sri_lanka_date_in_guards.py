"""Payroll guards judge "already in force" by the Sri Lanka date (fix, 21 Nov 2026).

These six guard functions compared with CURRENT_DATE, which is the database session's date,
and Django runs sessions in UTC. Between midnight and 05:30 in Sri Lanka the guards therefore
used yesterday's date: for example, a work rule from a pay month that had just started could
still be deleted. The other apps' guards already use the Sri Lanka date; these now do too.
The function bodies are otherwise unchanged: each is rewritten from its current definition.
"""

from django.db import migrations

FUNCTIONS = [
    "payroll_dated_guard",
    "payroll_holiday_guard",
    "payroll_rate_guard",
    "payroll_setting_guard",
    "payroll_taxband_guard",
    "payroll_workrule_guard",
]

SRI_LANKA = "(now() AT TIME ZONE 'Asia/Colombo')::date"


# Each function is rewritten from its current definition, swapping OLD_TEXT for NEW_TEXT; it
# stops if a function does not contain OLD_TEXT, so nothing is half done.
TEMPLATE = """
DO $$
DECLARE
  f record;
  body text;
BEGIN
  FOR f IN SELECT oid FROM pg_proc WHERE proname = ANY(NAMES) LOOP
    body := pg_get_functiondef(f.oid);
    IF position($old$OLD_TEXT$old$ IN body) = 0 THEN
      RAISE EXCEPTION 'function % has no %', f.oid::regproc, $old$OLD_TEXT$old$;
    END IF;
    EXECUTE replace(body, $old$OLD_TEXT$old$, $new$NEW_TEXT$new$);
  END LOOP;
END $$;
"""


def _swap(old: str, new: str) -> str:
    names = "ARRAY[" + ", ".join(f"'{name}'" for name in FUNCTIONS) + "]"
    return TEMPLATE.replace("NAMES", names).replace("OLD_TEXT", old).replace("NEW_TEXT", new)


class Migration(migrations.Migration):
    dependencies = [("payroll", "0017_fingerprint")]

    operations = [
        migrations.RunSQL(_swap("CURRENT_DATE", SRI_LANKA), _swap(SRI_LANKA, "CURRENT_DATE"))
    ]
