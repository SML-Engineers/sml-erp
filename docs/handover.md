# Handover: continuing SML ERP development

Written **5 Nov 2026**, for the next Claude session (or any developer). It replaces the
handover of 3 Nov 2026 (in the git history of this file; its sections on earlier phases are
still worth reading there).

**Read in this order:** this file → `CLAUDE.md` (the non-negotiable rules) →
`docs/backlog/phase-2b.md` (with the owner's answers of 5 Nov 2026 under its questions) →
the spec sections of the task in hand.

---

## 1. The project in one page

A web ERP for **SML Engineers** (Sri Lanka, base currency LKR). Three divisions: **WS** metal
machining workshop, **IM** plastic injection moulding, **HO** head office (shared).

- Repository: **github.com/SML-Engineers/sml-erp**. It is **public for now**: the owner made
  it public on 3 Nov 2026 because GitHub Actions minutes ran out on the private plan, and public
  repositories get free CI. **Remind him to make it private again before go-live** (and to buy
  GitHub Team then, decision 0003). Never put business data in it (see section 4).
- Stack: Python 3.12, Django 5.2 LTS, DRF, PostgreSQL 16 (business rules also enforced by
  hand-written triggers in migrations), Celery + Redis, SeaweedFS (S3) for files, React +
  TypeScript + Vite + TanStack Query/Table + React Router, i18n (`frontend/src/i18n/en.json`),
  pytest / Vitest, Docker Compose, Nginx; servers will be a Hostinger VPS (not bought yet).
  Domain **smlerp.com.lk**.
- Apps: `core`, `masters`, `accounting`, `vouchers`, `payments`, `sales`, `purchasing`,
  `inventory`, `banking`, `assets`, **`payroll`** (new, Phase 2b).
- `CLAUDE.md` holds the **non-negotiable rules** (money as Decimal, balanced journals,
  posted entries never changed, no supplier payment without Director approval, segregation
  of duties, three-level vouchers, insert-only logs, server-side permissions, immutable codes,
  number series in the saving transaction, effective-dated settings, no secrets). Never weaken
  them, even if a task or the owner seems to ask; explain and offer a safe alternative.

## 2. Where things stand (5 Nov 2026)

| Phase | Backlog | State |
| --- | --- | --- |
| 0 + 1 Payment vouchers | phase-1.md | Built. Only **P1-12 UAT and go-live** open (waits for staff testing and servers). |
| 1.5 Sales documents | phase-1-5.md | Built. Only **P15-12 UAT and go-live** open. |
| 1.6 Purchasing, GRN, QC, supplier invoices | phase-1-6.md | Built. Only **P16-14 UAT and go-live** open. |
| 2 Financial accounting | phase-2.md | **P2-00 to P2-28 merged.** **P2-29** (parallel run, UAT, go-live on 1 April) has its tools merged (#137: `docs/uat-scripts.md` and the QuickBooks comparison page) but stays **unticked until the owner's sign-off**. |
| **2b Payroll and people** | **phase-2b.md** | **P2B-01 to P2B-05 merged** (#139–#143). The owner's answers of 5 Nov 2026 are recorded (#144, `docs/phase-2b-answers`) with new tasks P2B-15, P2B-16, P2B-17 before P2B-06. #144–#152 merged (P2B-15, answers, P2B-16, P2B-17, P2B-06 payroll, P2B-07 posting, P2B-08 payslips, P2B-09 returns). #153–#155 merged (P2B-10 advances and loans, P2B-11 self-service, P2B-12 phone punch clock). **P2B-20** detail-change requests in PR #156. Next: P2B-13 payroll in the rest of the system; P2B-18 bank file waits for the bank's format; P2B-19 gratuity. |

Pull requests merged in this session: #126 (CI fix after making the repo public), #127 P2-21
revaluation, #128 P2-22 budgets, #129 P2-23 month/year-end close, #130 quotation pictures
(owner feature: up to 3 images ≤ 1 MB, shown to the approver, emailed with the quotation), #131
P2-24 cash flow and financial dashboard, #132 P2-25 cash planner, #133 P2-26 report builder,
#134 P2-27 invoice tracking and OnePay links, #135/#136 P2-28 QuickBooks migration (opening
balances; open invoices and bills), #137 P2-29 tools, #138 Phase 2b backlog, #139 P2B-01
employees, #140 P2B-02 pay structure, #141 P2B-03 holidays and leave, #142 P2B-04 attendance
from Excel, #143 P2B-05 overtime and work rules.

Latest migration per app (new migrations continue from these):
accounting `0021_opening_balances`, assets `0001_initial`, banking `0004_petty_cash`, core
`0026_sentemail_other_attachments`, inventory `0010_issues_adjustments_counts`, masters
`0011_limit_no_maximum`, payments `0003_withholding_tax`, **payroll `0005_overtime`**,
purchasing `0008_opening_bills`, sales `0018_opening_invoices`, vouchers `0011_withholding_tax`.

The last row added to spec section 8.4 is **"Overtime and attendance rules (P2B-05)"**.

## 3. How we work with the owner (keep doing exactly this)

- The owner is **Mewantha** (GitHub **mewanthaexam1**). He is **not a developer**: plain
  language, short steps, exact commands. He reads on his **phone**: keep replies to a screen
  or two, lead with the result.
- **Order of work:** the backlogs in order, **one task per branch and PR**
  (`task/P2B-06-payroll-run`). Feature or fix requests from him take priority, on their own
  branches (`feature/...`, `fix/...`). Docs-only changes on `docs/...`.
- **Never push to `main`, never merge.** Open each PR as a **draft**; wait for the **3 draft
  checks** (Lock files, Backend tests, Frontend tests); mark it ready; wait for **all 5**
  (plus Full stack and Production stack); only then send him the link. He merges and sends a
  **screenshot of the merged PR** — that is the signal to start the next task. If a check
  fails, fix it first and say in one line what went wrong. Never ask him to merge with a red
  or pending check.
- **PR body** (for him, plain language), three sections:
  1. **What changed** — what he will see and what the rules are.
  2. **How it was tested** — the cases the tests cover, in words.
  3. **On your PC after merging** — GitHub Desktop → **Fetch origin** → **Pull origin** →
     **F5** in the browser. When the PR has migrations, also:
     `cd D:\GitHub\sml-erp` and
     `docker compose -f deploy/docker-compose.dev.yml --env-file .env restart backend`.
     When a library or Dockerfile changes, `... up -d --build` instead of `restart backend`.
  The body ends with the attribution line and session link given in **your own** system
  reminder. PR #143's body is a real example.
- **Every PR that completes a task:** tick it in the backlog with a **"Done:"** note (what was
  built, rules, defaults used) and add a row to **spec section 8.4**.
- **Decisions:** tell him when one of his decisions looks wrong for the business or breaks a
  rule, and why. Send **lists of questions as .txt files**. When he does not answer, use the
  default, say so, and record it in the backlog as a default he can change. Record his
  answers in the backlog as "Owner, <date>: …".
- **Never ask questions he has already answered** (check the backlogs and spec 8.4 first —
  this session once re-asked the payment-gateway question and had to apologise).
- **Security, his words: "Never ask me for the email (SMTP) password: I type it into the ERP
  myself."** Keep business data (QuickBooks exports, bank statements, payroll sheets, staff
  lists) **out of the repository**; tests use made-up data.
- Commit messages end with the `Co-Authored-By:` and `Claude-Session:` lines from your system
  reminder.

## 4. The owner's PC (where he tests)

Windows, Docker Desktop, GitHub Desktop; repository at `D:\GitHub\sml-erp` with `.env`; ERP at
**http://localhost:8080**. Demo data: `python manage.py load_demo_data` (runs only missing
parts; refuses on production). Demo users `clerk@`, `accountant@`, `director@`, `cashier@`,
`sales@`, `salesmanager@`, `purchasing@`, `stores@`, `qc@demo.sml.lk`, password
`Demo-SML-2026!`. **There is no demo HR user or demo employees yet** — add them to the demo
data in a small PR when convenient (an HR and Payroll Officer user, a few employees in WS and
IM, a section with a supervisor).

