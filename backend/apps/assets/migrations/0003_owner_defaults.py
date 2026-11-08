from datetime import date

from django.db import migrations

# Owner, 8 Nov 2026: default depreciation per asset class (straight line), set by the
# Accountant from now on with the Director's approval; each asset's own terms are approved
# by the Director too. "Moulds and tooling" was not in the owner's list: it takes the plant
# and machinery values (recorded in his questions of 8 Nov) until the Accountant changes it.
# Classes that already have a rate keep it.

DEFAULTS = {
    "BUILDINGS": ("5", 20),
    "PLANT": ("10", 10),
    "MOULDS": ("10", 10),
    "VEHICLES": ("20", 5),
    "FURNITURE": ("25", 4),
    "COMPUTERS": ("25", 4),
}

SQL = """
CREATE OR REPLACE FUNCTION assets_terms_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Depreciation terms are never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW IS NOT DISTINCT FROM OLD THEN
    RETURN NEW;
  END IF;
  IF OLD.status <> 'awaiting'
     OR (NEW.asset_id, NEW.effective_from, NEW.method, NEW.rate, NEW.life_years, NEW.reason,
         NEW.created_by_id, NEW.created_at)
        IS DISTINCT FROM
        (OLD.asset_id, OLD.effective_from, OLD.method, OLD.rate, OLD.life_years, OLD.reason,
         OLD.created_by_id, OLD.created_at) THEN
    RAISE EXCEPTION 'Depreciation terms never change once sent; propose new ones'
      USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER assets_terms_guard
BEFORE UPDATE OR DELETE ON assets_assetterms
FOR EACH ROW EXECUTE FUNCTION assets_terms_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS assets_terms_guard ON assets_assetterms;
DROP FUNCTION IF EXISTS assets_terms_guard();
"""


def seed(apps, schema_editor):
    AssetClass = apps.get_model("assets", "AssetClass")
    AssetClassRate = apps.get_model("assets", "AssetClassRate")
    Role = apps.get_model("core", "Role")
    ApprovalRule = apps.get_model("core", "ApprovalRule")
    ApprovalReminder = apps.get_model("core", "ApprovalReminder")
    for code, (rate, years) in DEFAULTS.items():
        found = AssetClass.objects.filter(code=code).first()
        if found is None or AssetClassRate.objects.filter(asset_class=found).exists():
            continue
        AssetClassRate.objects.create(
            asset_class=found,
            effective_from=date(2000, 1, 1),
            method="straight_line",
            rate=rate,
            life_years=years,
            status="approved",
            reason="Owner's defaults, 8 Nov 2026",
        )
    director = Role.objects.filter(code="director").first()
    for document_type in ("asset_terms", "asset_class_rate"):
        if director and not ApprovalRule.objects.filter(document_type=document_type).exists():
            ApprovalRule.objects.create(document_type=document_type, level=2, role=director)
        ApprovalReminder.objects.get_or_create(
            document_type=document_type, defaults={"enabled": True, "after_days": 2}
        )


def unseed(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0002_depreciation_terms"),
        ("core", "0027_company_epf_etf"),
    ]

    operations = [migrations.RunSQL(SQL, BACKWARD), migrations.RunPython(seed, unseed)]
