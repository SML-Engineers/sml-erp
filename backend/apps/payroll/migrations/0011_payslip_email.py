from django.db import migrations

from apps.core.email_catalogue import DEFAULT_TEMPLATES_V2

# P2B-08: the default message for emailing payslips (the Admin may change it).


def load(apps, schema_editor):
    EmailTemplate = apps.get_model("core", "EmailTemplate")
    for kind, (subject, body) in DEFAULT_TEMPLATES_V2.items():
        EmailTemplate.objects.get_or_create(
            document_type=kind, defaults={"subject": subject, "body": body}
        )


class Migration(migrations.Migration):
    dependencies = [
        ("payroll", "0010_payroll_posting"),
        ("core", "0026_sentemail_other_attachments"),
    ]

    operations = [migrations.RunPython(load, migrations.RunPython.noop)]
