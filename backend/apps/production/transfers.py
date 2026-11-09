"""Mould making and inter-division transfers (backlog P3-15; spec 3.1, 7.3).

When the workshop makes or repairs a mould for the moulding division, the completed job is
transferred **at cost** by the Accountant (accounting, Enter), once per job:

- **Cost** (until order costing, P3-16, records each cost as it happens):
  - material issued to the job, less what came back (P3-11), at its issue cost;
  - supplier bills coded to the job (P3-13): approved or paid voucher lines (not those
    paying a supplier invoice, counted on the invoice) and posted supplier invoice lines of
    items not held in stock (stock items reach the job as material issues);
  - labour and overhead for the job card time in approved shift reports (P3-12): hours ×
    the section's labour rate and the machine's (or section's) overhead rate in force that
    day (P3-05).
- **New company mould:** Dr the moulds' cost account (asset class "Moulds and tooling") in
  the mould's division, Cr Inter-division sales in the workshop; the mould is registered as
  a fixed asset at that cost and linked to the mould, and its depreciation terms go to the
  Director (owner, 8 Nov 2026). A customer's mould is not ours to capitalise.
- **Mould repair:** Dr Inter-division charges in the mould's division, Cr Inter-division
  sales in the workshop. Repairs are left out of the company's total profit and loss (they
  are income and cost of the same amount), so nothing is counted twice.
- The transfer is never changed or deleted (database); a mistake is reversed by journal.
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.accounting import journal
from apps.accounting.models import Account
from apps.accounting.services import AccountingError
from apps.assets import services as assets
from apps.assets.models import AssetClass
from apps.assets.services import AssetError
from apps.core.access import effective_access
from apps.core.audit import audit_context
from apps.core.models import User
from apps.inventory.models import StockIssue, StockIssueLine
from apps.purchasing.models import SupplierInvoice
from apps.vouchers.models import Voucher

from . import rates
from .models import InterDivisionTransfer, JobCardEntry, JobOrder, Mould, ShiftReport

ZERO = Decimal("0")
CENT = Decimal("0.01")
P = JobOrder.Purpose
PAID = (Voucher.Status.DIRECTOR_APPROVED, Voucher.Status.PARTLY_PAID, Voucher.Status.PAID)


class TransferError(Exception):
    pass


def can_post(user: User) -> bool:
    return effective_access(user).has("accounting", "enter")


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


# --- What the job cost ---------------------------------------------------------------------------


def cost(job: JobOrder) -> dict:
    """The job's cost so far, by element, with the lines behind it."""
    material = ZERO
    for row in (
        StockIssueLine.objects.filter(issue__job_link__job=job)
        .values("issue__kind")
        .annotate(v=Sum("value"))
    ):
        material += row["v"] if row["issue__kind"] == StockIssue.Kind.ISSUE else -row["v"]
    bills, lines = ZERO, []
    for line in job.voucher_lines.filter(
        voucher__status__in=PAID, supplier_invoice__isnull=True
    ).select_related("voucher"):
        bills += line.amount
        lines.append(f"{line.voucher.number} line {line.line_no}: {line.amount:,.2f}")
    for line in job.invoice_lines.filter(
        invoice__status=SupplierInvoice.Status.POSTED, item__is_stock=False
    ).select_related("invoice"):
        rate = line.invoice.exchange_rate  # LKR at the invoice date (P16-19)
        amount = _money(line.amount * rate) if rate else line.amount
        bills += amount
        lines.append(f"{line.invoice.number} line {line.line_no}: {amount:,.2f}")
    labour = overhead = ZERO
    hours_total = ZERO
    for e in JobCardEntry.objects.filter(
        job=job, report__status=ShiftReport.Status.APPROVED
    ).select_related("machine__section", "report"):
        hours = Decimal(str((e.ended_at - e.started_at).total_seconds())) / 3600
        hours_total += hours
        section = e.machine.section
        labour += hours * (rates.labour_on(section, e.report.day) or ZERO)
        overhead += hours * rates.overhead_on(section, e.machine, e.report.day)
    out = {
        "material": _money(max(material, ZERO)),
        "bills": _money(bills),
        "labour": _money(labour),
        "overhead": _money(overhead),
        "hours": hours_total.quantize(Decimal("0.01"), ROUND_HALF_UP),
        "bill_lines": lines,
    }
    out["amount"] = out["material"] + out["bills"] + out["labour"] + out["overhead"]
    return out


# --- Posting -------------------------------------------------------------------------------------


def _system(role: str, name: str) -> Account:
    account = Account.objects.filter(system_role=role, is_active=True).first()
    if account is None:
        raise TransferError(f"The chart of accounts has no active {name} account.")
    return account


