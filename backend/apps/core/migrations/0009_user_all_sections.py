from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_number_series"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="all_sections",
            field=models.BooleanField(default=True),
        ),
    ]
