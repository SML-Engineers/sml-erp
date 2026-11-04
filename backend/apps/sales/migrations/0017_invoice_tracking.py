import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Invoice tracking (backlog P2-27): the secret customer link of an issued tax invoice, the
# views of it, and the OnePay card payment links sent. Views and card links are insert-only.

FORWARD = """
CREATE TRIGGER sales_invoiceview_insert_only
BEFORE UPDATE OR DELETE ON sales_invoiceview
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();

CREATE TRIGGER sales_cardpaymentlink_insert_only
BEFORE UPDATE OR DELETE ON sales_cardpaymentlink
FOR EACH ROW EXECUTE FUNCTION core_refuse_change();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS sales_cardpaymentlink_insert_only ON sales_cardpaymentlink;
DROP TRIGGER IF EXISTS sales_invoiceview_insert_only ON sales_invoiceview;
"""

ID = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0016_quotation_images"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="InvoiceLink",
            fields=[
                ("id", ID.clone()),
                ("token", models.CharField(max_length=64, unique=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "invoice",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="link",
                        to="sales.taxinvoice",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="InvoiceView",
            fields=[
                ("id", ID.clone()),
                (
                    "what",
                    models.CharField(
                        choices=[
                            ("page", "Opened the invoice page"),
                            ("pdf", "Downloaded the PDF"),
                        ],
                        max_length=10,
                    ),
                ),
                ("viewed_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "invoice",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="views",
                        to="sales.taxinvoice",
                    ),
                ),
            ],
            options={"ordering": ["viewed_at", "id"]},
        ),
        migrations.CreateModel(
            name="CardPaymentLink",
            fields=[
                ("id", ID.clone()),
                ("url", models.URLField(max_length=500)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=18)),
                ("sent_on", models.DateField()),
                ("note", models.CharField(blank=True, max_length=300)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "invoice",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="card_links",
                        to="sales.taxinvoice",
                    ),
                ),
            ],
            options={
                "ordering": ["sent_on", "id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("amount__gt", 0)),
                        name="sales_cardlink_amount_positive",
                    )
                ],
            },
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
