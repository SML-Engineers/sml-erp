from django.urls import path

from . import attendance_views as av
from . import gratuity_views as gv
from . import leave_views as lv
from . import overtime_views as ov
from . import payroll_views as pr
from . import selfservice_views as me
from . import takeover_views as tv
from . import views as v

urlpatterns = [
    path("employees/", v.EmployeeListView.as_view(), name="employees"),
    path("detail-changes/", v.DetailChangesView.as_view(), name="detail-changes"),
    path(
        "detail-changes/<int:pk>/<str:action>/",
        v.DetailChangeDecideView.as_view(),
        name="detail-change-decide",
    ),
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
    path("attendance/punches/", av.PunchBringInView.as_view(), name="attendance-punches"),
    path("punch-sites/", av.PunchSitesView.as_view(), name="punch-sites"),
    path("punch-sites/<int:pk>/", av.PunchSiteView.as_view(), name="punch-site"),
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
    path("payroll-returns/<str:kind>/", pr.ReturnView.as_view(), name="payroll-return"),
    path("my/", me.MySummaryView.as_view(), name="my-summary"),
    path("my/payslips/<int:pk>/", me.MyPayslipView.as_view(), name="my-payslip"),
    path("my/apit-certificate/", me.MyCertificateView.as_view(), name="my-certificate"),
    path("my/leave/", me.MyLeaveView.as_view(), name="my-leave"),
    path("payroll-takeover/", tv.TakeoverView.as_view(), name="takeover"),
    path(
        "payroll-takeover/pay-template/", tv.PayTemplateView.as_view(), name="takeover-pay-template"
    ),
    path("payroll-takeover/pay/", tv.PayImportView.as_view(), name="takeover-pay"),
    path(
        "payroll-takeover/opening-template/",
        tv.OpeningTemplateView.as_view(),
        name="takeover-opening-template",
    ),
    path("payroll-takeover/opening/", tv.OpeningImportView.as_view(), name="takeover-opening"),
    path(
        "payroll-takeover/opening/<int:pk>/<str:action>/",
        tv.OpeningDecideView.as_view(),
        name="takeover-opening-decide",
    ),
    path(
        "payroll-takeover/compare-template/<int:run>/",
        tv.CompareTemplateView.as_view(),
        name="takeover-compare-template",
    ),
    path("payroll-takeover/compare/<int:run>/", tv.CompareView.as_view(), name="takeover-compare"),
    path(
        "payroll-takeover/checks/<int:pk>/sign-off/",
        tv.SignOffView.as_view(),
        name="takeover-sign-off",
    ),
    path("gratuity/", gv.GratuityView.as_view(), name="gratuity"),
    path(
        "gratuity/settings/<int:pk>/<str:action>/",
        gv.GratuitySettingView.as_view(),
        name="gratuity-setting",
    ),
    path("my/clock/", me.MyPunchView.as_view(), name="my-clock"),
    path("my/details/", me.MyDetailsView.as_view(), name="my-details"),
    path(
        "my/details/<int:pk>/withdraw/",
        me.MyDetailsWithdrawView.as_view(),
        name="my-details-withdraw",
    ),
    path("my/location-consent/", me.MyLocationConsentView.as_view(), name="my-location-consent"),
    path("my/leave/<int:pk>/withdraw/", me.MyLeaveWithdrawView.as_view(), name="my-leave-withdraw"),
    path(
        "my/team-leave/<int:pk>/<str:action>/",
        me.TeamLeaveDecideView.as_view(),
        name="team-leave-decide",
    ),
    path("staff-credits/", pr.StaffCreditListView.as_view(), name="staff-credits"),
    path("staff-credits/<int:pk>/", pr.StaffCreditDetailView.as_view(), name="staff-credit"),
    path(
        "staff-credits/<int:pk>/<str:action>/",
        pr.StaffCreditActionView.as_view(),
        name="staff-credit-action",
    ),
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