## 5. Phase 2b as built (payroll app, `backend/apps/payroll/`)

Read `docs/backlog/phase-2b.md` "Done:" notes for the full rules. Summary:

| Task | Files | What exists |
| --- | --- | --- |
| P2B-01 Employees | `employees.py`, `views.py` (Employee views), `models.Employee`, migration 0001 | Employee master; NIC (old/new) checked and unique; number immutable; never deleted (trigger); leavers with date and reason; salary bank account with a **second check by the Director** (never the person who changed it); Excel template/export/import (all or nothing); export of everyone needs action `export_personal_data`. The **HR and Payroll Officer** role is switched on. Link to a user kept by the API (UI comes with self-service). |
| P2B-02 Pay structure | `pay.py`, `models.PayComponent/PayRate`, migration 0002 | Components (earning/deduction, EPF/ETF-liable, APIT-taxable, fixed or variable); deductions never EPF/APIT (DB check). Per-employee dated amounts from the 1st of a month, never changed (trigger); 0 ends a component; future amounts withdrawable. Seeded: BASIC, FIXED, ATTEND, TRAVEL, INCENTIVE; WELFARE, UNION, LOAN, ADVANCE. **No budgetary relief allowance**: it ended as a separate payment on 31 March 2025 (Amendment Acts No. 9 and 10 of 2025). |
| P2B-03 Holidays and leave | `leave.py`, `leave_views.py`, `models.Holiday/LeaveType/LeaveGrant/Leave`, migration 0003 | Holidays (past ones kept); leave types with rules `annual_soe` (14/10/7/4 by joining quarter), `casual_soe` (½ day per completed month in joining year, then 7), `fixed`, `unlimited`; "Grant the year's leave"; adjustments with reason; grants insert-only; leave counted Mon–Sat without holidays; half days; no overlaps; never beyond balance; applied-for leave approved by HR, never one's own; cancel, never delete. Seeded: ANNUAL, CASUAL, MATERNITY, NOPAY. |
| P2B-04 Attendance | `attendance.py`, `attendance_views.py`, `models.AttendanceImport/AttendanceDay/AttendanceMonth`, migration 0004 | Excel template (Employee no, Date, Time in, Time out, Shift, Leave code, Remarks); checked first, all or nothing; minutes worked (less shift break), late, early; night shifts past midnight; leave code without times = day of leave, with times = half day. HR confirms a **division's calendar month** after it ends: leave codes become leave (balances checked); confirmed days frozen (trigger); reopen with reason. |
| P2B-05 Overtime | `overtime.py`, `overtime_views.py`, `models.WorkRule/OvertimeCheck`, migration 0005 | Dated **work rules per division** (default 480 min day, 10 min grace, 2 short leaves of 90 min, OT from 30 min in 15-min steps, rates 1.5/2.0/2.0, hourly divisor 240); OT per day; short time = late beyond grace + early, covered by short leave, rest no-pay; no-pay days = absent + unpaid leave. The section supervisor or the Director checks each employee's month (never the attendance confirmer, never oneself); checked figures frozen (trigger) and voided if attendance is reopened. |