def why_not(job: JobOrder) -> str | None:
    """Why the job cannot be transferred, or None."""
    if job.purpose not in (P.NEW_MOULD, P.MOULD_REPAIR):
        return "Only mould making and mould repair jobs are transferred."
    if hasattr(job, "transfer"):
        return f"{job.number} is already transferred."
    if job.status not in (JobOrder.Status.COMPLETED, JobOrder.Status.CLOSED):
        return f"{job.number} is transferred when it is completed."
    mould = job.mould
    if mould is None:
        return "Choose the mould on the job first (Moulds: add the new mould to the register)."
    if mould.division_id == job.division_id:
        return f"{mould.code} belongs to the division that made it: nothing to transfer."
    if job.purpose == P.NEW_MOULD:
        if mould.owner != Mould.Owner.COMPANY:
            return f"{mould.code} is a customer's mould: it is not capitalised."
        if mould.asset_id is not None:
            return f"{mould.code} is already in the fixed asset register."
    return None


def post(user: User, job: JobOrder, notes: str = "") -> InterDivisionTransfer:
    if not can_post(user):
        raise TransferError("The Accountant posts inter-division transfers.")
    with audit_context("inter_division_transfer", job.number), transaction.atomic():
        job = JobOrder.objects.select_for_update().get(pk=job.pk)
        reason = why_not(job)
        if reason:
            raise TransferError(reason)
        mould = Mould.objects.select_for_update().get(pk=job.mould_id)
        figures = cost(job)
        amount = figures["amount"]
        if amount <= 0:
            raise TransferError(f"{job.number} has no cost yet to transfer.")
        today = timezone.localdate()
        income = _system("inter_division_income", "Inter-division sales")
        new_mould = job.purpose == P.NEW_MOULD
        if new_mould:
            moulds = AssetClass.objects.filter(code="MOULDS", is_active=True).first()
            if moulds is None or moulds.cost_account is None:
                raise TransferError("The asset class Moulds and tooling has no cost account.")
            target = moulds.cost_account
            kind = InterDivisionTransfer.Kind.NEW_MOULD
        else:
            target = _system("inter_division_charges", "Inter-division charges")
            kind = InterDivisionTransfer.Kind.REPAIR
        text = f"{job.number} {mould.code} {mould.name}"
        try:
            entry = journal.post(
                user,
                entry_date=today,
                narration=f"Inter-division transfer at cost: {text} "
                f"({job.division.code} to {mould.division.code})",
                lines=[
                    journal.Line(
                        account=target, debit=amount, division=mould.division, description=text
                    ),
                    journal.Line(
                        account=income, credit=amount, division=job.division, description=text
                    ),
                ],
                source_type=f"inter_division_{'mould' if new_mould else 'repair'}",
                source_id=job.number,
            )
        except AccountingError as error:
            raise TransferError(str(error)) from None
        asset = None
        if new_mould:
            try:
                asset = assets.register(
                    user,
                    asset_class=moulds,
                    division=mould.division,
                    name=f"{mould.code} {mould.name}"[:200],
                    acquisition_date=today,
                    cost=amount,
                    supplier=f"Own workshop, {job.number}",
                    notes=f"Made by job {job.number}; transferred at cost.",
                )
            except AssetError as error:
                raise TransferError(str(error)) from None
            mould.asset = asset
            mould.save(update_fields=["asset"])
        return InterDivisionTransfer.objects.create(
            job=job,
            kind=kind,
            mould=mould,
            from_division=job.division,
            to_division=mould.division,
            transfer_date=today,
            material=figures["material"],
            bills=figures["bills"],
            labour=figures["labour"],
            overhead=figures["overhead"],
            amount=amount,
            fixed_asset=asset,
            journal_entry=entry,
            notes=" ".join((notes or "").split())[:300],
            created_by=user,
        )


def payload(job: JobOrder, user: User) -> dict | None:
    """What the job page shows: the transfer made, or what it would be."""
    if job.purpose not in (P.NEW_MOULD, P.MOULD_REPAIR):
        return None
    done = getattr(job, "transfer", None)
    if done is not None:
        return {
            "done": True,
            "kind": done.kind,
            "kind_label": done.get_kind_display(),
            "date": done.transfer_date,
            "from": done.from_division.code,
            "to": done.to_division.code,
            "material": str(done.material),
            "bills": str(done.bills),
            "labour": str(done.labour),
            "overhead": str(done.overhead),
            "amount": str(done.amount),
            "journal": done.journal_entry.number,
            "asset": done.fixed_asset.code if done.fixed_asset_id else "",
        }
    figures = cost(job)
    reason = why_not(job)
    return {
        "done": False,
        "kind_label": "New mould capitalised"
        if job.purpose == P.NEW_MOULD
        else "Mould repair charged",
        "from": job.division.code,
        "to": job.mould.division.code if job.mould_id else "",
        "material": str(figures["material"]),
        "bills": str(figures["bills"]),
        "labour": str(figures["labour"]),
        "overhead": str(figures["overhead"]),
        "hours": str(figures["hours"]),
        "amount": str(figures["amount"]),
        "bill_lines": figures["bill_lines"],
        "why_not": reason or "",
        "can_post": can_post(user) and reason is None and figures["amount"] > 0,
    }
