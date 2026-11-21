"""One computer and one phone signed in at a time (owner, 21 Nov 2026)."""

import pytest
from rest_framework.test import APIClient

from apps.core.auth_services import COMPUTER, PHONE, device_kind
from apps.core.models import LoginEvent

from .conftest import login

pytestmark = pytest.mark.django_db

ME = "/api/v1/auth/me/"
PROTECTED = "/api/v1/auth/login-history/"

WINDOWS = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0"
MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 Version/18.0"
ANDROID = "Mozilla/5.0 (Linux; Android 14; SM-A546E) AppleWebKit/537.36 Chrome/131.0 Mobile"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
ANDROID_TABLET = "Mozilla/5.0 (Linux; Android 13; SM-X200) AppleWebKit/537.36 Chrome/131.0"
IPAD = "Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"


def device(agent: str) -> APIClient:
    return APIClient(HTTP_USER_AGENT=agent)


def signed_in(client) -> bool:
    return client.get(ME).json()["authenticated"] is True


@pytest.mark.parametrize(
    ("agent", "kind"),
    [
        (WINDOWS, COMPUTER),
        (MAC, COMPUTER),
        ("", COMPUTER),
        (ANDROID, PHONE),
        (IPHONE, PHONE),
        (ANDROID_TABLET, PHONE),
        (IPAD, PHONE),
    ],
)
def test_the_browser_decides_computer_or_phone(agent, kind):
    assert device_kind(agent) == kind


def test_one_computer_and_one_phone_stay_signed_in_together(user):
    computer, phone = device(WINDOWS), device(ANDROID)
    assert login(computer).json()["status"] == "ok"
    assert login(phone).json()["status"] == "ok"

    assert signed_in(computer)
    assert signed_in(phone)
    assert computer.get(PROTECTED).status_code == 200


def test_a_second_computer_ends_the_first(user):
    first, second = device(WINDOWS), device(MAC)
    login(first)
    login(second)

    assert first.get(PROTECTED).status_code == 403
    me = first.get(ME).json()
    assert me["authenticated"] is False
    assert me["signed_out_reason"] == "computer"
    assert signed_in(second)
    event = LoginEvent.objects.filter(user=user, outcome="replaced_computer").get()
    assert event.user_agent == WINDOWS
    assert event.get_outcome_display() == "Signed out: signed in on another computer"


def test_a_second_phone_ends_the_first_but_not_the_computer(user):
    computer, first_phone, second_phone = device(WINDOWS), device(IPHONE), device(ANDROID)
    login(computer)
    login(first_phone)
    login(second_phone)

    me = first_phone.get(ME).json()
    assert me["authenticated"] is False
    assert me["signed_out_reason"] == "phone"
    assert signed_in(second_phone)
    assert signed_in(computer)
    assert LoginEvent.objects.filter(user=user, outcome="replaced_phone").count() == 1
    assert not LoginEvent.objects.filter(outcome="replaced_computer").exists()


def test_the_ended_device_can_sign_in_again_and_then_ends_the_other(user):
    first, second = device(WINDOWS), device(MAC)
    login(first)
    login(second)
    assert not signed_in(first)

    assert login(first).json()["status"] == "ok"
    me = first.get(ME).json()
    assert me["authenticated"] is True
    assert signed_in(first)
    second_me = second.get(ME).json()
    assert second_me["authenticated"] is False
    assert second_me["signed_out_reason"] == "computer"


def test_other_users_are_not_affected(user, make_user):
    make_user(email="accountant@sml.lk")
    mine, theirs = device(WINDOWS), device(MAC)
    login(mine)
    login(theirs, email="accountant@sml.lk")

    assert signed_in(mine)
    assert signed_in(theirs)


def test_a_wrong_password_on_another_computer_ends_nothing(user):
    mine, other = device(WINDOWS), device(MAC)
    login(mine)
    assert login(other, password="not-it-at-all").status_code == 400

    assert signed_in(mine)


def test_signing_out_normally_gives_no_reason(user):
    computer = device(WINDOWS)
    login(computer)
    computer.post("/api/v1/auth/logout/")

    me = computer.get(ME).json()
    assert me["authenticated"] is False
    assert me["signed_out_reason"] is None
