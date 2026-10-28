"""Chart of accounts rules (spec 3, backlog P0-15).

The Accountant (Chart of accounts and journals: Manage) adds, renames, numbers, moves,
merges and deactivates accounts at any time. The rules:

- every account has a type and a detail type of that type; a sub-account has the same type
  as its parent, so it is printed in the same place on the reports (as in QuickBooks);
- names are unique within the same parent; numbers are optional and unique, and fixed once
  the account has been used (rule 9);
- an account that has been used, that the system needs, or that has sub-accounts is never
  deleted; it is made inactive instead;
- a merge never rewrites posted entries (rule 3): the merged account keeps them, is made
  inactive and points at the remaining account, and reports count its history there
  (`roll_up`). Its sub-accounts move to the remaining account.
"""

import re
from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.core.access import effective_access
from apps.core.audit import audit_context, record
from apps.core.models import Division, User
from apps.core.organisation import related_rows

from .catalogue import SECTIONS, TYPE_ORDER, TYPES
from .models import NUMBER_REGEX, Account, DetailType

NUMBER_PATTERN = re.compile(NUMBER_REGEX)


class AccountingError(Exception):
    pass


def _manage(user: User) -> None:
    if not effective_access(user).has("accounting", "manage"):
        raise AccountingError("Only the Accountant can change the chart of accounts.")


def _require_reason(reason: str, doing: str) -> None:
    if not (reason or "").strip():
        raise AccountingError(f"Give a reason for {doing}.")


# --- Reading the chart ------------------------------------------------------------------


def sort_key(account: Account):
    """Accounts are listed by type in report order; numbers, when used, set the order."""
    return (
        TYPE_ORDER[account.account_type],
        account.number == "",
        account.number,
        account.name.lower(),
    )


def chart(include_inactive: bool = False) -> list[tuple[Account, int, str]]:
    """The whole chart as a tree, depth first: (account, depth, full name)."""
    rows = Account.objects.select_related(
        "detail_type", "default_division", "merged_into", "parent"
    )
    if not include_inactive:
        rows = rows.filter(is_active=True)
    children = defaultdict(list)
    ids = set()
    for account in rows:
        ids.add(account.pk)
        children[account.parent_id].append(account)
    result = []

    def walk(parent_id, depth, prefix):
        for account in sorted(children.get(parent_id, []), key=sort_key):
            name = f"{prefix}:{account.name}" if prefix else account.name
            result.append((account, depth, name))
            walk(account.pk, depth + 1, name)

    walk(None, 0, "")
    # An inactive parent's active sub-account (possible only through history) still shows.
    for parent_id in [p for p in children if p is not None and p not in ids]:
        walk(parent_id, 0, "")
    return result


def full_name(account: Account) -> str:
    """Parent:Child:Grandchild, as QuickBooks writes it (also used by the Excel import)."""
    names = []
    seen = set()
    while account is not None and account.pk not in seen:
        seen.add(account.pk)
        names.append(account.name)
        account = account.parent
    return ":".join(reversed(names))


def descendant_ids(account: Account) -> set[int]:
    found, frontier = set(), {account.pk}
    while frontier:
        frontier = (
            set(Account.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)) - found
        )
        found |= frontier
    return found


def is_in_use(account: Account) -> bool:
    """True once a transaction has used the account (journal lines, P0-16, and later)."""
    if account.first_used_at is not None:
        return True
    return any(
        related_rows(rel, account).exists()
        for rel in Account._meta.related_objects
        if rel.get_accessor_name() and not getattr(rel.related_model, "is_structure", False)
    )


@transaction.atomic
def mark_used(account: Account) -> None:
    """Record that a transaction has used the account (called by posting, P0-16).
    Idempotent. From then on its number is fixed and it cannot be deleted."""
    now = timezone.now()
    if Account.objects.filter(pk=account.pk, first_used_at__isnull=True).update(first_used_at=now):
        account.first_used_at = now
        record("update", account, {"first_used_at": [None, now.isoformat()]}, event="first_used")


def surviving(account_id: int) -> int:
    """The account that now holds this account's history (itself unless merged)."""
    seen = set()
    while account_id not in seen:
        seen.add(account_id)
        nxt = Account.objects.filter(pk=account_id).values_list("merged_into_id", flat=True).first()
        if nxt is None:
            return account_id
        account_id = nxt
    return account_id