Frontend: menu section **"People and payroll"** (`menu.people`): Employees, Pay components,
Attendance, Overtime, Work rules, Leave, Holidays and leave types. Pages in
`frontend/src/pages/` (`EmployeesPage`, `EmployeePage` + `EmployeePay` + `EmployeeLeave`,
`PayComponentsPage`, `AttendancePage`, `OvertimePage`, `WorkRulesPage`, `LeavePage`,
`HolidaysPage`); API clients `src/api/employees.ts`, `pay.ts`, `leave.ts`, `attendance.ts`,
`overtime.ts`. Menu items support `anyLevel: ["enter", "approve"]` (HR or the Director, not the
Accountant's "totals only" view).

Access in payroll: area `hr_payroll`. HR and Payroll Officer = Manage; Director = Approve
(sees everything, checks bank accounts and overtime, enters nothing); Accountant = View
"totals only" (sees no personal data: `employees.can_view` needs Enter or Approve); Production
Supervisor = View "attendance" (checks overtime for the sections they supervise). The System
Admin has **no** payroll access by default.

## 6. The owner's answers of 5 Nov 2026 and the next tasks

He answered all 13 Phase 2b questions after P2B-01 to P2B-05 were built. The answers are
recorded under each question in `docs/backlog/phase-2b.md` ("Owner, 5 Nov 2026: …") and in
spec 8.4. In short:

- **Pay period 21st to 20th**, paid on the last day of the month; advances during the month
  are deducted at month end.
- **Everything per employee, approved by the Director**: overtime settings, attendance bonus
  (default LKR 1,500, lost when absent four half days), up to four allowances, leave, APIT.
- **Leave per labour category**: Shop and Office (annual 14, casual and sick 7, short leave
  2 × 1.5 h paid) and Wages Board (annual 7, casual and sick 7, short leave 2 × 1.5 h unpaid,
  a quarter day's pay deducted each).
- Payroll approved by the Director **and** paid through a three-level voucher; Commercial
  Bank of Ceylon PLC; payslips as the default; loans in equal monthly instalments; gratuity
  "as the government's guidance".

**Next tasks, in this order:** P2B-15 pay period → P2B-16 labour categories and leave →
P2B-17 pay settings approved by the Director → P2B-06 payroll run → P2B-07 to P2B-14.
The backlog has the text of each. Implementation hints:

- **P2B-15:** keep `AttendanceMonth.month` and `OvertimeCheck.month` as the 1st of the pay
  month; add a helper `pay_period(month) -> (start, end)`; the DB trigger in migration 0004
  uses `date_trunc('month', date)` — replace it in a new migration with the period rule
  (date ≥ 21 → next pay month); the cut-off day is a dated company setting (default 21).
  Nothing is live, so no data migration.
- **P2B-16:** `Employee.category`; entitlements and short-leave rules per category; check
  maternity days by web search (Shop and Office Act, Maternity Benefits Ordinance as
  amended), not memory.
- **P2B-17:** a "pay settings change" document through `apps/core/approvals.py`
  (DocumentType + ApprovalRule level 2 Director + reminder; add to
  `tests/test_approval_reminders.py`). Decide how `pay.add_rate` fits (pending rows, or the
  amounts move into the change) and record it. "The Admin" = HR and Payroll Officer (System
  Admin has no payroll access by design).
- **P2B-06:** search the current IRD APIT tables (2026/27); do not use memory.

**Follow-up questions** were sent to him with #144 (as a .txt) and are listed in the backlog
under "Follow-up questions (sent 5 Nov 2026)", with defaults. Record his answers there.

## 7. Still waiting on the owner (from earlier phases)

| What | For | Status |
| --- | --- | --- |
| Staff UAT and parallel month; auditors' and owner's sign-off | P1-12, P15-12, P16-14, P2-29 | `docs/uat-scripts.md` (sent to him as SML-ERP-test-scripts.md) and the Parallel run page are ready |
| Commercial Bank bulk transfer file format | P2B-07 | Follow-up question 10 |
| A masked sample of the payroll Excel | P2B-14 | Asked |
| Auditors' depreciation methods and rates (P2-19 built with editable classes) | Go-live | He said "soon" |
| Bank statement exports in Excel/CSV per bank (P2-15 built with templates) | Go-live | Asked |
| Hostinger VPS, Backblaze B2, GitHub Team, make the repository private | Go-live | Later |

Things he or his staff do in the ERP (no code): Admin enters W1/I1/H1 and the company TIN;
tax rates (Director confirms); grants of Issue tax invoices / Approve credit notes; give
someone the **HR and Payroll Officer** role; enter holidays for 2026/2027; grant the year's
leave; assign section supervisors.

## 8. Technical notes (learned the hard way)

**The workspace**
- **pip to PyPI fails**: no local Django; you cannot run backend tests. **CI is the backend
  test runner.** `ruff` works: `/root/.local/bin/ruff check --fix .` and `ruff format .` in
  `backend/` (line length 100; migrations excluded from ruff's format).
- **npm works now**: `cd frontend && npm ci`, then `npx tsc --noEmit` and
  `npx vitest run [file]` run locally (the full suite takes ~100 s). Run them before pushing.
- **Migrations are written by hand.** CI runs `makemigrations --check`; it fails when the
  migration does not match the model exactly. Lessons: `Q(a=1, b=2)` sorts its keywords, so
  write the same `models.Q(...)` expression in model and migration; keep field options
  identical (`verbose_name`, defaults as `Decimal("1.50")`).
- **Seeded rows in tables with "never change" triggers** must use whole-second timestamps
  (e.g. `datetime(2024, 1, 1, tzinfo=UTC)`): transactional tests reload serialized data with
  millisecond precision and the trigger refuses the "change" (this broke #143 once).
- Triggers allow an unchanged re-save with `IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW`.
- Services receive model instances that may be stale: re-read the row (`visible(user)
  .filter(pk=...).first()` or `select_for_update()`) before checking state (this broke #140
  once).
- Pushes are occasionally silently rejected: verify with `git ls-remote origin <branch>`.

**GitHub through `gh api`** (GraphQL is blocked in this environment):
- Draft PR: `gh api repos/SML-Engineers/sml-erp/pulls -f title=... -f head=<branch> -f base=main -F draft=true -F body=@file --jq .number` (retry on 502).
- Mark ready: `gh api -X POST repos/SML-Engineers/sml-erp/pulls/<n>/ccr/ready_for_review`.
- Checks: `gh api repos/SML-Engineers/sml-erp/commits/<sha>/check-runs --jq '.check_runs[] | "\(.name)|\(.status)|\(.conclusion)"' | sort -u`
  (after marking ready the skipped draft-run entries of Full stack/Production stack remain;
  wait for the new `success` entries).
- Failure logs: run id from `actions/runs?head_sha=<sha>`, job id from `.../runs/<id>/jobs`,
  then `gh api repos/SML-Engineers/sml-erp/actions/jobs/<job>/logs | grep -E "FAILED|E  |Migrations for"`.
- A small script that waits for the draft checks, marks the PR ready and waits for all five
  helps (`watch-checks.sh <PR> <SHA>`, kept outside the repository).
  Foreground commands time out at 10 minutes: loop in chunks of ≤ 9 minutes; the full stack
  takes 10–15 minutes after marking ready.

**Backend patterns**
- Logic in a service module per feature; views thin; domain errors → 400 `{"detail": ...}`.
- Permissions: every view subclasses `AreaAccess` (`access_area`, optional
  `access_write_level`, `access_also_area`); levels view ⊂ enter ⊂ manage; approve ⊃ view only
  (approver endpoints set write level "view" and the service checks the role).
  `tests/test_access.py` checks every endpoint (a `reviewed_without_area` list exists).
  `effective_access(user)` is cached on the user object: reload users after grants in tests.
- Payroll views subclass `_Employees` (`apps/payroll/views.py`): `hr_payroll` area plus
  `employees.can_view` (Enter or Approve). Overtime uses `_Overtime` (view level; the service
  decides). Division scope: `apps.core.access.division_scope(user)`.
- Approval engine `apps/core/approvals.py` (register DocumentType, seed ApprovalRule level 2
  Director + ApprovalReminder in a migration, add the tuple to
  `tests/test_approval_reminders.py`). Nobody approves their own document.
- Audit: `apps.core.audit.audit_context(event, reason)` around changes; register models in
  `apps/payroll/apps.py`. Insert-only tables use `core_refuse_change()`.
- Journal: `apps.accounting.journal.post(...)`; add new posting documents to
  `apps/accounting/sources.py`. Numbers: `apps.core.numbering.allocate(...)` inside the
  transaction.
- Tests: `from .test_access import as_user, person`; payroll tests import helpers from
  `tests/test_employees.py` (`values`), `tests/test_attendance.py` (`row`, `upload`); never
  touch the database at import time.

**Frontend patterns**
- Pages `src/pages`, API `src/api`, routes `src/App.tsx`, menu `src/layout/menu.ts`, wording
  `src/i18n/en.json` (edit with Python json load/dump, `ensure_ascii=False, indent=2`,
  trailing newline; check a new top-level key does not exist yet).
- Tests: `mockApi({"GET /api/v1/x/?a=1": {body}})` — URLs must match exactly (every request
  the page makes, including panels on the same page); function routes when the page
  refetches after an action; `renderAt(path, element, routePath)`.
