from django.db import migrations

# Credit control (backlog P2-08): the "allow_credit_holds" action. A sales order or tax invoice
# of a customer over the credit limit or with overdue invoices is stopped until the Director
# allows that document (owner, 3 Nov 2026). The Director holds it through the role; a grant to
# anyone else is sensitive and needs the Director's confirmation.

ROLE_ACTIONS_V6 = {"director": ["allow_credit_holds"]}


def grant(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V6.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for action in actions:
            RoleAction.objects.get_or_create(role=role, action=action)


def revoke(apps, schema_editor):
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V6.items():
        RoleAction.objects.filter(role__code=code, action__in=actions).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0022_credit_note_action")]

    operations = [migrations.RunPython(grant, revoke)]
