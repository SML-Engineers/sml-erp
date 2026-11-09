from datetime import date, timedelta

from django.db import migrations

# Owner, 9 Nov 2026: the default depreciation rates per class (straight line) are amended:
# Buildings 5%, Plant and machinery 10%, Computers and software 20%, Furniture and fittings
# 20%, Motor vehicles 20%. Furniture and computers were 25% (4 years); now 20% (5 years).
# Moulds and tooling keep the plant and machinery rate.
#
# A class rate may still be corrected until posted depreciation has used it (0001's guard):
# the owner's defaults of 8 Nov are corrected in place. If depreciation has already been
# posted with them, the old rate stays for those months and the new one starts the month
# after the last posted month.

AMENDED = {
    "BUILDINGS": ("5", 20),
    "PLANT": ("10", 10),
    "MOULDS": ("10", 10),
    "VEHICLES": ("20", 5),
    "FURNITURE": ("20", 5),
    "COMPUTERS": ("20", 5),
}
REASON = "Owner's amended defaults, 9 Nov 2026"


def amend(apps, schema_editor):
    AssetClass = apps.get_model("assets", "AssetClass")
    AssetClassRate = apps.get_model("assets", "AssetClassRate")
    DepreciationRun = apps.get_model("assets", "DepreciationRun")
    last = DepreciationRun.objects.filter(status="posted").order_by("-month_end").first()
    for code, (rate, years) in AMENDED.items():
        found = AssetClass.objects.filter(code=code).first()
        if found is None:
            continue
        current = (
            AssetClassRate.objects.filter(asset_class=found, status="approved")
            .order_by("-effective_from")
            .first()
        )
        if current is not None and current.method == "straight_line":
            if str(current.rate.normalize()) == rate and current.life_years == years:
                continue  # already as the owner wants
        if current is not None and (last is None or last.month_end < current.effective_from):
            current.method = "straight_line"
            current.rate = rate
            current.life_years = years
            current.reason = REASON
            current.save()
            continue
        start = (last.month_end + timedelta(days=1)) if last else date(2000, 1, 1)
        if (
            AssetClassRate.objects.filter(asset_class=found, effective_from=start)
            .exclude(status="rejected")
            .exists()
        ):
            continue
        AssetClassRate.objects.create(
            asset_class=found,
            effective_from=start,
            method="straight_line",
            rate=rate,
            life_years=years,
            status="approved",
            reason=REASON,
        )


def keep(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("assets", "0003_owner_defaults")]

    operations = [migrations.RunPython(amend, keep)]
