from django.apps import AppConfig


class AssetsConfig(AppConfig):
    name = "apps.assets"
    label = "assets"
    verbose_name = "Fixed assets"

    def ready(self):
        from apps.core.audit import register

        from .models import AssetClass, AssetClassRate, DepreciationRun, FixedAsset

        register(AssetClass)
        register(AssetClassRate)
        register(FixedAsset)
        register(DepreciationRun)
