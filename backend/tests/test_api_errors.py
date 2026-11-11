"""Plain wording for API errors (owner's testing, T1, 10 Nov 2026): a record that has gone is
reported without Django's model name; every other error is unchanged."""

from django.http import Http404
from rest_framework.exceptions import NotFound, ValidationError

from apps.core.exceptions import GONE, plain_exception_handler


def test_the_raw_not_found_sentence_is_replaced():
    response = plain_exception_handler(Http404("No Bom matches the given query."), {})
    assert (response.status_code, response.data) == (404, {"detail": GONE})


def test_other_messages_pass_through_unchanged():
    own = plain_exception_handler(Http404("No logo has been uploaded."), {})
    assert own.data == {"detail": "No logo has been uploaded."}
    plain = plain_exception_handler(NotFound("This run is no longer in the plan."), {})
    assert plain.data == {"detail": "This run is no longer in the plan."}
    refused = plain_exception_handler(ValidationError({"code": ["Give a code."]}), {})
    assert (refused.status_code, refused.data) == (400, {"code": ["Give a code."]})
    assert plain_exception_handler(ValueError("not an API error"), {}) is None
