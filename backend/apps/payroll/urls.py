from django.urls import path

from . import attendance_views as av
from . import leave_views as lv
from . import overtime_views as ov
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
        "employees/<int:pk>/pay/<int:rate_pk>/",
        v.EmployeePayRateView.as_view(),
        name="employee-pay-rate",
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
