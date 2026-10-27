from unittest import mock

import pytest
from django.db.utils import OperationalError
from django.urls import reverse
from rest_framework.test import APIClient


@pytest.mark.django_db
def test_health_reports_ok_when_database_is_reachable():
    response = APIClient().get(reverse("health"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["database"] == "ok"


@pytest.mark.django_db
def test_health_reports_503_when_database_is_down():
    with mock.patch(
        "apps.core.views.connection.cursor", side_effect=OperationalError("connection refused")
    ):
        response = APIClient().get(reverse("health"))

    assert response.status_code == 503
    assert response.json() == {
        "status": "degraded",
        "database": "unavailable",
        "version": response.json()["version"],
    }


def test_health_is_served_under_api_v1():
    assert reverse("health") == "/api/v1/health/"
