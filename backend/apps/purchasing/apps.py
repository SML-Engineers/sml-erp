from django.apps import AppConfig


class PurchasingConfig(AppConfig):
    name = "apps.purchasing"
    label = "purchasing"
    verbose_name = "Purchasing"

    def ready(self):
        from apps.core.audit import register

        from . import models as m

        register(m.PurchaseOrder)
        register(m.PurchaseOrderLine)
        register(m.SupplierInvoice)
        register(m.SupplierInvoiceLine)
        register(m.SupplierInvoiceAttachment)
