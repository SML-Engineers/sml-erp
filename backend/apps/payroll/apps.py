from django.apps import AppConfig


class PayrollConfig(AppConfig):
    name = "apps.payroll"
    label = "payroll"
    verbose_name = "Payroll and people"

    def ready(self):
        from apps.core.audit import register

        from .models import Employee, PayComponent, PayRate

        register(Employee)
        register(PayComponent)
        register(PayRate)
