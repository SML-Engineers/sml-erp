from django.db import migrations

# Exports of goods are zero-rated for VAT and pay no SSCL (owner, 3 Nov 2026; P2-09): the tax
# code ZERO-RATED, with no tax on it, kept apart from EXEMPT and NO-TAX so the VAT return
# (P2-20) shows zero-rated supplies. Sales put it on every line for an export customer.


def add(apps, schema_editor):
    TaxCode = apps.get_model("accounting", "TaxCode")
    TaxCode.objects.get_or_create(
        code="ZERO-RATED",
        defaults={"name": "Zero-rated export: VAT 0%, no SSCL", "use": "sales"},
    )


class Migration(migrations.Migration):
    dependencies = [("accounting", "0013_line_customer")]

    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
