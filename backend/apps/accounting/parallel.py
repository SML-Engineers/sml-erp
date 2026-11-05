"""Parallel run: the ERP against QuickBooks for the same month (backlog P2-29, spec 8.2).

During the parallel month the same transactions are entered in both systems. At its end the
Accountant uploads QuickBooks' trial balance (and, if wanted, its A/R and A/P ageing detail)
as at the month end, in the layouts already read for the migration (P2-28). The page puts the
two side by side and lists every difference to explain:
- every account: QuickBooks' balance against the ERP's at the same date (the bank and cash
  accounts among them);
- debtors per customer, and creditors per supplier.
Nothing is posted or kept: it is a comparison only, run as often as wanted.
"""

from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum

from .models import Account, JournalLine
from .quickbooks import (
    MigrationError,
    _by_name,
    _full_names,
    _party,
    match_account,
    read_payables,
    read_receivables,
    read_trial_balance,
)

ZERO = Decimal("0")


def _m(v: Decimal) -> str:
    return f"{v:.2f}"


def _rows(pairs: dict, label_of) -> list[dict]:
    """{key: (qb, erp)} as rows, the largest difference first."""
    out = []
    for key, (qb, erp) in pairs.items():
        out.append(
            {
                "label": label_of(key),
                "quickbooks": _m(qb),
                "erp": _m(erp),
                "difference": _m(erp - qb),
                "agrees": qb == erp,
            }
        )
    out.sort(key=lambda r: (r["agrees"], -abs(Decimal(r["difference"])), r["label"]))
    return out


def _accounts(tb: dict) -> tuple[list[dict], list[str]]:
    as_at = tb["as_at"]
    full = _full_names()
    every = list(Account.objects.filter(merged_into=None))
    by_name = defaultdict(list)
    for a in every:
        by_name[a.name.lower()].append(a)
    by_number = {a.number.upper(): a for a in every if a.number}
    pairs: dict = {}
    unknown = []
    for label, debit, credit in tb["accounts"]:
        account = match_account(label, full, by_name, by_number)
        if account is None:
            unknown.append(label)
            continue
        qb, erp = pairs.get(account.pk, (ZERO, ZERO))
        pairs[account.pk] = (qb + debit - credit, erp)
    erp = {
        r["account"]: (r["d"] or ZERO) - (r["c"] or ZERO)
        for r in JournalLine.objects.filter(entry__entry_date__lte=as_at)
        .values("account")
        .annotate(d=Sum("debit"), c=Sum("credit"))
    }
    for pk, amount in erp.items():
        if amount or pk in pairs:
            qb, _ = pairs.get(pk, (ZERO, ZERO))
            pairs[pk] = (qb, amount)
    names = {a.pk: f"{a.number} {a.name}".strip() for a in every}
    return _rows(pairs, lambda pk: names.get(pk, str(pk))), unknown


def _parties(kind: str, content: bytes, as_at) -> tuple[list[dict], list[str]]:
    from apps.masters.models import Customer, Supplier

    if kind == "receivables":
        found = read_receivables(content)["customers"]
        index, model, field = _by_name(Customer), Customer, "customer"
        lines = JournalLine.objects.filter(account__account_type="accounts_receivable")
    else:
        found = read_payables(content)["suppliers"]
        index, model, field = _by_name(Supplier), Supplier, "supplier"
        lines = JournalLine.objects.filter(account__account_type="accounts_payable")
    pairs: dict = {}
    unknown = []
    for name, amount in found.items():
        party = _party(name, index)
        if party is None:
            if amount:
                unknown.append(name)
            continue
        qb, _ = pairs.get(party.pk, (ZERO, ZERO))
        pairs[party.pk] = (qb + amount, ZERO)
    sign = 1 if kind == "receivables" else -1
    for r in (
        lines.filter(entry__entry_date__lte=as_at, **{f"{field}__isnull": False})
        .values(field)
        .annotate(d=Sum("debit"), c=Sum("credit"))
    ):
        amount = sign * ((r["d"] or ZERO) - (r["c"] or ZERO))
        if amount or r[field] in pairs:
            qb, _ = pairs.get(r[field], (ZERO, ZERO))
            pairs[r[field]] = (qb, amount)
    names = dict(model.objects.filter(pk__in=pairs).values_list("pk", "name"))
    return _rows(pairs, lambda pk: names.get(pk, str(pk))), unknown


def compare(
    *, trial_balance: bytes, receivables: bytes | None = None, payables: bytes | None = None
) -> dict:
    tb = read_trial_balance(trial_balance)
    if not tb["as_at"]:
        raise MigrationError("The trial balance's date was not found in its title.")
    accounts, unknown_accounts = _accounts(tb)
    result = {
        "as_at": tb["as_at"],
        "accounts": accounts,
        "unknown_accounts": unknown_accounts,
        "customers": None,
        "suppliers": None,
    }
    if receivables is not None:
        rows, unknown = _parties("receivables", receivables, tb["as_at"])
        result["customers"] = {"rows": rows, "unknown": unknown}
    if payables is not None:
        rows, unknown = _parties("payables", payables, tb["as_at"])
        result["suppliers"] = {"rows": rows, "unknown": unknown}

    def count(rows):
        return sum(1 for r in rows if not r["agrees"])

    result["differences"] = {
        "accounts": count(accounts),
        "customers": count(result["customers"]["rows"]) if result["customers"] else None,
        "suppliers": count(result["suppliers"]["rows"]) if result["suppliers"] else None,
    }
    return result
