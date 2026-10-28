from django.apps import AppConfig


class VouchersConfig(AppConfig):
    name = "apps.vouchers"
    label = "vouchers"
    verbose_name = "Payment vouchers"

    def ready(self):
        from apps.core.audit import register

        from . import models as m

        register(m.VoucherType)
