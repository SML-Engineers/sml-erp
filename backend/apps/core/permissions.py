from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission

from .auth_services import PASSWORD_CHANGE_REQUIRED, setup_requirements

_MESSAGES = {
    PASSWORD_CHANGE_REQUIRED: "Change your password before continuing.",
    "two_factor_setup_required": "Set up two-factor sign-in before continuing.",
}


class IsFullyAuthenticated(BasePermission):
    """Signed in, and nothing outstanding (password change, two-factor setup).

    This is the default for every endpoint (settings.REST_FRAMEWORK). Role permissions are
    added on top in P0-04.
    """

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        pending = setup_requirements(user)
        if pending:
            raise PermissionDenied(detail=_MESSAGES[pending[0]], code=pending[0])
        return True
