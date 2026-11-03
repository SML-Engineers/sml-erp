from django.apps import AppConfig


class BankingConfig(AppConfig):
    name = "apps.banking"
    label = "banking"
    verbose_name = "Banking"

    def ready(self):
        from apps.core.audit import register

        from .models import ChequeClearance, Deposit, DepositLine

        register(Deposit)
        register(DepositLine)
        register(ChequeClearance)
