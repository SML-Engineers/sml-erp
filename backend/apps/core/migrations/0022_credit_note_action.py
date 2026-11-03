from django.db import migrations

# Credit notes (backlog P2-06): the "approve_credit_notes" action. The Director holds it through
# the role; the Admin may give it to another person one by one (a sensitive grant the Director
# confirms). It lets them approve credit notes at the Director's level (owner, 3 Nov 2026).

ROLE_ACTIONS_V5 = {"director": ["approve_credit_notes"]}


def grant(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V5.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for action in actions:
            RoleAction.objects.get_or_create(role=role, action=action)


def revoke(apps, schema_editor):
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V5.items():
        RoleAction.objects.filter(role__code=code, action__in=actions).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0021_issue_invoices_action")]

    operations = [migrations.RunPython(grant, revoke)]
