from django.db import migrations

# Customer receipts and advances (P2-07 fix, after P2-08): the "approve_customer_receipts" action. The
# Accountant holds it through the role; the Admin may give it to any other person one by one
# (a sensitive grant the Director confirms), and they then approve at the Accountant's level
# (owner, 3 Nov 2026). Nobody approves a receipt they recorded.

ROLE_ACTIONS_V7 = {"accountant": ["approve_customer_receipts"]}


def grant(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V7.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for action in actions:
            RoleAction.objects.get_or_create(role=role, action=action)


def revoke(apps, schema_editor):
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V7.items():
        RoleAction.objects.filter(role__code=code, action__in=actions).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0023_credit_hold_action")]

    operations = [migrations.RunPython(grant, revoke)]