def roll_up(totals: dict[int, Decimal]) -> dict[int, Decimal]:
    """Move the totals of merged accounts onto the accounts that replaced them. The grand
    total never changes. Reports call this on per-account totals."""
    merged = dict(
        Account.objects.filter(merged_into__isnull=False).values_list("pk", "merged_into_id")
    )
    result: dict[int, Decimal] = defaultdict(Decimal)
    for account_id, amount in totals.items():
        target, hops = account_id, 0
        while target in merged and hops <= len(merged):
            target, hops = merged[target], hops + 1
        result[target] += amount
    return dict(result)


def linked_company_account(account: Account):
    from apps.masters.models import CompanyAccount  # masters links to accounting, not back

    return CompanyAccount.objects.filter(ledger_account=account).first()


# --- Checks -----------------------------------------------------------------------------


def _name(value) -> str:
    name = " ".join((value or "").split())
    if not name:
        raise AccountingError("The account name is required.")
    if len(name) > 100:
        raise AccountingError("The account name can have at most 100 characters.")
    if ":" in name:
        raise AccountingError("The account name cannot contain a colon (:).")
    return name


def _number(value) -> str:
    number = (value or "").strip().upper()
    if number and not NUMBER_PATTERN.match(number):
        raise AccountingError(
            "The account number must be 1 to 20 letters, digits, dots or dashes, for example 6210."
        )
    return number


def _type(value) -> str:
    if value not in TYPES:
        raise AccountingError("Choose the account type.")
    return value


def _check(account: Account, *, new_detail: bool) -> None:
    """Rules that involve the account and its neighbours. Called before every save."""
    if account.detail_type.account_type != account.account_type:
        raise AccountingError(
            f"The detail type {account.detail_type.name} is not a detail type of "
            f"{TYPES[account.account_type][0]}."
        )
    if new_detail and not account.detail_type.is_active:
        raise AccountingError(f"The detail type {account.detail_type.name} is inactive.")
    parent = account.parent
    if parent is not None:
        if account.pk and (parent.pk == account.pk or parent.pk in descendant_ids(account)):
            raise AccountingError(
                "An account cannot be a sub-account of itself or its own sub-account."
            )
        if parent.account_type != account.account_type:
            raise AccountingError(
                f"A sub-account must have the same type as its parent: {parent.name} is "
                f"{TYPES[parent.account_type][0]}, so this account must be too."
            )
        if not parent.is_active and account.is_active:
            raise AccountingError(f"The parent account {parent.name} is inactive.")
    clash = Account.objects.filter(name__iexact=account.name, parent=parent).exclude(pk=account.pk)
    if clash.exists():
        where = f"under {parent.name}" if parent else "at the top level"
        raise AccountingError(f"There is already an account called {account.name} {where}.")
    if account.number:
        other = Account.objects.filter(number=account.number).exclude(pk=account.pk).first()
        if other:
            raise AccountingError(f"The number {account.number} is already used by {other.name}.")
    if account.default_division is not None and not account.default_division.is_active:
        raise AccountingError(f"The division {account.default_division.code} is inactive.")
    if len(account.description) > 500:
        raise AccountingError("The description can have at most 500 characters.")


# --- Accounts ---------------------------------------------------------------------------


def create_account(
    user: User,
    *,
    name,
    account_type,
    detail_type: DetailType | None,
    parent: Account | None = None,
    number="",
    description="",
    default_division: Division | None = None,
    reason="",
) -> Account:
    _manage(user)
    if detail_type is None:
        raise AccountingError("Choose the detail type.")
    account = Account(
        name=_name(name),
        number=_number(number),
        account_type=_type(account_type),
        detail_type=detail_type,
        parent=parent,
        description=(description or "").strip(),
        default_division=default_division,
    )
    with audit_context("account_created", reason), transaction.atomic():
        if parent is not None:
            account.parent = Account.objects.select_for_update().get(pk=parent.pk)
            if account.parent.merged_into_id:
                raise AccountingError(f"{parent.name} was merged and cannot have sub-accounts.")
        _check(account, new_detail=True)
        account.save()
        return account


EDITABLE = (
    "name",
    "number",
    "description",
    "default_division",
    "detail_type",
    "account_type",
    "parent",
)


