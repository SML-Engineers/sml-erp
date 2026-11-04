"""Roles, access levels and division scope (backlog P0-04, spec 1.1 and 1.2)."""

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import access
from apps.core.access_defaults import AREAS, STANDARD_ROLES_V1
from apps.core.models import AuditEvent, Division, Role, User, UserRole
from apps.core.permissions import AreaAccess

from .conftest import PASSWORD

pytestmark = pytest.mark.django_db


def person(email, *role_codes, divisions=(), all_divisions=False):
    """A fully signed-up user holding the given roles."""
    user = User.objects.create_user(
        email, email.split("@")[0].title(), PASSWORD, all_divisions=all_divisions
    )
    user.totp_confirmed_at = timezone.now()  # as if two-factor were already set up
    user.save()
    for code in role_codes:
        UserRole.objects.create(user=user, role=Role.objects.get(code=code))
    user.divisions.set(Division.objects.filter(code__in=divisions))
    return User.objects.get(pk=user.pk)


def as_user(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def admin():
    return person("admin@sml.lk", "system_admin", all_divisions=True)


# --- Standard roles and defaults --------------------------------------------------------


def test_standard_roles_are_loaded_with_phase_one_and_sales_roles_active():
    active = set(
        Role.objects.filter(is_standard=True, is_active=True).values_list("code", flat=True)
    )
    phase_one = {"system_admin", "director", "accountant", "clerk", "cashier", "auditor"}
    assert active == phase_one | {"sales_executive", "sales_manager"} | {
        "purchasing_officer",
        "store_supervisor",
        "qc_inspector",
    }  # Phase 1.5 (P15-01) and Phase 1.6 (P16-02)
    assert Role.objects.filter(is_standard=True).count() == len(STANDARD_ROLES_V1)


def test_divisions_ws_im_ho_are_loaded():
    assert list(Division.objects.values_list("code", flat=True)) == ["HO", "IM", "WS"]


def test_system_admin_has_no_access_to_money_or_finance_by_default(admin):
    rights = access.effective_access(admin)
    for area in ("payments", "banking", "accounting", "financial_reports"):
        assert not rights.has(area, "view"), area
    assert rights.has("users", "manage")
    assert rights.has("settings", "manage")
    assert not rights.can("record_payment")


def test_clerk_enters_vouchers_but_cannot_approve():
    clerk = person("clerk@sml.lk", "clerk")
    rights = access.effective_access(clerk)
    assert rights.has("vouchers", "enter")
    assert rights.has("vouchers", "view")
    assert not rights.has("vouchers", "approve")
    assert not rights.has("payments", "view")


def test_only_the_cashier_records_payments():
    holders = {
        code
        for code, (_, _, _, _, actions) in STANDARD_ROLES_V1.items()
        if "record_payment" in actions
    }
    assert holders == {"cashier"}


def test_auditor_reads_everything_and_changes_nothing():
    rights = access.effective_access(person("auditor@sml.lk", "auditor"))
    for area in AREAS:
        assert rights.has(area, "view"), area
        assert not rights.has(area, "enter")
        assert not rights.has(area, "approve")
        assert not rights.has(area, "manage")
    assert rights.actions == set()


def test_manage_includes_enter_and_view():
    rights = access.effective_access(person("acc@sml.lk", "accountant"))
    assert rights.has("accounting", "manage")
    assert rights.has("accounting", "enter")
    assert rights.has("accounting", "view")
    assert not rights.has("accounting", "approve")


def test_several_roles_add_up():
    rights = access.effective_access(person("two@sml.lk", "clerk", "auditor"))
    assert rights.has("vouchers", "enter")
    assert rights.has("financial_reports", "view")


def test_a_deactivated_role_grants_nothing():
    user = person("x@sml.lk", "clerk")
    Role.objects.filter(code="clerk").update(is_active=False)
    assert not access.effective_access(User.objects.get(pk=user.pk)).has("vouchers", "view")


def test_superuser_flag_alone_grants_nothing_but_first_admin_gets_admin_role():
    first = User.objects.create_superuser("first@sml.lk", "First Admin", PASSWORD)
    assert list(first.role_assignments.values_list("role__code", flat=True)) == ["system_admin"]
    assert first.all_divisions is True
    rights = access.effective_access(first)
    assert not rights.has("payments", "view")


# --- Server-side checks -----------------------------------------------------------------


def test_without_permission_the_api_refuses(admin):
    clerk = person("clerk@sml.lk", "clerk")
    assert as_user(clerk).get("/api/v1/users/").status_code == 403
    assert as_user(clerk).get("/api/v1/roles/").status_code == 403
    assert as_user(admin).get("/api/v1/users/").status_code == 200


def test_auditor_can_read_users_and_roles_but_not_change_them(admin):
    auditor = as_user(person("auditor@sml.lk", "auditor"))
    assert auditor.get("/api/v1/users/").status_code == 200
    assert auditor.get("/api/v1/roles/").status_code == 200
    assert (
        auditor.post("/api/v1/users/", {"email": "n@sml.lk", "full_name": "N"}).status_code == 403
    )
    clerk = person("clerk@sml.lk", "clerk")
    response = auditor.put(
        f"/api/v1/users/{clerk.pk}/roles/", {"roles": ["director"]}, format="json"
    )
    assert response.status_code == 403


def test_signed_in_user_owing_two_factor_setup_is_refused(admin):
    director = person("d@sml.lk", "director")
    director.totp_confirmed_at = None
    director.two_factor_required = True
    director.save()
    assert as_user(director).get("/api/v1/divisions/").status_code == 403


def test_my_access_is_sent_to_the_app():
    clerk = person("clerk@sml.lk", "clerk", divisions=["IM"])
    data = as_user(clerk).get("/api/v1/auth/me/").json()["user"]["access"]
    assert data["areas"]["vouchers"] == ["enter", "view"]
    assert "payments" not in data["areas"]
    assert data["divisions"] == ["IM"]


def test_every_endpoint_declares_its_access():
    """Rule 8: every API view either checks an area, or is on this reviewed list."""
    reviewed_without_area = {
        "health",  # public status check, no business data
        "CsrfView",
        "LoginView",
        "LoginVerifyView",
        "LogoutView",
        "MeView",
        "TwoFactorSetupView",
        "TwoFactorConfirmView",
        "PasswordChangeView",
        "LoginHistoryView",  # own records only
        "CatalogView",  # names of areas and levels, no business data
        "DivisionListView",  # filtered to the user's own divisions
        "DivisionDetailView",  # filtered to the user's own divisions
        "SectionPickerView",  # filtered to the user's own sections
        "MachinePickerView",  # filtered to the user's own sections
        "CurrencyPickerView",  # currency codes and names, no business data
        "RateLookupView",  # published exchange rates, no business data
        "NotificationListView",  # own notifications only
        "NotificationReadView",  # own notifications only
        "PreferenceView",  # own notification choices only
        # Petty cash (P2-17): a custodian may hold any role; each view shows only the floats
        # the user holds or, for accounts staff, may see, and the service checks every change.
        "PettyFloatListView",
        "PettyExpenseListView",
        "PettyExpenseDetailView",
        "PettySlipView",
    }

    def walk(patterns):
        for p in patterns:
            if isinstance(p, URLResolver):
                yield from walk(p.url_patterns)
            elif isinstance(p, URLPattern):
                yield p

    for pattern in walk(get_resolver().url_patterns):
        view_class = getattr(pattern.callback, "view_class", None) or getattr(
            pattern.callback, "cls", None
        )
        if view_class is None or not str(pattern.pattern).strip("^"):
            continue
        if view_class.__module__.startswith("django.contrib"):
            continue
        name = view_class.__name__ if view_class.__name__ != "WrappedAPIView" else "health"
        permissions = getattr(view_class, "permission_classes", [])
        if any(issubclass(p, AreaAccess) for p in permissions):
            assert getattr(view_class, "access_area", None) in AREAS, name
        else:
            assert name in reviewed_without_area, f"{name} has no area check"


# --- Division scope ---------------------------------------------------------------------


def test_users_see_only_their_divisions():
    moulding = as_user(person("m@sml.lk", "clerk", divisions=["IM"]))
    codes = [d["code"] for d in moulding.get("/api/v1/divisions/").json()]
    assert codes == ["IM"]
    assert moulding.get("/api/v1/divisions/IM/").status_code == 200
    assert moulding.get("/api/v1/divisions/WS/").status_code == 404


def test_all_divisions_scope_sees_every_division():
    everyone = as_user(person("e@sml.lk", "clerk", all_divisions=True))
    assert len(everyone.get("/api/v1/divisions/").json()) == 3


def test_scope_filter_limits_any_division_owned_records():
    user = person("m@sml.lk", "clerk", divisions=["IM"])
    # Division-owned records are filtered through the same function; divisions stand in here.
    queryset = access.filter_by_division(Division.objects.all(), user, field_name="pk")
    assert list(queryset.values_list("code", flat=True)) == ["IM"]


def test_admin_sets_a_users_divisions(admin):
    clerk = person("clerk@sml.lk", "clerk")
    response = as_user(admin).put(
        f"/api/v1/users/{clerk.pk}/scope/",
        {"all_divisions": False, "divisions": ["WS", "HO"]},
        format="json",
    )
    assert response.status_code == 200
    assert sorted(response.json()["divisions"]) == ["HO", "WS"]


# --- Role assignment --------------------------------------------------------------------


def test_admin_creates_a_user_with_a_temporary_password(admin):
    response = as_user(admin).post(
        "/api/v1/users/", {"email": "New@SML.lk", "full_name": "New Person"}, format="json"
    )
    assert response.status_code == 201
    created = User.objects.get(email="new@sml.lk")
    assert created.must_change_password is True
    assert created.check_password(response.json()["temporary_password"])


def test_a_new_user_stays_inactive_until_given_roles_and_divisions(admin):
    """Owner's decision (31 Oct 2026): the Admin sets the account up first, then activates it."""
    client = as_user(admin)
    made = client.post(
        "/api/v1/users/", {"email": "ajith@sml.lk", "full_name": "Ajith"}, format="json"
    ).json()
    assert made["is_active"] is False
    password = made["temporary_password"]
    signed_in = APIClient().post(
        "/api/v1/auth/login/", {"email": "ajith@sml.lk", "password": password}, format="json"
    )
    assert signed_in.status_code != 200

    url = f"/api/v1/users/{made['id']}/"
    refused = client.patch(url, {"is_active": True}, format="json")
    assert refused.status_code == 400
    assert refused.json()["detail"] == (
        "Give Ajith at least one role and the divisions they work in before activating the account."
    )
    client.put(f"{url}roles/", {"roles": ["sales_executive"]}, format="json")
    refused = client.patch(url, {"is_active": True}, format="json")
    assert "the divisions they work in" in refused.json()["detail"]
    client.put(f"{url}scope/", {"all_divisions": False, "divisions": ["IM"]}, format="json")
    activated = client.patch(url, {"is_active": True}, format="json")
    assert activated.status_code == 200 and activated.json()["is_active"] is True
    assert AuditEvent.objects.filter(event="user_activated").exists()


def test_finance_roles_switch_two_factor_on(admin):
    user = person("d@sml.lk")
    user.totp_confirmed_at = None
    user.save()
    as_user(admin).put(f"/api/v1/users/{user.pk}/roles/", {"roles": ["director"]}, format="json")
    user.refresh_from_db()
    assert user.two_factor_required is True


def test_conflicting_roles_need_a_reason_which_is_recorded(admin):
    user = person("c@sml.lk")
    url = f"/api/v1/users/{user.pk}/roles/"

    refused = as_user(admin).put(url, {"roles": ["clerk", "cashier"]}, format="json")
    assert refused.status_code == 400
    assert refused.json()["warnings"]
    assert not user.role_assignments.exists()

    accepted = as_user(admin).put(
        url,
        {"roles": ["clerk", "cashier"], "reason": "Only one finance staff member this month"},
        format="json",
    )
    assert accepted.status_code == 200
    assignment = user.role_assignments.get(role__code="cashier")
    assert assignment.reason == "Only one finance staff member this month"
    assert "Cashier" in assignment.conflict_warning
    assert assignment.assigned_by == admin


def test_admin_with_a_finance_role_is_a_conflict():
    assert access.conflict_warnings({"system_admin", "accountant"})


def test_admin_cannot_change_their_own_roles_or_scope(admin):
    me = as_user(admin)
    roles = me.put(f"/api/v1/users/{admin.pk}/roles/", {"roles": ["director"]}, format="json")
    scope = me.put(
        f"/api/v1/users/{admin.pk}/scope/", {"all_divisions": True, "divisions": []}, format="json"
    )
    deactivate = me.patch(f"/api/v1/users/{admin.pk}/", {"is_active": False}, format="json")
    assert roles.status_code == scope.status_code == deactivate.status_code == 403


def test_later_phase_roles_cannot_be_assigned_yet(admin):
    user = person("s@sml.lk")
    response = as_user(admin).put(
        f"/api/v1/users/{user.pk}/roles/", {"roles": ["production_planner"]}, format="json"
    )
    assert response.status_code == 400


# --- Phase 1.6 roles (P16-02, spec 5A.6) ----------------------------------------------------


def test_purchasing_stores_and_qc_roles_can_be_assigned(admin):
    stores = Role.objects.get(code="store_supervisor")
    assert stores.name == "Stores Manager / Executive"
    for code in ("purchasing_officer", "store_supervisor", "qc_inspector"):
        user = person(f"{code}@sml.lk")
        response = as_user(admin).put(
            f"/api/v1/users/{user.pk}/roles/", {"roles": [code]}, format="json"
        )
        assert response.status_code == 200, response.json()
    rights = access.effective_access(User.objects.get(email="store_supervisor@sml.lk"))
    assert rights.has("stores", "enter") and not rights.has("quality", "approve")
    assert not rights.has("vouchers", "view") and not rights.has("payments", "view")
    buyer = access.effective_access(User.objects.get(email="purchasing_officer@sml.lk"))
    assert buyer.has("purchasing", "enter") and not buyer.has("purchasing", "approve")


def test_ordering_receiving_invoicing_and_paying_need_different_people(admin):
    user = person("one@sml.lk")
    url = f"/api/v1/users/{user.pk}/roles/"
    for pair in (
        ["purchasing_officer", "store_supervisor"],
        ["store_supervisor", "clerk"],
        ["store_supervisor", "cashier"],
        ["purchasing_officer", "cashier"],
    ):
        refused = as_user(admin).put(url, {"roles": pair}, format="json")
        assert refused.status_code == 400 and refused.json()["warnings"], pair
    allowed = as_user(admin).put(
        url,
        {"roles": ["purchasing_officer", "store_supervisor"], "reason": "Covering a holiday"},
        format="json",
    )
    assert allowed.status_code == 200


def test_the_stores_person_can_never_also_be_the_qc_inspector(admin):
    """QC acceptance is the check on SML's single stores person (owner, 31 Oct 2026)."""
    user = person("one@sml.lk")
    refused = as_user(admin).put(
        f"/api/v1/users/{user.pk}/roles/",
        {"roles": ["store_supervisor", "qc_inspector"], "reason": "Small team"},
        format="json",
    )
    assert refused.status_code == 400
    assert "cannot be held by one person" in refused.json()["detail"]
    assert not user.role_assignments.exists()


def test_removing_a_role_removes_its_access(admin):
    user = person("c@sml.lk", "clerk")
    as_user(admin).put(f"/api/v1/users/{user.pk}/roles/", {"roles": ["auditor"]}, format="json")
    rights = access.effective_access(User.objects.get(pk=user.pk))
    assert not rights.has("vouchers", "enter")
    assert rights.has("vouchers", "view")


# --- Custom roles -----------------------------------------------------------------------


def test_admin_creates_a_custom_role_by_ticking_permissions(admin):
    response = as_user(admin).post(
        "/api/v1/roles/",
        {
            "code": "store-viewer",
            "name": "Store viewer",
            "permissions": [{"area": "stores", "level": "view"}],
            "actions": [],
        },
        format="json",
    )
    assert response.status_code == 201
    user = person("v@sml.lk", "store-viewer")
    assert access.effective_access(user).has("stores", "view")
    assert not access.effective_access(user).has("vouchers", "view")


def test_unknown_areas_and_actions_are_refused(admin):
    bad_area = as_user(admin).post(
        "/api/v1/roles/",
        {"code": "x", "name": "X", "permissions": [{"area": "moon", "level": "view"}]},
        format="json",
    )
    bad_action = as_user(admin).post(
        "/api/v1/roles/",
        {"code": "y", "name": "Y", "permissions": [], "actions": ["launch"]},
        format="json",
    )
    assert bad_area.status_code == bad_action.status_code == 400
    assert not Role.objects.filter(code__in=["x", "y"]).exists()


def test_standard_roles_cannot_be_edited(admin):
    response = as_user(admin).put(
        "/api/v1/roles/clerk/",
        {"name": "Accounts Clerk", "permissions": [{"area": "payments", "level": "enter"}]},
        format="json",
    )
    assert response.status_code == 403
    clerk = person("clerk@sml.lk", "clerk")
    assert not access.effective_access(clerk).has("payments", "enter")
