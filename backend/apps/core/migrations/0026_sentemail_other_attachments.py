from django.db import migrations, models

# Further files sent with a document email (a quotation's product pictures), listed by name
# and SHA-256 on the record.


class Migration(migrations.Migration):
    dependencies = [("core", "0025_credit_terms_action")]

    operations = [
        migrations.AddField(
            model_name="sentemail",
            name="other_attachments",
            field=models.TextField(blank=True),
        ),
    ]
