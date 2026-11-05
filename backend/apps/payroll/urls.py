from django.urls import path

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
]
