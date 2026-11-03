from django.db import migrations

# Tax invoices (backlog P2-05): the "issue_tax_invoices" action. The Director and the
# Accountant hold it through their roles; the Admin grants it to chosen salespeople one by
# one (a sensitive grant the Director confirms). Not every salesperson issues invoices
# (owner, 3 Nov 2026).

ROLE_ACTIONS_V4 = {"director": ["issue_tax_invoices"], "accountant": ["issue_tax_invoices"]}


def grant(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V4.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for action in actions:
            RoleAction.objects.get_or_create(role=role, action=action)


def revoke(apps, schema_editor):
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V4.items():
        RoleAction.objects.filter(role__code=code, action__in=actions).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0020_tax_rate_action")]

    operations = [migrations.RunPython(grant, revoke)]
