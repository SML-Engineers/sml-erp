from django.apps import AppConfig


class AccountingConfig(AppConfig):
    name = "apps.accounting"
    label = "accounting"
    verbose_name = "Accounting"

    def ready(self):
        from apps.core.audit import register

        from . import models as m

        register(m.DetailType)
        register(m.Account)
        register(m.AccountingPeriod)
        register(m.JournalEntry)
