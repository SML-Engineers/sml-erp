from django.db import migrations, models

# P2B-21: attendance from the fingerprint machine's file: each employee's fingerprint ID,
# and the import's kind.


class Migration(migrations.Migration):
    dependencies = [("payroll", "0016_takeover")]

    operations = [
        migrations.AddField(
            model_name="employee",
            name="device_id",
            field=models.CharField(blank=True, max_length=20, verbose_name="Fingerprint ID"),
        ),
        migrations.AddConstraint(
            model_name="employee",
            constraint=models.UniqueConstraint(
                condition=models.Q(("device_id", ""), _negated=True),
                fields=("device_id",),
                name="payroll_employee_device_id_once",
            ),
        ),
        migrations.AlterField(
            model_name="attendanceimport",
            name="kind",
            field=models.CharField(
                choices=[
                    ("sheet", "Excel sheet"),
                    ("punches", "Phone punches"),
                    ("device", "Fingerprint machine"),
                ],
                default="sheet",
                max_length=10,
            ),
        ),
    ]
