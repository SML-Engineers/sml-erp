from django.db import migrations

# Phase 3 (backlog P3-01): the Production Planner, Production Supervisor and Production
# Manager roles are switched on so that they can be assigned. They were loaded with the other
# standard roles in core 0004 but kept off until their first page (moulds) existed.

ROLES = ("production_planner", "production_supervisor", "production_manager")


def switch_on(apps, schema_editor):
    apps.get_model("core", "Role").objects.filter(code__in=ROLES).update(is_active=True)


def switch_off(apps, schema_editor):
    apps.get_model("core", "Role").objects.filter(code__in=ROLES).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("production", "0002_mould_guard"), ("core", "0027_company_epf_etf")]

    operations = [migrations.RunPython(switch_on, switch_off)]
