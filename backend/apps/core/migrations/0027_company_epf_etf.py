from django.db import migrations, models

# P2B-09: the company's EPF and ETF employer numbers, printed on the returns.


class Migration(migrations.Migration):
    dependencies = [("core", "0026_sentemail_other_attachments")]

    operations = [
        migrations.AddField(
            model_name="company",
            name="epf_employer_no",
            field=models.CharField(blank=True, max_length=30, verbose_name="EPF employer no."),
        ),
        migrations.AddField(
            model_name="company",
            name="etf_employer_no",
            field=models.CharField(blank=True, max_length=30, verbose_name="ETF employer no."),
        ),
    ]
