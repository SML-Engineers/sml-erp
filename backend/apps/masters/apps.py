from django.apps import AppConfig


class MastersConfig(AppConfig):
    name = "apps.masters"
    label = "masters"
    verbose_name = "Master data"

    def ready(self):
        from apps.core.audit import register

        from . import models as m

        register(m.Section)
        register(m.Machine)
        register(m.MachineRate)