def update_account(user: User, account: Account, values: dict, reason: str = "") -> Account:
    """Change an account. `values` may hold the fields in EDITABLE and is_active."""
    _manage(user)
    with transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        if account.merged_into_id:
            raise AccountingError(
                f"{account.name} was merged into {account.merged_into.name} and cannot change."
            )
        used = is_in_use(account)
        event = "account_changed"
        old_detail = account.detail_type_id
        if "name" in values:
            account.name = _name(values["name"])
        if "number" in values:
            number = _number(values["number"])
            if number != account.number and used and account.number:
                raise AccountingError(
                    f"{account.name} has been used, so its number {account.number} cannot change."
                )
            account.number = number
        if "description" in values:
            account.description = (values["description"] or "").strip()
        if "default_division" in values:
            account.default_division = values["default_division"]
        if "detail_type" in values:
            if values["detail_type"] is None:
                raise AccountingError("Choose the detail type.")
            account.detail_type = values["detail_type"]
        if "parent" in values:
            parent = values["parent"]
            if parent is not None and parent.merged_into_id:
                raise AccountingError(f"{parent.name} was merged and cannot have sub-accounts.")
            account.parent = parent
        if "account_type" in values and values["account_type"] != account.account_type:
            _change_type(account, _type(values["account_type"]))
        if "is_active" in values and bool(values["is_active"]) != account.is_active:
            event = _switch(account, bool(values["is_active"]), reason)
        _check(account, new_detail=account.detail_type_id != old_detail)
        with audit_context(event, reason):
            account.save()
        return account


def _change_type(account: Account, new_type: str) -> None:
    """The type may change (it moves the account to another place on the reports) unless
    the system needs the account, it has sub-accounts, or it is a bank or cash account's
    ledger. Changing the type of an account with entries in a closed period is refused
    once periods exist (P0-16)."""
    if account.system_role:
        raise AccountingError(f"{account.name} is needed by the system and keeps its type.")
    if account.children.exists():
        raise AccountingError(
            f"{account.name} has sub-accounts, which must have the same type. Move them or "
            "change their type first."
        )
    if new_type != "bank" and linked_company_account(account):
        raise AccountingError(
            f"{account.name} is the ledger of a company bank or cash account, so it stays "
            "a Bank account."
        )
    account.account_type = new_type


def _switch(account: Account, active: bool, reason: str) -> str:
    """Make inactive (with all its sub-accounts) or active again. Returns the audit event."""
    if not active:
        _require_reason(reason, "making the account inactive")
        if account.system_role:
            raise AccountingError(f"{account.name} is needed by the system and stays active.")
        below = descendant_ids(account)
        family = Account.objects.filter(pk__in=below | {account.pk})
        system = family.exclude(system_role="").first()
        if system:
            raise AccountingError(
                f"{system.name} is needed by the system; move it out from under "
                f"{account.name} first."
            )
        from apps.masters.models import CompanyAccount

        bank = CompanyAccount.objects.filter(ledger_account__in=family, is_active=True).first()
        if bank:
            raise AccountingError(
                f"The open company account {bank.code} uses this ledger; close it first."
            )
        with audit_context("account_made_inactive", reason):
            for child in Account.objects.filter(pk__in=below, is_active=True):
                child.is_active = False
                child.save()  # one by one, so each change is in the audit log
        account.is_active = False
        return "account_made_inactive"
    if account.parent is not None and not account.parent.is_active:
        raise AccountingError(f"Make the parent account {account.parent.name} active first.")
    account.is_active = True
    return "account_reactivated"


def delete_account(user: User, account: Account, reason: str) -> None:
    """Remove an account set up by mistake. Anything with history is made inactive instead."""
    _manage(user)
    _require_reason(reason, "deleting the account")
    with audit_context("account_deleted", reason), transaction.atomic():
        account = Account.objects.select_for_update().get(pk=account.pk)
        if account.system_role:
            raise AccountingError(f"{account.name} is needed by the system and cannot be deleted.")
        if is_in_use(account) or account.merged_into_id or account.merged_accounts.exists():
            raise AccountingError(
                f"{account.name} has transactions, so it cannot be deleted; "
                "make it inactive instead."
            )
        if account.children.exists():
            raise AccountingError(f"{account.name} has sub-accounts; delete or move them first.")
        if linked_company_account(account):
            raise AccountingError(
                f"{account.name} is the ledger of a company bank or cash account."
            )
        account.delete()


