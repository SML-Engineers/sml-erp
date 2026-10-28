import django.utils.timezone
from django.db import migrations, models

# Voucher types (backlog P1-01, spec 4.1). The code of a type used on a voucher cannot
# change and the type cannot be deleted, only switched off (masters_code_guard).

TYPE_CODE_REGEX = r"^[A-Z][A-Z0-9]{1,9}$"

# (code, name, payment method, needs payee, payee category, advance, notes, order)
TYPES_V1 = [
    ("CHQ", "Cheque Payment", "cheque", True, "", False,
     "Cheque number, bank and cheque date recorded at payment", 10),
    ("ONL", "Online Payment", "transfer", True, "", False,
     "Transfer reference recorded at payment", 20),
    ("PCH", "Petty Cash", "cash", True, "", False,
     "Same three-level approval as every other type", 30),
    ("INT", "Internal Transfer", "internal", False, "", False,
     "No payee; both sides are company bank or cash accounts", 40),
    ("ADV", "Supplier Advance", "cheque_or_transfer", True, "supplier", True,
     "Paid before the invoice; later set off against the invoice", 50),
    ("RMB", "Staff Reimbursement", "any", True, "employee", False,
     "Payee is an employee, with receipts attached", 60),
]

FORWARD = """
CREATE TRIGGER vouchers_vouchertype_guard
BEFORE UPDATE OR DELETE ON vouchers_vouchertype
FOR EACH ROW EXECUTE FUNCTION masters_code_guard();
"""

BACKWARD = "DROP TRIGGER IF EXISTS vouchers_vouchertype_guard ON vouchers_vouchertype;"


def load(apps, schema_editor):
    VoucherType = apps.get_model("vouchers", "VoucherType")
    for code, name, method, payee, category, advance, notes, order in TYPES_V1:
        VoucherType.objects.get_or_create(
            code=code,
            defaults={
                "name": name,
                "payment_method": method,
                "needs_payee": payee,
                "payee_category": category,
                "is_advance": advance,
                "notes": notes,
                "sort_order": order,
            },
        )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("masters", "0002_seed_and_guards"),
    ]

    operations = [
        migrations.CreateModel(
            name="VoucherType",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.CharField(max_length=10, unique=True)),
                ("name", models.CharField(max_length=50, unique=True)),
                (
                    "payment_method",
                    models.CharField(
                        choices=[
                            ("cheque", "Cheque"),
                            ("transfer", "Bank transfer"),
                            ("cheque_or_transfer", "Cheque or bank transfer"),
                            ("cash", "Cash"),
                            ("internal", "Between the company's own accounts"),
                            ("any", "Any"),
                        ],
                        max_length=20,
                    ),
                ),
                ("needs_payee", models.BooleanField(default=True)),
                ("payee_category", models.CharField(blank=True, max_length=20)),
                ("is_advance", models.BooleanField(default=False)),
                ("notes", models.CharField(blank=True, max_length=300)),
                ("sort_order", models.PositiveSmallIntegerField(default=100)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
            ],
            options={
                "ordering": ["sort_order", "name"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("code__regex", TYPE_CODE_REGEX)),
                        name="vouchers_type_code_format",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(
                            ("needs_payee", True), ("payee_category", ""), _connector="OR"
                        ),
                        name="vouchers_type_no_payee_no_category",
                    ),
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
        migrations.RunPython(load, migrations.RunPython.noop),
    ]
