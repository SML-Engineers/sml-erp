from django.db import migrations

# Phase 1.5 (backlog P15-01): the Sales Executive and Sales Manager roles are switched on so
# that they can be assigned. They were loaded with the other standard roles in 0004 but kept
# off until their first page (customers) existed.

SALES_ROLES = ("sales_executive", "sales_manager")


def switch_on(apps, schema_editor):
    apps.get_model("core", "Role").objects.filter(code__in=SALES_ROLES).update(is_active=True)


def switch_off(apps, schema_editor):
    apps.get_model("core", "Role").objects.filter(code__in=SALES_ROLES).update(is_active=False)


class Migration(migrations.Migration):
    dependencies = [("core", "0015_approval_reminders")]

    operations = [migrations.RunPython(switch_on, switch_off)]
