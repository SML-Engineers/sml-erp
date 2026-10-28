from django.db import migrations

from apps.core.access_defaults import STANDARD_DIVISIONS_V1, STANDARD_ROLES_V1


def load(apps, schema_editor):
    Division = apps.get_model("core", "Division")
    Role = apps.get_model("core", "Role")
    RolePermission = apps.get_model("core", "RolePermission")
    RoleAction = apps.get_model("core", "RoleAction")

    for code, name, division_type in STANDARD_DIVISIONS_V1:
        Division.objects.get_or_create(
            code=code, defaults={"name": name, "division_type": division_type}
        )

    for code, (name, description, active, permissions, actions) in STANDARD_ROLES_V1.items():
        role, _ = Role.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "description": description,
                "is_standard": True,
                "is_active": active,
            },
        )
        for area, level, note in permissions:
            RolePermission.objects.get_or_create(
                role=role, area=area, level=level, defaults={"note": note}
            )
        for action in actions:
            RoleAction.objects.get_or_create(role=role, action=action)


def unload(apps, schema_editor):
    apps.get_model("core", "Role").objects.filter(is_standard=True).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_divisions_roles"),
    ]

    operations = [migrations.RunPython(load, unload)]
