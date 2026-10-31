from django.db import migrations

# Phase 1.6 (backlog P16-02): the Purchasing Officer, stores and QC Inspector roles are switched
# on, and the stores role gets SML's own name (one stores person, owner 31 Oct 2026). Loaded from
# access_defaults so new and existing databases agree.

ROLES = ("purchasing_officer", "store_supervisor", "qc_inspector")
NAMES = {
    "store_supervisor": (
        "Stores Manager / Executive",
        "Receives goods against purchase orders and confirms GRNs; material issues and "
        "returns. Never approves payments or accepts goods in QC.",
    ),
}
OLD_NAMES = {
    "store_supervisor": (
        "Store Supervisor",
        "Goods receipts with weights and counts, material issues and returns.",
    ),
}


def _apply(apps, active, names):
    Role = apps.get_model("core", "Role")
    Role.objects.filter(code__in=ROLES).update(is_active=active)
    for code, (name, description) in names.items():
        Role.objects.filter(code=code).update(name=name, description=description)


def forward(apps, schema_editor):
    _apply(apps, True, NAMES)


def backward(apps, schema_editor):
    _apply(apps, False, OLD_NAMES)


class Migration(migrations.Migration):
    dependencies = [("core", "0018_password_reset")]

    operations = [migrations.RunPython(forward, backward)]
