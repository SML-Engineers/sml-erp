from django.db import migrations, models

# Owner, 12 Nov 2026: a company-wide switch for two-factor sign-in (on by default).


class Migration(migrations.Migration):
    dependencies = [("core", "0027_company_epf_etf")]

    operations = [
        migrations.AddField(
            model_name="company",
            name="two_factor_on",
            field=models.BooleanField(default=True, verbose_name="Two-factor sign-in"),
        ),
    ]
