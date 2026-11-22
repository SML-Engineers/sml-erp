"""Clear statuses (owner, 16 Nov 2026): lists and document pages say who a document waits for
and who last acted on it ("Waiting for Ruwan (Director)", "Returned by Kumari"), from the
approval engine. A person is named only when exactly one person other than the maker can act
at that level; otherwise the role alone is given."""

import pytest

from apps.core import approvals
from apps.vouchers import services

from .test_access import as_user, person
from .test_director_approval import (  # noqa: F401
    accountant,
    at_director,
    clerk,
    director,
    memory_storage,  # noqa: F401
)
from .test_quotation_approval import draft as quotation_draft
from .test_quotation_approval import executive, manager, unilever  # noqa: F401
from .test_vouchers import LineInput, attach, draft, payee

pytestmark = pytest.mark.django_db


def test_a_voucher_says_who_it_waits_for_and_who_acted(clerk, accountant, director):  # noqa: F811
    voucher = draft(clerk, payee(code="S0009"), LineInput(amount="500.00", invoice_no="I-9"))
    assert approvals.people_for(services.DOC, [voucher.pk]) == {}  # a draft has no approval

    attach(clerk, voucher, content=b"%PDF-1.7 S0009")
    services.submit(clerk, voucher)
    waiting = approvals.people_for(services.DOC, [voucher.pk])[voucher.pk]
    assert waiting == {
        "waiting": {"person": accountant.full_name, "role": "Accountant"},
        "last": None,
    }

    # With a second accountant, only the role can be named.
    person("accountant2@sml.lk", "accountant", all_divisions=True)
    assert approvals.people_for(services.DOC, [voucher.pk])[voucher.pk]["waiting"] == {
        "person": None,
        "role": "Accountant",
    }


def test_the_director_and_a_return_are_named(clerk, accountant, director):  # noqa: F811
    voucher = at_director(clerk, accountant)
    people = approvals.people_for(services.DOC, [voucher.pk])[voucher.pk]
    assert people["waiting"] == {"person": director.full_name, "role": "Director"}
    assert people["last"] == {"action": "approve", "by": accountant.full_name}

    services.send_back(director, voucher, "Wrong invoice attached")
    people = approvals.people_for(services.DOC, [voucher.pk])[voucher.pk]
    assert people == {"waiting": None, "last": {"action": "return", "by": director.full_name}}


def test_the_maker_is_never_the_one_named(clerk, accountant):  # noqa: F811
    # The only Accountant made the voucher: they cannot approve it, so the role is given.
    both = person("both@sml.lk", "clerk", "accountant", all_divisions=True)
    voucher = draft(both, payee(code="S0010"), LineInput(amount="500.00", invoice_no="I-10"))
    attach(both, voucher, content=b"%PDF-1.7 S0010")
    services.submit(both, voucher)
    # The other Accountant leaves afterwards (T51 refuses it at submit if none is left).
    accountant.is_active = False
    accountant.save()
    waiting = approvals.people_for(services.DOC, [voucher.pk])[voucher.pk]["waiting"]
    assert waiting == {"person": None, "role": "Accountant"}


def test_lists_and_pages_carry_it(clerk, accountant, director, executive, unilever):  # noqa: F811
    voucher = at_director(clerk, accountant)
    rows = as_user(director).get("/api/v1/vouchers/").json()
    row = next(r for r in rows if r["id"] == voucher.pk)
    assert row["people"]["waiting"]["person"] == director.full_name
    page = as_user(director).get(f"/api/v1/vouchers/{voucher.pk}/").json()
    assert page["people"]["last"] == {"action": "approve", "by": accountant.full_name}

    quotation = quotation_draft(executive, unilever)
    listed = as_user(executive).get("/api/v1/quotations/").json()
    assert next(r for r in listed if r["id"] == quotation.pk)["people"] is None  # a draft
    assert as_user(executive).get(f"/api/v1/quotations/{quotation.pk}/").json()["people"] is None
