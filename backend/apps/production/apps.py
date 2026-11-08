from django.apps import AppConfig


class ProductionConfig(AppConfig):
    name = "apps.production"
    label = "production"
    verbose_name = "Production"

    def ready(self):
        from apps.core.audit import register

        from .models import (
            Bom,
            BomLine,
            BomOutput,
            CostRate,
            DowntimeEntry,
            ManpowerEntry,
            MaterialEntry,
            Mould,
            MouldingRun,
            MouldPart,
            OrderBomLine,
            PlanEntry,
            ProductionOrder,
            ProductionOrderDue,
            ProductionReceipt,
            ProductionSetting,
            ReasonCode,
            RejectEntry,
            Routing,
            RoutingOperation,
            ShiftCorrection,
            ShiftReport,
        )

        for model in (
            Mould,
            MouldPart,
            ReasonCode,
            ProductionSetting,
            Routing,
            RoutingOperation,
            Bom,
            BomLine,
            BomOutput,
            CostRate,
            ProductionOrder,
            ProductionOrderDue,
            OrderBomLine,
            PlanEntry,
            ShiftReport,
            MouldingRun,
            RejectEntry,
            DowntimeEntry,
            MaterialEntry,
            ManpowerEntry,
            ProductionReceipt,
            ShiftCorrection,
        ):
            register(model)
