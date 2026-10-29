from django.apps import AppConfig


class PaymentsConfig(AppConfig):
    name = "apps.payments"
    label = "payments"
    verbose_name = "Supplier payments"

    def ready(self):
        from apps.core.audit import register

        from .models import SupplierPayment

        register(SupplierPayment)
