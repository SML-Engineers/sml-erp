from django.db import migrations

# Credit terms (owner, 3 Nov 2026): the "set_credit_terms" action. Only the Accountant and the
# Director change a customer's credit limit and payment terms, so a salesperson cannot lift
# their own customer's credit hold (P2-08). A grant to anyone else is sensitive and needs the
# Director's confirmation.

ROLE_ACTIONS_V8 = {"director": ["set_credit_terms"], "accountant": ["set_credit_terms"]}


def grant(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V8.items():
        role = Role.objects.filter(code=code).first()
        if role is None:
            continue
        for action in actions:
            RoleAction.objects.get_or_create(role=role, action=action)


def revoke(apps, schema_editor):
    RoleAction = apps.get_model("core", "RoleAction")
    for code, actions in ROLE_ACTIONS_V8.items():
        RoleAction.objects.filter(role__code=code, action__in=actions).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0024_receipt_approver_action")]

    operations = [migrations.RunPython(grant, revoke)]
