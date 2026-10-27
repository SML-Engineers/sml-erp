# Backlog — Phase 0 + Phase 1 (core foundation and payment vouchers)

Work top to bottom. Each task is one pull request. A task is done when every acceptance
criterion is covered by a passing test (or, for pure UI items, checked on the test server by
the owner). Spec references point to `docs/spec.md`.

Status: `[ ]` to do · `[x]` done

---

## A. Project foundation

- [x] **P0-01 Project skeleton**
  Docker Compose with Django, PostgreSQL, Redis, S3-compatible file storage, Celery worker, React (Vite) dev
  server and Nginx. `make up`, `make test`, `make migrate` commands. `.env.example`.
  - `make up` starts everything; the API health endpoint returns 200; the React app loads.
  - `make test` runs backend and frontend tests (one sample test each) and passes.
  - No secrets committed.

- [ ] **P0-02 Continuous integration**
  GitHub Actions workflow running lint and all tests on every pull request.
  (The workflow itself was added in P0-01; remaining: commit exact dependency locks per
  `docs/decisions/0001-dependency-pinning.md`, and protect `main` so it can only change
  through a pull request whose checks pass.)
  - A failing test makes the pull request check fail.
  - `main` cannot be pushed to directly, or merged with failing checks.

- [ ] **P0-03 Login and user accounts**
  Email + password login (Argon2 hashing), logout, session timeout, password change,
  login history. Two-factor authentication (TOTP) for users with Accountant, Director,
  Cashier or Admin roles.
  - Users with those roles cannot reach any page until 2FA is set up.
  - Failed logins are recorded; 5 failures in 15 minutes locks the account for 15 minutes.

- [ ] **P0-04 Roles and permissions** (spec 1.1, 3)
  Standard roles from spec 1.1 loaded at setup (Phase 1 roles active: System Administrator,
  Director, Accountant, Accounts Clerk, Cashier, Auditor). Admin can create custom roles by
  ticking permissions. A user can hold several roles. Permission checks on every API endpoint,
  following the Phase 1 permission table in spec 1.1.
  - Assigning a conflicting combination (Clerk + Cashier, Accountant + Cashier, Admin + any
    finance role) shows a warning and records the reason in the audit log.
  - An endpoint called without the required permission returns 403.
  - Auditor can read everything and change nothing.

- [ ] **P0-05 Audit log** (spec 3)
  Insert-only log of create/update/delete on audited models: user, time, IP, old and new values.
  - Updating or deleting an audit row fails at database level.
  - Changing a supplier's bank account writes one audit row with old and new value.

- [ ] **P0-06 Application layout**
  Sidebar navigation, top bar with notification bell and user menu, responsive layout
  (works on a phone), shared table component with search, sort, paging and column totals.

## B. Master data and admin settings

- [ ] **P0-07 Company and divisions** (spec 3, 3.1)
  Company profile (name, registration, VAT no., base currency LKR, financial year start).
  Division master maintained by the Admin: two-character code (PP), name, type (Production or
  Shared), default bank account, active. Seed: WS Workshop, IM Plastic Injection Moulding,
  HO Head Office (shared costs); codes confirmed by the owner before go-live.
  - A division's code cannot change once it has been used on any document.
  - A division with transactions cannot be deleted, only deactivated.
  - A new division appears in every division picker and filter without code changes.

- [ ] **P0-08 Number series** (spec 3)
  Number formats built from tokens, set by the Admin per document type: code (PP), year
  (YY / YYYY), month (MM), day (DD), running number (XXX / NNNN) with a reset period
  (daily, monthly, yearly or never). Allocated inside the saving transaction.
  - Voucher format PPYYMMDDXXX, PP = the voucher's division code: the third IM voucher on
    2026-10-23 is IM261023003.
  - The running number restarts at 001 each day, separately for each division.
  - 50 concurrent saves produce 50 unique, consecutive numbers.
  - A number is never reused, including after its document is deleted.
  - Creating a 1,000th document with a 3-digit running number on one day is refused with a
    clear message (the Admin can widen the running number).

