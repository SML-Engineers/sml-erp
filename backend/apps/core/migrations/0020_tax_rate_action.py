from django.db import migrations

# Tax rate changes (backlog P16-20): the Director confirms them (the "confirm_tax_rates"
# action); the Admin or the Accountant enters them (owner, 2 Nov 2026).

ROLE_ACTIONS_V3 = {"director": ["confirm_tax_rates"]}


def grant(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V3.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for action in actions:
            RoleAction.objects.get_or_create(role=role, action=action)


def revoke(apps, schema_editor):
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V3.items():
        RoleAction.objects.filter(role__code=code, action__in=actions).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0019_purchasing_roles")]

    operations = [migrations.RunPython(grant, revoke)]
