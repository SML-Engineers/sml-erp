"""Controls no role, override or administrator can switch off (spec 1.3, CLAUDE.md rules 5-7).

The approval engine (P0-17) calls these before accepting any approval, whatever access the
user holds.
"""

VOUCHER_APPROVAL_LEVELS = 3  # Clerk -> Accountant -> Director; no voucher skips the Director


def approval_refusal(user, *, created_by_id, earlier_approver_ids) -> str | None:
    """Why this user may not approve this document, or None if nothing prevents it."""
    if user.pk == created_by_id:
        return "You cannot approve a document you created."
    if user.pk in set(earlier_approver_ids):
        return "You have already approved this document at another level."
    return None


def voucher_levels_required(voucher=None) -> int:
    """Every voucher, of every type and amount, needs all three levels (rule 6)."""
    return VOUCHER_APPROVAL_LEVELS
