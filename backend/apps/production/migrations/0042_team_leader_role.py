from django.db import migrations

from apps.core.access_defaults import MACHINE_TIME_GRANTS_V1, TEAM_LEADER_ROLE_V1

# P3-24 (owner, 15 Nov 2026): the Production Team Leader role and the "Machine time" area,
# granted to the roles that work with production. Loaded from access_defaults so new and
# existing databases agree.


def forward(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    RolePermission = apps.get_model("core", "RolePermission")
    for code, (name, description, active, permissions, _actions) in TEAM_LEADER_ROLE_V1.items():
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
    for code, (level, note) in MACHINE_TIME_GRANTS_V1.items():
        role = Role.objects.filter(code=code).first()
        if role is not None:
            RolePermission.objects.get_or_create(
                role=role, area="machine_time", level=level, defaults={"note": note}
            )


def backward(apps, schema_editor):
    apps.get_model("core", "RolePermission").objects.filter(area="machine_time").delete()
    apps.get_model("core", "Role").objects.filter(code__in=TEAM_LEADER_ROLE_V1).delete()


class Migration(migrations.Migration):
    dependencies = [("production", "0041_machine_jobs"), ("core", "0028_company_two_factor_on")]

    operations = [migrations.RunPython(forward, backward)]
