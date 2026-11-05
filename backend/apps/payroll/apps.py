from django.apps import AppConfig


class PayrollConfig(AppConfig):
    name = "apps.payroll"
    label = "payroll"
    verbose_name = "Payroll and people"

    def ready(self):
        from apps.core.audit import register

        from .models import (
            AttendanceImport,
            AttendanceMonth,
            Employee,
            EmployeeSetting,
            Holiday,
            Leave,
            LeaveGrant,
            LeaveType,
            OvertimeCheck,
            PayChange,
            PayChangeLine,
            PayComponent,
            PayPeriodRule,
            PayRate,
            WorkRule,
        )

        register(Employee)
        register(PayComponent)
        register(PayRate)
        for model in (
            Holiday,
            LeaveType,
            LeaveGrant,
            Leave,
            AttendanceMonth,
            AttendanceImport,
            WorkRule,
            OvertimeCheck,
            PayPeriodRule,
            PayChange,
            PayChangeLine,
            EmployeeSetting,
        ):
            register(model)
