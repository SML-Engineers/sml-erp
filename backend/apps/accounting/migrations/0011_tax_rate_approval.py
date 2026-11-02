import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

# Tax rates kept in a control panel (backlog P16-20; owner's decision of 2 Nov 2026).
# - A change to a tax rate is entered by the Admin or the Accountant and takes effect only
#   when the Director confirms it; rates already entered are confirmed.
# - SSCL has its own tax for each kind of supply, with its own dated rates, as the owner
#   wants to enter them: SSCL-M (manufactured goods, 2.125% today), SSCL (services, 2.5%) and
#   SSCL-R (resold goods, 1.25%). All three print as "SSCL". The codes VAT-SSCL-M and
#   VAT-SSCL-R (migration 0009) use them, if not used yet.
# - The rate guard now protects confirmed rates only: a proposal can still be decided.

NEW = [
    ("SSCL-M", "SSCL on manufactured goods", "VAT-SSCL-M"),
    ("SSCL-R", "SSCL on resold goods", "VAT-SSCL-R"),
]

GUARD = """
CREATE OR REPLACE FUNCTION accounting_taxrate_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.status = 'confirmed'
     AND OLD.effective_from <= (now() AT TIME ZONE 'Asia/Colombo')::date
     AND EXISTS (
       SELECT 1 FROM accounting_taxcomponent c
       WHERE c.id = OLD.component_id AND c.first_used_at IS NOT NULL
     ) THEN
    RAISE EXCEPTION 'The rate in force since % has been used and cannot change; add a new rate',
      OLD.effective_from USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.status IN ('confirmed', 'rejected', 'withdrawn')
     AND NEW.status IS DISTINCT FROM OLD.status THEN
    RAISE EXCEPTION 'A tax rate that is % stays that way', OLD.status
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def components(apps, schema_editor):
    TaxComponent = apps.get_model("accounting", "TaxComponent")
    TaxCode = apps.get_model("accounting", "TaxCode")
    TaxCodeLine = apps.get_model("accounting", "TaxCodeLine")
    sscl = TaxComponent.objects.filter(code="SSCL").first()
    if sscl is None:
        return
    for code, name, tax_code in NEW:
        component, _ = TaxComponent.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "kind": "charged",
                "sales_account_id": sscl.sales_account_id,
                "purchase_account_id": sscl.purchase_account_id,
                "printed_as": "SSCL",
            },
        )
        found = TaxCode.objects.filter(code=tax_code, first_used_at__isnull=True).first()
        if found is None:
            continue
        TaxCodeLine.objects.filter(tax_code=found, component=sscl).update(
            component=component, portion_pct="100.00"
        )
        TaxCode.objects.filter(pk=found.pk).update(
            name=f"{name}, then VAT",
            description=f"{name} at its own rate (Settings → Tax rates), then VAT on the amount "
            "plus SSCL.",
        )
    TaxComponent.objects.filter(pk=sscl.pk, printed_as="").update(printed_as="SSCL")
    if sscl.first_used_at is None:
        TaxComponent.objects.filter(pk=sscl.pk).update(name="SSCL on services")


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0010_exchange_roles"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="taxcomponent",
            name="printed_as",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="taxrate",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "Waiting for the Director"),
                    ("confirmed", "Confirmed"),
                    ("rejected", "Rejected"),
                    ("withdrawn", "Withdrawn"),
                ],
                default="confirmed",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="taxrate", name="reason", field=models.TextField(blank=True)
        ),
        migrations.AddField(
            model_name="taxrate",
            name="decided_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="taxrate",
            name="decided_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="taxrate", name="decision_note", field=models.TextField(blank=True)
        ),
        migrations.RemoveConstraint(model_name="taxrate", name="accounting_taxrate_one_per_day"),
        migrations.AddConstraint(
            model_name="taxrate",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status__in", ["pending", "confirmed"])),
                fields=("component", "effective_from"),
                name="accounting_taxrate_one_per_day",
            ),
        ),
        migrations.AddConstraint(
            model_name="taxrate",
            constraint=models.UniqueConstraint(
                condition=models.Q(("status", "pending")),
                fields=("component",),
                name="accounting_taxrate_one_pending",
            ),
        ),
        migrations.RunSQL(GUARD, migrations.RunSQL.noop),
        migrations.RunPython(components, migrations.RunPython.noop),
    ]
