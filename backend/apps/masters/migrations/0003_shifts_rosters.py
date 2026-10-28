import datetime

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

# Shifts and rosters (backlog P0-10). Starts with the General shift, 08:00-17:00 with a
# one-hour break (spec 3A.2).


def load(apps, schema_editor):
    Shift = apps.get_model("masters", "Shift")
    Shift.objects.get_or_create(
        code="G",
        defaults={
            "name": "General",
            "start_time": datetime.time(8, 0),
            "end_time": datetime.time(17, 0),
            "break_minutes": 60,
        },
    )


def big_id():
    return models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_invoice_numbering"),
        ("masters", "0002_seed_and_guards"),
    ]

    operations = [
        migrations.CreateModel(
            name="Shift",
            fields=[
                ("id", big_id()),
                ("code", models.CharField(max_length=5, unique=True)),
                ("name", models.CharField(max_length=50, unique=True)),
                ("start_time", models.TimeField()),
                ("end_time", models.TimeField()),
                ("break_minutes", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"ordering": ["start_time", "code"]},
        ),
        migrations.CreateModel(
            name="RosterPattern",
            fields=[
                ("id", big_id()),
                ("name", models.CharField(max_length=100, unique=True)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="RosterPatternDay",
            fields=[
                ("id", big_id()),
                ("position", models.PositiveSmallIntegerField()),
                (
                    "pattern",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="days",
                        to="masters.rosterpattern",
                    ),
                ),
                (
                    "shift",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="pattern_days",
                        to="masters.shift",
                    ),
                ),
            ],
            options={
                "ordering": ["pattern", "position"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("pattern", "position"), name="masters_patternday_unique_position"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Crew",
            fields=[
                ("id", big_id()),
                ("code", models.CharField(max_length=10)),
                ("name", models.CharField(blank=True, max_length=100)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="crews",
                        to="core.division",
                    ),
                ),
            ],
            options={
                "ordering": ["division__code", "code"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("division", "code"), name="masters_crew_unique_code"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RosterAssignment",
            fields=[
                ("id", big_id()),
                ("start_date", models.DateField()),
                ("end_date", models.DateField(blank=True, null=True)),
                ("note", models.CharField(blank=True, max_length=200)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="roster_assignments",
                        to="core.division",
                    ),
                ),
                (
                    "pattern",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assignments",
                        to="masters.rosterpattern",
                    ),
                ),
                (
                    "section",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="roster_assignments",
                        to="masters.section",
                    ),
                ),
            ],
            options={
                "ordering": ["division__code", "-start_date"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("end_date__isnull", True),
                            ("end_date__gte", models.F("start_date")),
                            _connector="OR",
                        ),
                        name="masters_roster_dates_in_order",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="RosterCrew",
            fields=[
                ("id", big_id()),
                ("start_position", models.PositiveSmallIntegerField(default=0)),
                (
                    "assignment",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="crews",
                        to="masters.rosterassignment",
                    ),
                ),
                (
                    "crew",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rosters",
                        to="masters.crew",
                    ),
                ),
            ],
            options={
                "ordering": ["assignment", "crew__code"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("assignment", "crew"), name="masters_rostercrew_unique"
                    )
                ],
            },
        ),
        migrations.RunPython(load, migrations.RunPython.noop),
    ]
