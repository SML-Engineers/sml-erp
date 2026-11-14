"""The company-wide two-factor switch (owner, 12 Nov 2026): the Admin turns it off while
testing; it must be on before go-live."""

import time

import pytest

from apps.core.models import AuditEvent, Company

from .conftest import enable_two_factor, login
from .test_access import as_user, person

pytestmark = pytest.mark.django_db

URL = "/api/v1/access/sign-in-security/"
PROTECTED = "/api/v1/auth/login-history/"


def test_it_is_on_by_default():
    assert Company.get().two_factor_on is True


def test_while_it_is_off_nobody_is_asked_for_a_code(client, user, make_user):
    totp, _ = enable_two_factor(client, user)
    Company.objects.filter(pk=1).update(two_factor_on=False)

    # Someone who set up an authenticator signs in with the password alone.
    response = login(client)
    assert response.json()["status"] == "ok"
    assert client.get(PROTECTED).status_code == 200

    # Someone who must use it is not held to set it up.
    director = make_user(email="director@sml.lk", two_factor_required=True)
    other = client.__class__()
    held = login(other, email=director.email)
    assert held.json()["user"]["requirements"] == []

    # Back on: the code is asked for again, and the director is held again.
    Company.objects.filter(pk=1).update(two_factor_on=True)
    client.post("/api/v1/auth/logout/")
    assert login(client).json() == {"status": "two_factor_required"}
    verified = client.post(
        "/api/v1/auth/login/verify/", {"code": totp.at(time.time() + 30)}, format="json"
    )
    assert verified.json()["status"] == "ok"
    other = client.__class__()
    assert login(other, email=director.email).json()["user"]["requirements"] == [
        "two_factor_setup_required"
    ]


def test_only_the_admin_switches_it_with_a_reason():
    admin = person("admin2@sml.lk", "system_admin", all_divisions=True)
    director = person("dir2@sml.lk", "director", all_divisions=True)
    assert as_user(director).get(URL).json() == {"two_factor_on": True}
    refused = as_user(director).put(URL, {"two_factor_on": False, "reason": "x"}, format="json")
    assert refused.status_code == 403
    no_reason = as_user(admin).put(URL, {"two_factor_on": False}, format="json")
    assert no_reason.status_code == 400 and "reason" in no_reason.json()["detail"]
    off = as_user(admin).put(
        URL, {"two_factor_on": False, "reason": "Testing on the PC"}, format="json"
    )
    assert off.status_code == 200 and off.json() == {"two_factor_on": False}
    assert Company.get().two_factor_on is False
    assert AuditEvent.objects.filter(event="two_factor_switched_off").exists()
    clerk = person("clerk3@sml.lk", "clerk")
    assert as_user(clerk).get(URL).status_code == 403