- [ ] **P0-09 Divisions, sections and machines page** (spec 3A.1)
  Tree view Division → Section → Machine with add/edit forms, Excel import and export
  (divisions themselves come from P0-07).
  Moulding machine extra fields. Seed: Workshop division with the 18 sections from spec 3A.1,
  Moulding division. No machines are seeded: the Admin adds all of them from this page.
  - A section or machine used on a transaction cannot be deleted, only deactivated.
  - Codes cannot change once used.

- [ ] **P0-10 Shifts and rosters page** (spec 3A.2)
  Tabs: Shifts, Roster patterns, Crews, Roster calendar with 4-week preview and the warnings
  listed in the spec. Seed: General shift 08:00–17:00.
  - A night shift is attributed to the date it started.

- [ ] **P0-11 Currencies and exchange rates page** (spec 3A.4)
  Pre-loaded currencies (USD, EUR, GBP, AUD, JPY, CNY, INR, SGD, AED); daily rate entry and CSV import.
  - When no rate exists for a date, the latest earlier rate is returned and flagged.

- [ ] **P0-12 Quotation approval limits page** (spec 3A.3)
  Minimum margin % and value limit per division, effective-dated. A change entered by the
  Admin takes effect only after Director confirmation.
  (Used in Phase 1.5; built now because it is an admin setting.)

- [ ] **P0-13 Suppliers and payees** (spec 4.1)
  Supplier master: code, name, payee category (Supplier, Utility, Bank or credit card,
  Government, Employee, Other), address, contacts, VAT no., bank details, payment terms,
  currency, active. Bank detail changes are audited and shown to the Accountant on the next voucher.
  - Duplicate VAT number warns before saving.

- [ ] **P0-14 Bank and cash accounts**
  Company bank accounts and cash/petty cash accounts linked to ledger accounts; cheque books
  with number ranges.

## C. Accounting core

- [ ] **P0-15 Chart of accounts, QuickBooks style** (spec 3)
  Accountant adds, edits, merges and deactivates accounts from the Chart of Accounts page.
  QuickBooks account types and editable detail types, sub-accounts to any depth, optional
  account numbers, default tax code and division, system accounts that cannot be removed,
  Excel import and export. Starter chart for a manufacturing company loaded at setup.
  - An account with transactions cannot be deleted, only made inactive.
  - Merging two accounts moves all history to the remaining account; totals are unchanged.
  - An account's type cannot be changed once it has transactions in a closed period.
  - A sub-account must have the same report section as its parent (e.g. no expense
    sub-account under a bank account).

- [ ] **P0-16 Journal and periods** (spec 3)
  `journal_entry` / `journal_line`, posting service, reversal service, accounting periods
  with close/reopen (Director only).
  - An unbalanced entry is refused (service and database).
  - Updating or deleting a posted entry fails at database level.
  - Posting into a closed period is refused.
  - Reversal creates a mirror entry linked to the original.
  - A line on an income or expense account without a division is refused (spec 3.1).
  - Profit and loss by division for a date range equals the company total when summed.

- [ ] **P0-17 Approval engine** (spec 3)
  Generic engine: approval matrix per document type (levels, roles, conditions), approval log
  (insert-only), actions Submit / Approve / Return / Reject, segregation of duties.
  - Creator cannot approve their own document.
  - The same user cannot approve at two levels.
  - Return and Reject without a reason are refused.

- [ ] **P0-18 Notifications**
  In-app bell and email for: voucher awaiting my approval, voucher returned to me,
  voucher approved/rejected. Per-user on/off settings.

## D. Payment vouchers (Phase 1)

- [ ] **P1-01 Voucher types** (spec 4.1)
  Seed: Cheque Payment, Online Payment, Petty Cash, Internal Transfer, Supplier Advance,
  Staff Reimbursement. Admin can add types. The type is a field and a list filter; it is not
  part of the voucher number.

- [ ] **P1-02 Voucher entry — Clerk** (spec 4.4, 4.5)
  Create voucher with division, type, supplier (with outstanding balance), lines, multiple scanned
  attachments (PDF/JPG/PNG, drag-and-drop and phone camera), save draft, submit.
  The number (PPYYMMDDXXX, P0-08) is given on first save, using the voucher's division code.
  - Same supplier + invoice number already on another voucher shows a warning.
  - An uploaded file identical (SHA-256) to an existing attachment shows a warning.
  - Files larger than 20 MB or of other types are refused.

