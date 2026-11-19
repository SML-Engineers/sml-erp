"""Plain wording for API errors (owner's testing, T1, 10 Nov 2026).

Django's ``get_object_or_404`` says "No PlanEntry matches the given query." when a record has
gone (removed by someone else, or never visible to this user). Users should never see model
names, so that sentence is replaced by a plain one. An accounting rule's message that a page
did not catch is shown as it is (owner, 19 Nov 2026). Every other error passes through
unchanged.
"""

import re

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import exception_handler, set_rollback

GONE = "This record is no longer here. It may have been removed; reload the page."
_RAW = re.compile(r"^No \w+ matches the given query\.$")


def plain_exception_handler(exc, context):
    # An accounting rule's own message, e.g. "SSCL-M has no rate on 2026-11-19. The Admin or
    # the Accountant enters it under Settings → Tax rates.", reaches the page instead of
    # "Something went wrong" when a sales page did not catch it (owner, 19 Nov 2026). Nothing
    # was saved: the request's transaction is rolled back as for any error.
    from apps.accounting.services import AccountingError

    if isinstance(exc, AccountingError):
        set_rollback()
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    response = exception_handler(exc, context)
    if response is not None and response.status_code == NotFound.status_code:
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        if detail is not None and _RAW.match(str(detail)):
            response.data = {"detail": GONE}
    return response
