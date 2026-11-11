"""Plain wording for API errors (owner's testing, T1, 10 Nov 2026).

Django's ``get_object_or_404`` says "No PlanEntry matches the given query." when a record has
gone (removed by someone else, or never visible to this user). Users should never see model
names, so that sentence is replaced by a plain one. Every other error passes through unchanged.
"""

import re

from rest_framework.exceptions import NotFound
from rest_framework.views import exception_handler

GONE = "This record is no longer here. It may have been removed; reload the page."
_RAW = re.compile(r"^No \w+ matches the given query\.$")


def plain_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None and response.status_code == NotFound.status_code:
        detail = response.data.get("detail") if isinstance(response.data, dict) else None
        if detail is not None and _RAW.match(str(detail)):
            response.data = {"detail": GONE}
    return response
