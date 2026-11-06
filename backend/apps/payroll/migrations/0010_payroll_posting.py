import django.db.models.deletion
from django.db import migrations, models

# P2B-07: an approved payroll gets a number (series "payroll") and posts a journal entry.
SERIES = ("payroll", "Payrolls", "PR{YY}{MM}{XX}", "monthly", "grow")


def seed(apps, schema_editor):
    NumberSeries = apps.get_model("core", "NumberSeries")
    document_type, name, number_format, reset, when_full = SERIES
    NumberSeries.objects.get_or_create(
        document_type=document_type,
        defaults={
            "name": name,
            "format": number_format,
            "reset_period": reset,
            "when_full": when_full,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0009_payroll_run"),
        ("accounting", "0022_payroll_roles"),
        ("core", "0026_sentemail_other_attachments"),
    ]

    operations = [
        migrations.AddField(
            model_name="payrollrun",
            name="number",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="payrollrun",
            name="journal_entry",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="accounting.journalentry",
            ),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
