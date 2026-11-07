from datetime import date
from decimal import Decimal

from django.db import migrations
from django.utils import timezone

# P3-02: the starting reject and downtime reasons per division (spec 7.4), which the Admin
# can rename, add to and deactivate; the production settings from the owner's answers of
# 7 Nov 2026; and the database guards: a used reason keeps its code and is never deleted, a
# setting in force never changes.

DOWNTIME = [
    # (code, name, planned, divisions)
    ("BREAKDOWN", "Machine breakdown", False, ("IM", "WS")),
    ("MOULD-CHANGE", "Mould change", False, ("IM",)),
    ("SETUP", "Setting up", False, ("IM", "WS")),
    ("POWER", "Power failure", False, ("IM", "WS")),
    ("NO-MATERIAL", "No material", False, ("IM", "WS")),
    ("NO-OPERATOR", "No operator", False, ("IM", "WS")),
    ("QC-HOLD", "Waiting for quality check", False, ("IM", "WS")),
    ("PLANNED-PM", "Planned maintenance", True, ("IM", "WS")),
    ("NO-PLAN", "Nothing planned", True, ("IM", "WS")),
]
REJECTS = {
    "IM": [
        ("SHORT-SHOT", "Short shot"),
        ("FLASH", "Flash"),
        ("SINK", "Sink marks"),
        ("BURN", "Burn marks"),
        ("WARP", "Warpage"),
        ("COLOUR", "Colour variation"),
        ("CONTAMINATION", "Contamination or black specks"),
        ("FLOW-LINES", "Flow or weld lines"),
        ("START-UP", "Start-up shots"),
        ("OTHER", "Other"),
    ],
    "WS": [
        ("DIMENSION", "Out of dimension"),
        ("SURFACE", "Surface finish"),
        ("MATERIAL", "Material defect"),
        ("SETUP-PIECE", "Setting-up piece"),
        ("TOOL", "Tool breakage"),
        ("OTHER", "Other"),
    ],
}

SQL = """
CREATE TRIGGER production_reason_guard
BEFORE UPDATE OR DELETE ON production_reasoncode
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();

CREATE TRIGGER production_setting_guard
BEFORE UPDATE OR DELETE ON production_productionsetting
FOR EACH ROW EXECUTE FUNCTION masters_rate_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS production_setting_guard ON production_productionsetting;
DROP TRIGGER IF EXISTS production_reason_guard ON production_reasoncode;
"""


def seed(apps, schema_editor):
    Division = apps.get_model("core", "Division")
    ReasonCode = apps.get_model("production", "ReasonCode")
    ProductionSetting = apps.get_model("production", "ProductionSetting")
    now = timezone.now().replace(microsecond=0)
    for division in Division.objects.filter(code__in=["IM", "WS"]):
        order = 0
        for code, name, planned, divisions in DOWNTIME:
            if division.code in divisions:
                order += 10
                ReasonCode.objects.get_or_create(
                    division=division,
                    kind="downtime",
                    code=code,
                    defaults={"name": name, "planned": planned, "sort_order": order},
                )
        for order, (code, name) in enumerate(REJECTS[division.code], start=1):
            ReasonCode.objects.get_or_create(
                division=division,
                kind="reject",
                code=code,
                defaults={"name": name, "sort_order": order * 10},
            )
    ProductionSetting.objects.get_or_create(
        effective_from=date(2026, 1, 1),
        defaults={
            "grace_hours": Decimal("4.0"),
            "reject_alert_pct": Decimal("5.00"),
            "overrun_alert_pct": Decimal("10.00"),
            "min_margin_pct": None,
            "reason": "Owner's answers of 7 Nov 2026 (backlog P3-02)",
            "created_at": now,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("production", "0004_reasons_settings"),
        ("masters", "0002_seed_and_guards"),
        ("core", "0027_company_epf_etf"),
    ]

    operations = [
        migrations.RunSQL(SQL, BACKWARD),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
