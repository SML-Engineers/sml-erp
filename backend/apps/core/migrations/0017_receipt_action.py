from django.db import migrations

# Customer advances (backlog P15-09): the Cashier records customer receipts and advances
# (the "record_receipt" action), which the Accountant approves (owner, 31 Oct 2026).
# Loaded from access_defaults.ROLE_ACTIONS_V2 so new and existing databases agree.

ROLE_ACTIONS_V2 = {"cashier": ["record_receipt"]}


def grant(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V2.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for action in actions:
            RoleAction.objects.get_or_create(role=role, action=action)


def revoke(apps, schema_editor):
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V2.items():
        RoleAction.objects.filter(role__code=code, action__in=actions).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0016_sales_roles_active")]

    operations = [migrations.RunPython(grant, revoke)]
