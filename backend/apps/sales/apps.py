from django.apps import AppConfig


class SalesConfig(AppConfig):
    name = "apps.sales"
    label = "sales"
    verbose_name = "Sales documents"

    def ready(self):
        from apps.core.audit import register

        from . import models as m

        for model in (
            m.Quotation,
            m.QuotationLine,
            m.QuotationQtyBreak,
            m.QuotationFile,
            m.QuotationCosting,
            m.QuotationCostingOperation,
            m.QuotationCostingExtra,
            m.CustomerAdvance,
            m.ProformaInvoice,
            m.ProformaLine,
            m.SalesOrder,
            m.SalesOrderLine,
            m.DeliverySchedule,
        ):
            register(model)
