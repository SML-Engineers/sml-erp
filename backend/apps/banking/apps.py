from django.apps import AppConfig


class BankingConfig(AppConfig):
    name = "apps.banking"
    label = "banking"
    verbose_name = "Banking"

    def ready(self):
        from apps.core.audit import register

        from .models import (
            BankReconciliation,
            BankRule,
            BankStatement,
            ChequeClearance,
            Deposit,
            DepositLine,
            PettyExpense,
            StatementMatch,
            StatementTemplate,
        )

        register(Deposit)
        register(DepositLine)
        register(ChequeClearance)
        register(StatementTemplate)
        register(BankStatement)
        register(StatementMatch)
        register(BankRule)
        register(BankReconciliation)
        register(PettyExpense)
