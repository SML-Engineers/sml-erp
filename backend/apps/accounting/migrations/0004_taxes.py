import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Taxes (backlog P0-20): tax components with dated rates, tax codes made of components,
# and a default tax code per account. The database refuses:
# - changing the code of a component or tax code once a document has used it, or deleting
#   it (masters_code_guard);
# - changing or removing a rate in force (Sri Lanka date) of a component already used;
# - changing the make-up of a tax code once a document has used it.
#
# Starting components and codes are suggestions only, with no rates: the Accountant checks
# them, enters the rates in force, and adds others, as in QuickBooks.

TAX_CODE_REGEX = r"^[A-Z0-9][A-Z0-9-]{0,19}$"

FORWARD = """
CREATE TRIGGER accounting_taxcomponent_guard
BEFORE UPDATE OR DELETE ON accounting_taxcomponent
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();

CREATE TRIGGER accounting_taxcode_guard
BEFORE UPDATE OR DELETE ON accounting_taxcode
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();

CREATE OR REPLACE FUNCTION accounting_taxrate_guard() RETURNS trigger AS $$
BEGIN
  IF OLD.effective_from <= (now() AT TIME ZONE 'Asia/Colombo')::date AND EXISTS (
    SELECT 1 FROM accounting_taxcomponent c
    WHERE c.id = OLD.component_id AND c.first_used_at IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'The rate in force since % has been used and cannot change; add a new rate',
      OLD.effective_from USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_taxrate_guard
BEFORE UPDATE OR DELETE ON accounting_taxrate
FOR EACH ROW EXECUTE FUNCTION accounting_taxrate_guard();

CREATE OR REPLACE FUNCTION accounting_taxcodeline_guard() RETURNS trigger AS $$
DECLARE
  code_id bigint;
BEGIN
  IF TG_OP = 'INSERT' THEN
    code_id := NEW.tax_code_id;
  ELSE
    code_id := OLD.tax_code_id;
  END IF;
  IF EXISTS (
    SELECT 1 FROM accounting_taxcode t WHERE t.id = code_id AND t.first_used_at IS NOT NULL
  ) THEN
    RAISE EXCEPTION 'This tax code has been used: its taxes cannot change; make a new tax code'
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER accounting_taxcodeline_guard
BEFORE INSERT OR UPDATE OR DELETE ON accounting_taxcodeline
FOR EACH ROW EXECUTE FUNCTION accounting_taxcodeline_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS accounting_taxcodeline_guard ON accounting_taxcodeline;
DROP FUNCTION IF EXISTS accounting_taxcodeline_guard();
DROP TRIGGER IF EXISTS accounting_taxrate_guard ON accounting_taxrate;
DROP FUNCTION IF EXISTS accounting_taxrate_guard();
DROP TRIGGER IF EXISTS accounting_taxcode_guard ON accounting_taxcode;
DROP TRIGGER IF EXISTS accounting_taxcomponent_guard ON accounting_taxcomponent;
"""

# (code, name, kind, sales account number, purchase account number)
COMPONENTS_V1 = [
    ("VAT", "Value added tax", "charged", "2100", "1340"),
    ("SSCL", "Social security contribution levy", "charged", "2110", None),
    ("WHT", "Withholding tax", "withheld", "2120", "1350"),
]
# (code, name, use, [(component, base)])
CODES_V1 = [
    (
        "VAT-SSCL",
        "SSCL, then VAT on the amount plus SSCL",
        "both",
        [("SSCL", "net"), ("VAT", "net_and_tax")],
    ),
    ("VAT", "VAT only", "both", [("VAT", "net")]),
    ("EXEMPT", "VAT exempt supply", "both", []),
    ("NO-TAX", "Out of scope: no tax", "both", []),
]


def load(apps, schema_editor):
    Account = apps.get_model("accounting", "Account")
    TaxComponent = apps.get_model("accounting", "TaxComponent")
    TaxCode = apps.get_model("accounting", "TaxCode")
    TaxCodeLine = apps.get_model("accounting", "TaxCodeLine")
    if TaxComponent.objects.exists():
        return

    def account(number):
        return Account.objects.filter(number=number).first() if number else None

    components = {}
    for code, name, kind, sales, purchases in COMPONENTS_V1:
        components[code] = TaxComponent.objects.create(
            code=code,
            name=name,
            kind=kind,
            sales_account=account(sales),
            purchase_account=account(purchases),
        )
    for code, name, use, parts in CODES_V1:
        tax_code = TaxCode.objects.create(code=code, name=name, use=use)
        for sequence, (component, base) in enumerate(parts, start=1):
            TaxCodeLine.objects.create(
                tax_code=tax_code, sequence=sequence, component=components[component], base=base
            )


def big_id():
    return models.BigAutoField(
        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
    )


def account_fk():
    return models.ForeignKey(
        blank=True,
        null=True,
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to="accounting.account",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("accounting", "0003_journal_periods"),
        ("masters", "0002_seed_and_guards"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="TaxComponent",
            fields=[
                ("id", big_id()),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("charged", "Charged on invoices and bills (VAT, SSCL…)"),
                            ("withheld", "Withheld from payments (WHT…)"),
                        ],
                        default="charged",
                        max_length=10,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
                ("purchase_account", account_fk()),
                ("sales_account", account_fk()),
            ],
            options={
                "ordering": ["code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("code__regex", TAX_CODE_REGEX)),
                        name="accounting_taxcomponent_code",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="TaxCode",
            fields=[
                ("id", big_id()),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("description", models.CharField(blank=True, max_length=300)),
                (
                    "use",
                    models.CharField(
                        choices=[
                            ("both", "Sales and purchases"),
                            ("sales", "Sales only"),
                            ("purchases", "Purchases only"),
                        ],
                        default="both",
                        max_length=10,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
            ],
            options={
                "ordering": ["code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("code__regex", TAX_CODE_REGEX)),
                        name="accounting_taxcode_code",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="TaxRate",
            fields=[
                ("id", big_id()),
                ("effective_from", models.DateField()),
                ("rate", models.DecimalField(decimal_places=4, max_digits=7)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rates",
                        to="accounting.taxcomponent",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["component", "-effective_from"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("component", "effective_from"),
                        name="accounting_taxrate_one_per_day",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("rate__gte", 0), ("rate__lte", 100)),
                        name="accounting_taxrate_percent",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="TaxCodeLine",
            fields=[
                ("id", big_id()),
                ("sequence", models.PositiveSmallIntegerField()),
                (
                    "base",
                    models.CharField(
                        choices=[
                            ("net", "On the net amount"),
                            ("net_and_tax", "On the net amount plus the taxes above"),
                        ],
                        default="net",
                        max_length=12,
                    ),
                ),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="in_codes",
                        to="accounting.taxcomponent",
                    ),
                ),
                (
                    "tax_code",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="lines",
                        to="accounting.taxcode",
                    ),
                ),
            ],
            options={
                "ordering": ["tax_code", "sequence"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("tax_code", "sequence"), name="accounting_taxcodeline_sequence"
                    ),
                    models.UniqueConstraint(
                        fields=("tax_code", "component"),
                        name="accounting_taxcodeline_component_once",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="account",
            name="default_tax_code",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="default_for",
                to="accounting.taxcode",
            ),
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(load, migrations.RunPython.noop),
    ]