def merge_accounts(user: User, source: Account, target: Account, reason: str) -> Account:
    """Merge `source` into `target`: all its history is then reported under `target`."""
    _manage(user)
    _require_reason(reason, "merging the accounts")
    with transaction.atomic():
        source, target = (
            Account.objects.select_for_update().get(pk=source.pk),
            Account.objects.select_for_update().get(pk=target.pk),
        )
        if source.pk == target.pk:
            raise AccountingError("Choose two different accounts to merge.")
        if source.system_role:
            raise AccountingError(
                f"{source.name} is needed by the system; merge the other account into it instead."
            )
        if source.merged_into_id or target.merged_into_id:
            raise AccountingError("An account that was already merged cannot be merged again.")
        if not target.is_active:
            raise AccountingError(f"{target.name} is inactive; make it active first.")
        if source.account_type != target.account_type:
            raise AccountingError(
                "Only accounts of the same type can be merged: "
                f"{source.name} is {TYPES[source.account_type][0]}, "
                f"{target.name} is {TYPES[target.account_type][0]}."
            )
        if target.pk in descendant_ids(source):
            raise AccountingError(f"{target.name} is a sub-account of {source.name}.")
        _move_children(source, target, reason)
        _move_bank_link(source, target, reason)
        with audit_context("account_merged", reason):
            if is_in_use(source):
                mark_used(target)
            source.is_active = False
            source.merged_into = target
            source.merged_at = timezone.now()
            source.save()
        target.refresh_from_db()
        return target


def _move_children(source: Account, target: Account, reason: str) -> None:
    taken = {n.lower() for n in target.children.values_list("name", flat=True)}
    clashes = [c.name for c in source.children.all() if c.name.lower() in taken]
    if clashes:
        raise AccountingError(
            f"{target.name} already has sub-accounts called {', '.join(clashes)}; "
            "rename or merge those first."
        )
    with audit_context("account_merged", reason):
        for child in source.children.all():
            child.parent = target
            child.save()


def _move_bank_link(source: Account, target: Account, reason: str) -> None:
    bank = linked_company_account(source)
    if bank is None:
        return
    if linked_company_account(target):
        raise AccountingError(
            "Both accounts are ledgers of company bank or cash accounts; they cannot be merged."
        )
    with audit_context("account_merged", reason):
        bank.ledger_account = target
        bank.save()


# --- Detail types -----------------------------------------------------------------------


def _detail_name(value) -> str:
    name = " ".join((value or "").split())
    if not name:
        raise AccountingError("The detail type name is required.")
    if len(name) > 100:
        raise AccountingError("The detail type name can have at most 100 characters.")
    return name


def _detail_clash(account_type: str, name: str, pk=None) -> None:
    clash = DetailType.objects.filter(account_type=account_type, name__iexact=name).exclude(pk=pk)
    if clash.exists():
        raise AccountingError(f"{TYPES[account_type][0]} already has a detail type {name}.")


def create_detail_type(user: User, *, account_type, name, reason="") -> DetailType:
    _manage(user)
    account_type, name = _type(account_type), _detail_name(name)
    with audit_context("detail_type_created", reason), transaction.atomic():
        _detail_clash(account_type, name)
        return DetailType.objects.create(account_type=account_type, name=name)


def update_detail_type(user: User, detail: DetailType, values: dict, reason="") -> DetailType:
    """Rename, or switch off for new accounts (accounts that have it keep it)."""
    _manage(user)
    with audit_context("detail_type_changed", reason), transaction.atomic():
        detail = DetailType.objects.select_for_update().get(pk=detail.pk)
        if "name" in values:
            detail.name = _detail_name(values["name"])
            _detail_clash(detail.account_type, detail.name, detail.pk)
        if "is_active" in values:
            detail.is_active = bool(values["is_active"])
        detail.save()
        return detail


def delete_detail_type(user: User, detail: DetailType, reason="") -> None:
    _manage(user)
    with audit_context("detail_type_deleted", reason), transaction.atomic():
        if detail.accounts.exists():
            raise AccountingError(
                f"Accounts use the detail type {detail.name}; make it inactive instead."
            )
        detail.delete()


def catalogue() -> list[dict]:
    """The account types in report order, with their report section and detail types."""
    details = defaultdict(list)
    for d in DetailType.objects.order_by("name"):
        details[d.account_type].append({"id": d.pk, "name": d.name, "is_active": d.is_active})
    return [
        {
            "code": code,
            "label": label,
            "section": section,
            "section_label": SECTIONS[section],
            "normal_balance": balance,
            "detail_types": details[code],
        }
        for code, (label, section, balance) in TYPES.items()
    ]
