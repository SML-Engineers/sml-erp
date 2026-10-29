from django.db import migrations, models

# Two more approval outcomes (backlog P1-04b): a document withdrawn by its module (a voucher
# deleted), and a later approver's change that sends it back to the first approval level
# (the Director changing a voucher's payee, amount or lines). Both need a reason.


class Migration(migrations.Migration):
    dependencies = [("core", "0013_document_email")]

    operations = [
        migrations.AlterField(
            model_name="approvalstate",
            name="status",
            field=models.CharField(
                choices=[
                    ("in_progress", "Waiting for approval"),
                    ("approved", "Approved"),
                    ("returned", "Returned"),
                    ("rejected", "Rejected"),
                    ("withdrawn", "Withdrawn"),
                ],
                max_length=20,
            ),
        ),
        migrations.AlterField(
            model_name="approvallog",
            name="action",
            field=models.CharField(
                choices=[
                    ("submit", "Submitted"),
                    ("approve", "Approved"),
                    ("return", "Returned"),
                    ("reject", "Rejected"),
                    ("send_down", "Changed and sent back"),
                    ("withdraw", "Withdrawn"),
                ],
                max_length=10,
            ),
        ),
        migrations.RemoveConstraint(
            model_name="approvallog", name="core_approvallog_reason_required"
        ),
        migrations.AddConstraint(
            model_name="approvallog",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    models.Q(
                        ("action__in", ["return", "reject", "send_down", "withdraw"]),
                        _negated=True,
                    ),
                    ("reason__regex", "\\S"),
                    _connector="OR",
                ),
                name="core_approvallog_reason_required",
            ),
        ),
    ]
