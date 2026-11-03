import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

# Credit control and payment reminders (backlog P2-08).
# - Credit holds: the database refuses deleting a hold, changing an allowed one, changing what
#   document and customer a hold is for or who asked, and allowing one without who and when.
# - Reminders sent are insert-only.

FORWARD = """
CREATE OR REPLACE FUNCTION sales_credit_hold_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'A credit hold is never deleted' USING ERRCODE = 'restrict_violation';
  END IF;
  IF OLD.status = 'allowed' THEN
    RAISE EXCEPTION 'Credit hold % was allowed and never changes', OLD.id
      USING ERRCODE = 'restrict_violation';
  END IF;
  IF NEW.document_type IS DISTINCT FROM OLD.document_type
     OR NEW.document_id IS DISTINCT FROM OLD.document_id
     OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
     OR NEW.requested_by_id IS DISTINCT FROM OLD.requested_by_id THEN
    RAISE EXCEPTION 'What a credit hold is for never changes' USING ERRCODE = 'restrict_violation';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_credit_hold_guard
BEFORE UPDATE OR DELETE ON sales_credithold
FOR EACH ROW EXECUTE FUNCTION sales_credit_hold_guard();

CREATE OR REPLACE FUNCTION sales_reminder_sent_guard() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Reminders sent are a record and never change' USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER sales_reminder_sent_guard
BEFORE UPDATE OR DELETE ON sales_remindersent
FOR EACH ROW EXECUTE FUNCTION sales_reminder_sent_guard();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS sales_reminder_sent_guard ON sales_remindersent;
DROP FUNCTION IF EXISTS sales_reminder_sent_guard();
DROP TRIGGER IF EXISTS sales_credit_hold_guard ON sales_credithold;
DROP FUNCTION IF EXISTS sales_credit_hold_guard();
"""


def id_field():
    return (
        "id",
        models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
    )


def fk(to, related_name="+", null=False):
    extra = {"blank": True, "null": True} if null else {}
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT, related_name=related_name, to=to, **extra
    )


def money(**extra):
    return models.DecimalField(decimal_places=2, max_digits=18, **extra)


class Migration(migrations.Migration):
    dependencies = [
        ("sales", "0012_customer_receipts"),
        ("core", "0023_credit_hold_action"),
        ("masters", "0011_limit_no_maximum"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CreditHold",
            fields=[
                id_field(),
                (
                    "document_type",
                    models.CharField(
                        choices=[("sales_order", "Sales order"), ("tax_invoice", "Tax invoice")],
                        max_length=20,
                    ),
                ),
                ("document_id", models.BigIntegerField()),
                ("document_label", models.CharField(max_length=100)),
                ("amount_lkr", money()),
                ("exposure_lkr", money()),
                ("credit_limit", money(blank=True, null=True)),
                ("overdue_lkr", money(default=0)),
                ("reasons", models.TextField()),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("waiting", "Waiting for the Director"),
                            ("allowed", "Allowed by the Director"),
                        ],
                        default="waiting",
                        max_length=10,
                    ),
                ),
                ("requested_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("note", models.TextField(blank=True)),
                ("customer", fk("masters.customer", "credit_holds")),
                ("requested_by", fk(settings.AUTH_USER_MODEL)),
                ("decided_by", fk(settings.AUTH_USER_MODEL, null=True)),
            ],
            options={
                "ordering": ["-requested_at", "-id"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(status="waiting")
                        | (models.Q(decided_by__isnull=False) & models.Q(decided_at__isnull=False)),
                        name="sales_credit_hold_decided",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ReminderPlan",
            fields=[
                id_field(),
                ("is_on", models.BooleanField(default=False)),
                ("every_days", models.PositiveSmallIntegerField(default=7)),
                ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "customer",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="reminder_plan",
                        to="masters.customer",
                    ),
                ),
                ("set_by", fk(settings.AUTH_USER_MODEL)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(every_days__gte=1) & models.Q(every_days__lte=90),
                        name="sales_reminder_every_days",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="ReminderSent",
            fields=[
                id_field(),
                ("amount_due_lkr", money()),
                ("overdue_lkr", money()),
                ("sent_on", models.DateField()),
                ("customer", fk("masters.customer", "reminders_sent")),
                (
                    "email",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="core.sentemail",
                    ),
                ),
            ],
            options={"ordering": ["-sent_on", "-id"]},
        ),
        migrations.RunSQL(FORWARD, BACKWARD),
    ]
