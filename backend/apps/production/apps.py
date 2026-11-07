from django.apps import AppConfig


class ProductionConfig(AppConfig):
    name = "apps.production"
    label = "production"
    verbose_name = "Production"

    def ready(self):
        from apps.core.audit import register

        from .models import (
            Mould,
            MouldPart,
            ProductionSetting,
            ReasonCode,
            Routing,
            RoutingOperation,
        )

        for model in (Mould, MouldPart, ReasonCode, ProductionSetting, Routing, RoutingOperation):
            register(model)
