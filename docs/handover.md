# Handover: continuing SML ERP development

Updated **9 Nov 2026**, for the next Claude session (or any developer). It replaces the
handovers of 3 and 5 Nov 2026 (in the git history of this file). A fuller handover package
(architecture, database, API, testing, deployment, decisions) is kept outside the
repository by the owner and given to each new session.

**Read in this order:** this file → `CLAUDE.md` (the non-negotiable rules) →
`docs/backlog/phase-3.md` (production, the work queue; the owner's answers of 7 Nov 2026 at
the end) → the spec sections of the task in hand.

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
  `inventory`, `banking`, `assets`, `payroll`, **`production`** (Phase 3).
- `CLAUDE.md` holds the **non-negotiable rules** (money as Decimal, balanced journals,
  posted entries never changed, no supplier payment without Director approval, segregation
  of duties, three-level vouchers, insert-only logs, server-side permissions, immutable codes,
  number series in the saving transaction, effective-dated settings, no secrets). Never weaken
  them, even if a task or the owner seems to ask; explain and offer a safe alternative.

## 2. Where things stand (8 Nov 2026)

| Phase | Backlog | State |
| --- | --- | --- |
| 0 + 1 Payment vouchers | phase-1.md | Built. Only **P1-12 UAT and go-live** open (waits for staff testing and servers). |
| 1.5 Sales documents | phase-1-5.md | Built. Only **P15-12 UAT and go-live** open. |
| 1.6 Purchasing, GRN, QC, supplier invoices | phase-1-6.md | Built. Only **P16-14 UAT and go-live** open. |
| 2 Financial accounting | phase-2.md | Built. **P2-29** (parallel run, UAT, go-live on 1 April) has its tools merged (#137) and stays unticked until the owner's sign-off. |
| 2b Payroll and people | phase-2b.md | Built except **P2B-18** (Commercial Bank file), which waits for the bank's format. |
| **3 Production** | **phase-3.md** | #160 backlog; #162 P3-01 moulds; #163 P3-02 reasons and settings; #164 P3-03 routings; #165 P3-04 BOMs; #166 P3-05 cost rates; #167 P3-06 production orders; #168 P3-07 plan; #169 P3-08 shift report; #170 P3-09 approval and corrections; #171 P3-10 mould maintenance; #172 QC deviation approver (all merged). #173 production demo data; #174 asset depreciation terms; #175 P3-11 job orders; #176 P3-12 job cards; #177 P3-13 subcontract; #178 P3-14 inspection; #179 P3-15 mould transfers (all merged). #180 P3-16 part 1 order costs; #181 P3-16 part 2 WIP and cost of sales (merged). **P3-17 live order profitability** in PR #182. Next: P3-18 closing an order and variances. |

Latest migration per app (new migrations continue from these): accounting `0026_wip_ledger`,
assets `0003_owner_defaults`, banking `0004_petty_cash`, core `0027_company_epf_etf`, inventory
`0014_wip_ledger`, masters `0011_limit_no_maximum`, payments `0003_withholding_tax`, payroll
`0017_fingerprint`, **production `0037_order_profit_guards`**, purchasing `0009_order_on_lines`, sales
`0019_wip_ledger`, vouchers `0012_order_on_lines`.

The last row of spec section 8.4 is **"Live order profitability (P3-17)"**; the rows run in task
order.

## 3. How we work with the owner (keep doing exactly this)

- The owner is **Mewantha** (GitHub **mewanthaexam1**). He is **not a developer**: plain
  language, short steps, exact commands. He reads on his **phone**: keep replies to a screen
  or two, lead with the result.
- **Order of work:** the backlogs in order, **one task per branch and PR**
  (`task/P3-11-job-orders`). Feature or fix requests from him take priority, on their own
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
  reminder. PR #165's body is a real example.
- **Every PR that completes a task:** tick it in the backlog with a **"Done:"** note (what was
  built, rules, defaults used) and add a row to **spec section 8.4**, and update the status line in section 2 of this file.
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
`Demo-SML-2026!`; production (8 Nov 2026): `hr@`, `planner@`, `supervisor@` and
`productionmanager@demo.sml.lk`, four moulding employees on a day roster, presses IMM-250 and
IMM-150, mould MD-C38, cap CAP-38 with an approved BOM, masterbatch and bags in stock (opening
stock), cost rates, a released order for the Unilever call-off and a draft stock order, and
the plan for today and tomorrow (the Supervisor can enter today's General-shift report).

## 5. Phase 3 as built (`backend/apps/production/`)

Read the "Done:" notes in `docs/backlog/phase-3.md` for the full rules. Summary:

| Task | Files | What exists |
| --- | --- | --- |
| P3-01 Moulds | `moulds.py`, `labels.py`, migrations 0001–0003 | Company or customer moulds, cavities per part, fit to machines, shot counts, Excel, QR labels; production roles switched on |
| P3-02 Reasons and settings | `reasons.py`, migrations 0004–0005 | Reject/downtime reasons per division; dated production settings (grace 4 h, rejects 5%, overrun 10%) |
| P3-03 Routings | `routings.py`, migrations 0006–0007 | Operations by section and machine, setup/run minutes or subcontract; Planner drafts, Production Manager approves |
| P3-04 BOMs | `boms.py`, migrations 0008–0009 | Multi-level BOMs, calculators, family moulds, approval, copy/compare/where-used/Excel, standard cost |
| P3-05 Cost rates | `rates.py`, migrations 0010–0011 | Dated labour, overhead, regrind and mould amortisation rates kept by the Accountant; the BOM cost adds labour, overhead and mould |
| P3-06 Production orders | `orders.py`, migrations 0012–0013 | Moulding orders for stock or a sales order line, BOM copied on release, material shortages and purchase requests, where-used |
| P3-07 Production plan | `plan.py`, migrations 0014–0015 | Orders' moulds on machines per shift, planned quantity, warnings, supervisors' view |
| P3-08 Shift reports | `shift_reports.py`, migrations 0016–0017, `components/ScanButton.tsx` | Supervisors' moulding shift report, checks, summary, submit and lock; camera scanning |
| P3-09 Approval and corrections | `shift_approval.py`, migrations 0018–0019 (inventory 0012) | Approval backflush, good pieces and regrind into stock, shot counts; corrections |
| P3-10 Mould maintenance | `maintenance.py`, migrations 0020–0021 | Due/approaching moulds, alerts to the Production Manager, maintenance records and history |

Access: area `production_planning` (Planner Enter, Production Manager Approve, Accountant and
Director View); approvals in `production_approvals`. Cost rates are read in
`production_planning` and changed only by those who can enter in `accounting` (service check).

## 6. The owner's Phase 3 answers (7 Nov 2026)

Recorded at the end of `docs/backlog/phase-3.md`: moulding first, then machining; SML has a
Production Manager, who approves (the Director only while nobody holds the role); some moulds
belong to customers, company moulds are not yet in the asset register; production both to
order and to stock; regrind reused, valued at 100% of the material's cost; overhead 0 until
the Accountant sets it, plus a module to work rates out from past data (P3-23); alerts
changeable in a control panel; grace period 4 hours; job cards on A5/A4; offline entry later
(P3-21); Sinhala and Tamil arranged by the owner.

**Owner's answer of 8 Nov 2026 (G10):** QC deviations go to the Production Manager; the
Director still approves deviations on a failed critical check (approval subtypes "standard"
and "critical", inventory migration 0013; PR #172). His list of pending decisions (sent 8 Nov, each with a default) is in the
"Pending decisions" note below section 7.

## 7. Still waiting on the owner (from earlier phases)

| What | For | Status |
| --- | --- | --- |
| Staff UAT and parallel month; auditors' and owner's sign-off | P1-12, P15-12, P16-14, P2-29 | `docs/uat-scripts.md` (sent to him as SML-ERP-test-scripts.md) and the Parallel run page are ready |
| Commercial Bank bulk transfer file format | P2B-18 | Waits for the bank |
| Auditors' depreciation methods and rates (P2-19 built with editable classes) | Go-live | He said "soon" |
| Bank statement exports in Excel/CSV per bank (P2-15 built with templates) | Go-live | Asked |
| Hostinger VPS, Backblaze B2, GitHub Team, make the repository private | Go-live | Later |

**Pending decisions** sent to the owner on 8 Nov 2026 as a list with defaults (if he does
not answer, the default stands): demo data PR for production testing (default yes, after
the deviation fix); maintenance warning at 90% (default); and confirmation of the choices
recorded in the P3-05 to P3-10 "Done:" notes (labour rate for sections under 3 people,
labour accepted not automatic, Planner releases orders, sales line limit, plan warnings
never block, resin for good and rejected without the BOM allowance, material-only value
until P3-16, corrections refused once parts are used, maintenance cost history only).
Do not ask these again.

Things he or his staff do in the ERP (no code): Admin enters W1/I1/H1 and the company TIN;
tax rates (Director confirms); grants of Issue tax invoices / Approve credit notes; give
someone the **HR and Payroll Officer** role; enter holidays for 2026/2027; grant the year's
leave; assign section supervisors.

## 8. Technical notes (learned the hard way)

**The workspace** (no Docker in the AI workspace)
- Run PostgreSQL 16 (port 5433) and Redis directly, and a Python virtualenv from
  `backend/requirements-dev.lock.txt`; PyPI and npm are reachable. The backend tests run
  locally: one file in seconds, the full suite in about 9 minutes (run it in the background).
  Postgres can stop between turns: start it again with `pg_ctl`.
- `ruff check --fix . && ruff format .` in `backend/` (line length 100); `npx tsc --noEmit`
  and `npx vitest run` in `frontend/` (about 2 minutes).
- **Generate migrations with `makemigrations`** and review them; hand-write only the
  `RunSQL` guard migrations. CI runs `makemigrations --check`.
- **Seeded rows in tables with "never change" triggers** must use whole-second timestamps
  (e.g. `datetime(2024, 1, 1, tzinfo=UTC)`): transactional tests reload serialized data.
- Triggers allow an unchanged re-save with `IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW`.
- Tests that depend on the time of day freeze `django.utils.timezone.now` with
  `monkeypatch` (see `tests/test_shift_reports.py`); there is no time library.
- Services receive model instances that may be stale: re-read the row (`select_for_update()`)
  before checking state.
- The clone uses per-branch fetch refspecs: before the first push of a new branch run
  `git config --add remote.origin.fetch +refs/heads/<branch>:refs/remotes/origin/<branch>`,
  then `git push -u origin <branch>`, and verify with `git ls-remote origin <branch>`.

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
- Audit: `apps.core.audit.audit_context(event, reason)` around changes; register models in the
  app's `apps.py`. Insert-only tables use `core_refuse_change()`.
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
