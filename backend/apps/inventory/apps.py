from django.apps import AppConfig


class InventoryConfig(AppConfig):
    name = "apps.inventory"
    label = "inventory"
    verbose_name = "Items and stores"

    def ready(self):
        from apps.core.audit import register

        from . import models as m

        register(m.Item, exclude=("updated_at",))
        register(m.Store)
        register(m.GoodsReceipt)
        register(m.GoodsReceiptLine)
        register(m.GoodsReceiptPhoto)