- [ ] **P1-03 Accountant review** (spec 4.4)
  Queue of submitted vouchers; invoice preview beside details; set GL account, division,
  tax per line (and optional job/production order field, unused until Phase 3);
  approve / return / reject.
  - A voucher cannot be approved at L2 while any line lacks an account or division.
  - A line can be split across divisions by amount or %; the split must add up to the line total.

- [ ] **P1-04 Director approval page** (spec 4.4; replaces the current page)
  Type tabs with pending counts; table with Approve and Reject columns, reason box, bulk
  Approve all / Reject all / Clear all, Confirm and Reset; side panel with invoice preview,
  lines, Accountant's comment, supplier balance and aging; filters and totals; phone layout.
  - Confirm with any Reject lacking a reason is refused and the row is highlighted.
  - Bulk approval shows the count and total amount before confirming.

- [ ] **P1-04b Row actions: Resources, Print, Edit, Delete** (spec 4.4, as in the current system)
  Actions menu (⋯) on every voucher row, plus a paperclip icon when attachments exist.
  Resources opens an attachment viewer (page, zoom, rotate, download). Print produces the
  company-format payment voucher PDF (A4 default, A5 option) with prepared / checked /
  approved names, dates and times from the approval log, and the total in words.
  - Actions a user may not take are hidden AND refused by the API.
  - Edit: Clerk only on Draft/Returned; Accountant only at L2; Director only at L3. A Director
    change to payee, amount or lines returns the voucher to the Accountant with the change shown.
  - After Director approval, Edit is replaced by Amend.
  - Delete: a never-submitted Draft by its creator or the Admin; a submitted voucher with no
    payment by the Director or the Admin only, with a mandatory reason.
  - A deleted voucher is a soft delete: status Deleted, hidden from working lists, listed with
    its full history in a Deleted Vouchers report, number never reused.
  - Deleting a voucher with any payment is refused at service and database level.
  - Reprints are watermarked "Copy"; every edit, delete and print is in the audit log.

- [ ] **P1-05 Returns and amendments** (spec 4.2)
  Returned vouchers go back to the Clerk; resubmission restarts at L2. Amending an approved,
  unpaid voucher creates a new revision that goes through L2 and L3 again; Amendments List.
  - An approved voucher cannot be edited directly.

- [ ] **P1-06 Cancellation** (spec 4.2)
  Accountant requests cancellation of an unpaid voucher; Director approves.
  - A voucher with any payment cannot be cancelled.

- [ ] **P1-07 Supplier payments and the payment lock** (spec 4.6)
  Cashier screen listing Director-approved unpaid vouchers; payment created from a voucher
  only; bank account, method, cheque/transfer reference, date; partial payments; posts the
  journal entry; prints the payment voucher. PostgreSQL trigger as in the spec.
  - Payment for a voucher in any status other than Director Approved / Partly Paid is refused
    by the service AND by the database trigger (test both, including a raw SQL insert).
  - Total payments can never exceed the approved amount (including concurrent payments).
  - Fully paid voucher becomes Paid and locked.
  - Each payment produces a balanced journal entry (Dr supplier payable/expense, Cr bank).
  - Cheque numbers cannot be reused within a cheque book.

- [ ] **P1-08 Lists and reports** (spec 4.4)
  Voucher List, Approved List, Amendments List; vouchers pending by approver and age;
  payments by period; approval history of any voucher; export to Excel and PDF.

- [ ] **P1-09 Reminders**
  Daily reminder to approvers for vouchers waiting longer than a configurable number of days.

## E. Release

- [ ] **P1-10 Hosting setup** (spec 2)
  Scripts and documentation for the Hostinger Ubuntu VPS: Docker, Nginx, Let's Encrypt,
  firewall (HTTPS + key-only SSH), test and production environments, deployment from GitHub.
  Server credentials are entered by the owner, never committed.

- [ ] **P1-11 Backups**
  Nightly encrypted database and file backups, 30-day retention, copied off the VPS;
  documented restore procedure, tested once on the test server.

- [ ] **P1-12 User acceptance testing and go-live**
  Load real masters (chart of accounts, suppliers, bank accounts, users). Clerk, Accountant,
  Director and Cashier run through real vouchers on the test server; issues fixed; go-live.
