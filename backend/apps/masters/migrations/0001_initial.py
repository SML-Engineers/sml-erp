import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

CODE_REGEX = "^[A-Z0-9][A-Z0-9-]{0,19}$"


def dec(label, digits):
    return models.DecimalField(
        blank=True, decimal_places=1, max_digits=digits, null=True, verbose_name=label
    )


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("core", "0009_user_all_sections"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Section",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=100)),
                (
                    "category",
                    models.CharField(
                        blank=True,
                        choices=[("manual", "Manual"), ("cnc", "CNC")],
                        max_length=10,
                    ),
                ),
                (
                    "section_type",
                    models.CharField(
                        choices=[
                            ("machining", "Machining"),
                            ("moulding", "Moulding"),
                            ("support", "Support"),
                        ],
                        max_length=20,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
                (
                    "division",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sections",
                        to="core.division",
                    ),
                ),
                (
                    "supervisors",
                    models.ManyToManyField(
                        blank=True,
                        related_name="supervised_sections",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "users",
                    models.ManyToManyField(
                        blank=True, related_name="sections", to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
            options={
                "ordering": ["division__code", "code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("code__regex", CODE_REGEX)),
                        name="masters_section_code_format",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Machine",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("code", models.CharField(max_length=20, unique=True)),
                ("name", models.CharField(max_length=100)),
                ("make", models.CharField(blank=True, max_length=100)),
                ("model", models.CharField(blank=True, max_length=100)),
                ("serial_no", models.CharField(blank=True, max_length=100, verbose_name="Serial no.")),
                ("year", models.PositiveSmallIntegerField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("active", "Active"),
                            ("maintenance", "Under maintenance"),
                            ("retired", "Retired"),
                        ],
                        default="active",
                        max_length=20,
                    ),
                ),
                ("photo", models.FileField(blank=True, upload_to="machines/")),
                ("notes", models.TextField(blank=True)),
                ("clamping_force_t", dec("Clamping force (t)", 8)),
                ("max_shot_weight_g", dec("Maximum shot weight (g)", 10)),
                ("screw_diameter_mm", dec("Screw diameter (mm)", 7)),
                ("tie_bar_h_mm", dec("Tie-bar spacing, horizontal (mm)", 7)),
                ("tie_bar_v_mm", dec("Tie-bar spacing, vertical (mm)", 7)),
                ("max_mould_height_mm", dec("Maximum mould height (mm)", 7)),
                ("max_mould_thickness_mm", dec("Maximum mould thickness (mm)", 7)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("first_used_at", models.DateTimeField(blank=True, editable=False, null=True)),
                (
                    "section",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="machines",
                        to="masters.section",
                    ),
                ),
            ],
            options={
                "ordering": ["code"],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("code__regex", CODE_REGEX)),
                        name="masters_machine_code_format",
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="MachineRate",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("effective_from", models.DateField()),
                (
                    "rate",
                    models.DecimalField(
                        decimal_places=2, max_digits=18, verbose_name="Hourly rate (LKR)"
                    ),
                ),
                ("reason", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "machine",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="rates",
                        to="masters.machine",
                    ),
                ),
            ],
            options={
                "ordering": ["machine", "-effective_from"],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("machine", "effective_from"),
                        name="masters_machinerate_one_per_day",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("rate__gte", 0)), name="masters_rate_not_negative"
                    ),
                ],
            },
        ),
    ]
