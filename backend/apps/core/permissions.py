from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .access import has_access
from .auth_services import PASSWORD_CHANGE_REQUIRED, setup_requirements

_MESSAGES = {
    PASSWORD_CHANGE_REQUIRED: "Change your password before continuing.",
    "two_factor_setup_required": "Set up two-factor sign-in before continuing.",
}


class IsFullyAuthenticated(BasePermission):
    """Signed in, and nothing outstanding (password change, two-factor setup).

    This is the default for every endpoint (settings.REST_FRAMEWORK).
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        pending = setup_requirements(user)
        if pending:
            raise PermissionDenied(detail=_MESSAGES[pending[0]], code=pending[0])
        return True


class AreaAccess(IsFullyAuthenticated):
    """Checks the user's access to the view's area (spec 1.2), on the server, every request.

    A view sets `access_area`, and optionally `access_write_level` (default "manage") for
    methods that change data. Reading needs "view". A view used by two departments may also
    set `access_also_area`: the same level in either area is enough (e.g. delivery notes,
    made by Sales or the stores).
    """

    message = "You do not have access to this part of the system."

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        area = getattr(view, "access_area", None)
        if area is None:
            raise AssertionError(f"{view.__class__.__name__} must declare access_area")
        level = (
            "view"
            if request.method in SAFE_METHODS
            else getattr(view, "access_write_level", "manage")
        )
        if has_access(request.user, area, level):
            return True
        also = getattr(view, "access_also_area", None)
        return bool(also) and has_access(request.user, also, level)


class ReadForAllAreaWrite(AreaAccess):
    """Anyone fully signed in may read; changes need the view's area at its write level.

    For shared reference data with no business figures, such as the company name and logo
    printed on every document.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return IsFullyAuthenticated.has_permission(self, request, view)
        return super().has_permission(request, view)
