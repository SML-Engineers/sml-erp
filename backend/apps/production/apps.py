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
            JobCardEntry,
            JobCardReject,
            JobExcess,
            JobInspection,
            JobInspectionResult,
            JobIssue,
            JobMaterial,
            JobOperation,
            JobOrder,
            ManpowerEntry,
            MaterialEntry,
            Mould,
            MouldingRun,
            MouldMaintenance,
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
            SubcontractDispatch,
            SubcontractReturn,
        )

        for model in (
            JobCardEntry,
            JobCardReject,
            JobOrder,
            JobOperation,
            JobMaterial,
            JobIssue,
            JobExcess,
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
            MouldMaintenance,
            SubcontractDispatch,
            SubcontractReturn,
            JobInspection,
            JobInspectionResult,
        ):
            register(model)
