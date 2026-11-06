from django.urls import path

from . import attendance_views as av
from . import leave_views as lv
from . import overtime_views as ov
from . import payroll_views as pr
from . import views as v

urlpatterns = [
    path("employees/", v.EmployeeListView.as_view(), name="employees"),
    path("employees/excel/", v.EmployeeExcelView.as_view(), name="employees-excel"),
    path("employees/<int:pk>/", v.EmployeeDetailView.as_view(), name="employee"),
    path(
        "employees/<int:pk>/check-bank/",
        v.EmployeeBankCheckView.as_view(),
        name="employee-check-bank",
    ),
    path("employees/<int:pk>/leave/", v.EmployeeLeaveView.as_view(), name="employee-leave"),
    path("employees/<int:pk>/pay/", v.EmployeePayView.as_view(), name="employee-pay"),
    path(
        "employees/<int:pk>/pay-changes/",
        v.PayChangeListView.as_view(),
        name="employee-pay-changes",
    ),
    path("pay-changes/<int:pk>/", v.PayChangeDetailView.as_view(), name="pay-change"),
    path(
        "pay-changes/<int:pk>/<str:action>/",
        v.PayChangeActionView.as_view(),
        name="pay-change-action",
    ),
    path("attendance/", av.AttendanceView.as_view(), name="attendance"),
    path("attendance/template/", av.AttendanceTemplateView.as_view(), name="attendance-template"),
    path("attendance/import/", av.AttendanceImportView.as_view(), name="attendance-import"),
    path(
        "attendance/confirm/",
        av.AttendanceMonthActionView.as_view(action="confirm"),
        name="attendance-confirm",
    ),
    path(
        "attendance/reopen/",
        av.AttendanceMonthActionView.as_view(action="reopen"),
        name="attendance-reopen",
    ),
    path(
        "employees/<int:pk>/attendance/",
        av.AttendanceDaysView.as_view(),
        name="employee-attendance",
    ),
    path("work-rules/", ov.WorkRuleListView.as_view(), name="work-rules"),
    path("work-rules/<int:pk>/", ov.WorkRuleDetailView.as_view(), name="work-rule"),
    path("payroll/", pr.PayrollListView.as_view(), name="payroll"),
    path("payroll/<int:pk>/", pr.PayrollDetailView.as_view(), name="payroll-run"),
    path("payroll/<int:pk>/payslips/", pr.PayslipPdfView.as_view(), name="payroll-payslips"),
    path(
        "payroll/<int:pk>/email-payslips/",
        pr.PayslipEmailView.as_view(),
        name="payroll-email-payslips",
    ),
    path("payroll/<int:pk>/<str:action>/", pr.PayrollActionView.as_view(), name="payroll-action"),
    path("payroll-tax-tables/", pr.TaxTableView.as_view(), name="payroll-tax-tables"),
    path("pay-periods/", ov.PayPeriodListView.as_view(), name="pay-periods"),
    path("pay-periods/<int:pk>/", ov.PayPeriodDetailView.as_view(), name="pay-period"),
    path("overtime/", ov.OvertimeView.as_view(), name="overtime"),
    path("overtime/check/", ov.OvertimeCheckView.as_view(), name="overtime-check"),
    path("holidays/", lv.HolidayListView.as_view(), name="holidays"),
    path("holidays/<int:pk>/", lv.HolidayDetailView.as_view(), name="holiday"),
    path("leave-types/", lv.LeaveTypeListView.as_view(), name="leave-types"),
    path("leave-types/<int:pk>/", lv.LeaveTypeDetailView.as_view(), name="leave-type"),
    path("leave/", lv.LeaveListView.as_view(), name="leave"),
    path("leave/grant/", lv.LeaveGrantView.as_view(), name="leave-grant"),
    *[
        path(
            f"leave/<int:pk>/{name}/", lv.LeaveActionView.as_view(action=name), name=f"leave-{name}"
        )
        for name in ("approve", "reject", "cancel")
    ],
    path(
        "employees/<int:pk>/leave/balances/",
        lv.EmployeeLeaveBalanceView.as_view(),
        name="employee-leave-balances",
    ),
    path("pay-components/", v.PayComponentListView.as_view(), name="pay-components"),
    path("pay-components/<int:pk>/", v.PayComponentDetailView.as_view(), name="pay-component"),
]
