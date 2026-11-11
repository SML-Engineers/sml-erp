"""The Production Manager's dashboard (owner, 11 Nov 2026): what waits for their decision and
what was made today, taken from the same queues and report as the pages the tiles open."""

import pytest

from apps.production import jobs, shift_approval

from .test_access import as_user, person
from .test_job_orders import (  # noqa: F401
    accountant,
    give,
    manager,
    planner,
    released,
    shaft,
    storeman,
)
from .test_production_orders import cap, for_stock  # noqa: F401
from .test_shift_approval import ready  # noqa: F401
from .test_shift_reports import TODAY, clock, press, supervisor  # noqa: F401

pytestmark = pytest.mark.django_db

URL = "/api/v1/production-reports/dashboard/"


def test_what_waits_for_the_production_manager_and_what_was_made_today(
    ready,  # noqa: F811
    manager,  # noqa: F811
    supervisor,  # noqa: F811
    planner,  # noqa: F811
    storeman,  # noqa: F811
    shaft,  # noqa: F811
):
    body = as_user(manager).get(URL).json()
    assert body["today"] == TODAY.isoformat()
    assert body["waiting"] == {
        "shift_reports": 1,
        "corrections": 0,
        "issue_more": 0,
        "deviations": 0,
        "boms": 0,
        "routings": 0,
    }
    # Nothing counts as made until the report is approved.
    assert body["made_today"]["good"] == "0"

    job = released(planner)
    give(storeman, job, ("EN8-50", "42", ""))
    jobs.ask_more(storeman, job, {"item": "EN8-50", "quantity": "4", "reason": "Two scrapped"})
    shift_approval.decide(manager, ready["report"], "approve")

    body = as_user(manager).get(URL).json()
    assert body["waiting"]["shift_reports"] == 0
    assert body["waiting"]["issue_more"] == 1
    assert body["made_today"]["good"] == "3960"
    assert body["made_today"]["rejected"] == "40"
    # The supervisor who submitted the report has nothing to approve.
    assert as_user(supervisor).get(URL).json()["waiting"]["issue_more"] == 0


def test_only_people_with_production_reports_see_it(manager):  # noqa: F811
    assert as_user(manager).get(URL).status_code == 200
    clerk = person("clerk9@sml.lk", "clerk")
    assert as_user(clerk).get(URL).status_code == 403
