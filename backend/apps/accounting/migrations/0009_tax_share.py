from django.db import migrations, models

# Taxes charged on a share of the amount (backlog P16-17; owner's decision of 2 Nov 2026).
# SSCL is 2.5% of "liable turnover", and the liable share depends on the kind of supply:
# 85% for goods the company manufactures (2.125%), 100% for services, 50% for goods bought in
# and resold (1.25%). Each kind gets its own tax code, chosen per line; the SSCL rate stays one
# dated rate (2.5%), so a change in the law is one new rate. To be confirmed by the tax
# advisor; the Accountant can add or switch off codes on the Taxes page.

NEW_CODES = [
    (
        "VAT-SSCL-M",
        "Manufactured goods: SSCL on 85%, then VAT",
        "Goods SML makes. SSCL 2.5% on 85% of the amount (2.125%), then VAT on the amount "
        "plus SSCL.",
        "85.00",
    ),
    (
        "VAT-SSCL-R",
        "Resold goods: SSCL on 50%, then VAT",
        "Goods bought in and sold on unchanged. SSCL 2.5% on 50% of the amount (1.25%), then "
        "VAT on the amount plus SSCL.",
        "50.00",
    ),
]


def add_codes(apps, schema_editor):
    TaxCode = apps.get_model("accounting", "TaxCode")
    TaxCodeLine = apps.get_model("accounting", "TaxCodeLine")
    TaxComponent = apps.get_model("accounting", "TaxComponent")
    sscl = TaxComponent.objects.filter(code="SSCL").first()
    vat = TaxComponent.objects.filter(code="VAT").first()
    if sscl is None or vat is None:
        return
    for code, name, description, share in NEW_CODES:
        if TaxCode.objects.filter(code=code).exists():
            continue
        tax_code = TaxCode.objects.create(
            code=code, name=name, description=description, use="both"
        )
        TaxCodeLine.objects.create(
            tax_code=tax_code, sequence=1, component=sscl, base="net", portion_pct=share
        )
        TaxCodeLine.objects.create(
            tax_code=tax_code, sequence=2, component=vat, base="net_and_tax", portion_pct="100.00"
        )
    old = TaxCode.objects.filter(code="VAT-SSCL", first_used_at__isnull=True).first()
    if old is not None:
        TaxCode.objects.filter(pk=old.pk).update(
            name="Services: SSCL on 100%, then VAT",
            description="Services (and imports). SSCL 2.5% on the whole amount, then VAT on the "
            "amount plus SSCL.",
        )


class Migration(migrations.Migration):
    dependencies = [("accounting", "0008_manual_journals")]

    operations = [
        migrations.AddField(
            model_name="taxcodeline",
            name="portion_pct",
            field=models.DecimalField(decimal_places=2, default=100, max_digits=5),
        ),
        migrations.AddConstraint(
            model_name="taxcodeline",
            constraint=models.CheckConstraint(
                condition=models.Q(("portion_pct__gt", 0), ("portion_pct__lte", 100)),
                name="accounting_taxcodeline_portion_range",
            ),
        ),
        migrations.RunPython(add_codes, migrations.RunPython.noop),
    ]
