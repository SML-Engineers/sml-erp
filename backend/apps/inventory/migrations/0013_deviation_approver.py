from django.db import migrations

# QC deviations (owner, 8 Nov 2026; known issue G10): the Production Manager approves them,
# and the Director still approves a deviation on a failed critical check. The default rule
# seeded in 0004 (Director, no subtype) moves to the Production Manager, and a more specific
# rule for subtype "critical" goes to the Director. Rules the Admin has added are left alone.


def forward(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    director = Role.objects.filter(code="director").first()
    manager = Role.objects.filter(code="production_manager").first()
    if director is None or manager is None:
        return
    default = ApprovalRule.objects.filter(
        document_type="quality_deviation",
        level=2,
        role=director,
        subtype="",
        division__isnull=True,
        min_amount__isnull=True,
        max_amount__isnull=True,
        is_active=True,
    )
    default.update(role=manager)
    ApprovalRule.objects.get_or_create(
        document_type="quality_deviation",
        level=2,
        subtype="critical",
        division=None,
        defaults={"role": director},
    )


def backward(apps, schema_editor):
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    director = Role.objects.filter(code="director").first()
    ApprovalRule.objects.filter(document_type="quality_deviation", subtype="critical").delete()
    if director is not None:
        ApprovalRule.objects.filter(document_type="quality_deviation", subtype="").update(
            role=director
        )


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0012_production_kinds"),
        ("core", "0027_company_epf_etf"),
    ]

    operations = [migrations.RunPython(forward, backward)]
