# Handover: continuing SML ERP development

Written **3 Nov 2026** at the end of a long Claude session, for the next Claude session (or any
developer). It replaces the handover of 31 Oct 2026. Read it first, then `CLAUDE.md` (the
non-negotiable rules), then `docs/backlog/phase-2.md` and the spec sections of the task you
are working on.

---

## 1. The project

A web ERP for **SML Engineers** (Sri Lanka, base currency LKR) with three divisions: **WS**
metal machining workshop, **IM** plastic injection moulding, **HO** head office (shared).

- Repository: **github.com/SML-Engineers/sml-erp** (private). Local clone in the Claude
  workspace: `/home/claude/sml-erp`.
- Stack: Python 3.12, Django 5.2, DRF, PostgreSQL 16 (business rules also enforced by
  hand-written triggers in migrations), Celery + Redis (beat schedule in `config/settings.py`),
  SeaweedFS (S3) for files, React + TypeScript + Vite + TanStack Query/Table + React Router,
  i18n (`frontend/src/i18n/en.json`), Docker Compose, Nginx. Servers: Hostinger VPS (not bought
  yet). Domain: **smlerp.com.lk** (test: test.smlerp.com.lk; www redirects to the bare domain).
- Specification: `docs/spec.md`. Backlogs: `docs/backlog/phase-1.md`, `phase-1-5.md`,
  `phase-1-6.md`, `phase-2.md`. Decisions: `docs/decisions/`. Hosting and backups:
  `docs/hosting.md`, `docs/backups.md`.
- **`CLAUDE.md` holds the non-negotiable rules**: money as Decimal (`NUMERIC(18,2)`), balanced
  journals (service + DB), posted entries never changed (reversals only), no supplier payment
  without Director approval (UI + service + DB trigger), segregation of duties, three-level
  vouchers, insert-only audit and approval logs, server-side permissions on every endpoint,
  immutable codes, number series inside the saving transaction, effective-dated settings, no
  secrets in the repo. Never weaken them.

## 2. Where things stand (3 Nov 2026)

| Phase | Backlog | State |
| --- | --- | --- |
| 0 + 1 Payment vouchers | phase-1.md | All built. Only **P1-12 UAT and go-live** open (waits for servers). |
| 1.5 Sales documents | phase-1-5.md | All built. Only **P15-12 UAT and go-live** open. |
| 1.6 Purchasing, GRN, QC, supplier invoices | phase-1-6.md | All built, including section H (P16-15 to P16-20). Only **P16-14 UAT and go-live** open. |
| 2 Financial accounting | phase-2.md | **P2-00 to P2-06 merged.** Next: **P2-07 Customer receipts and allocation**, then P2-08 … P2-29 in order. |

Phase 2 pull requests merged this session: #97 plan, #98 P2-01 manual journals, #105 P2-02
recurring journals, #106 P2-03 trial balance / balance sheet / general ledger / P&L screen,
#107 P2-04 delivery notes, #108 P2-05 tax invoices, #109 P2-06 credit notes. Also merged:
#99–#104 (opening stock, quotation limits, SSCL codes, IAS 2 price differences, IAS 21 exchange
rates, tax rate control panel). **No pull request is open.** `main` is at `799e3de`.

Latest migration per app (new migrations continue from these): accounting `0013_line_customer`,
core `0022_credit_note_action`, inventory `0009_receipt_exchange_rate`, masters
`0011_limit_no_maximum`, payments `0001_initial`, purchasing `0005_invoice_exchange_rate`,
sales `0011_credit_notes`, vouchers `0010_advance_payments`.

## 3. How we work with the owner

- The owner is **Mewantha** (GitHub **mewanthaexam1**, mewantha@smlengineers.com), timezone
  Australia/Brisbane. He is **not a developer**: plain language, short steps, exact commands.
  He reads on his phone.
- **One backlog task per branch and pull request**, branch `task/P2-07-customer-receipts`;
  fixes from his testing on `fix/...` branches (they take priority). Tick the task in the
  backlog in the same PR, with a short "Done:" note of what was built.
- **Never push to `main`, never merge.** Open the PR as a **draft**, wait until all **five**
  checks are green (lock files, backend, frontend, full stack, production stack), mark it
  ready, then send him the link. He merges and sends a **screenshot of the merged PR** as the
  signal to continue. Do not send the link before everything is green; if a check fails, fix
  it and say briefly what went wrong.
- **PR descriptions** are for him: sections **What changed / How it was tested / On your PC
  after merging**. The last section always says: GitHub Desktop → **Fetch origin** → **Pull
  origin** → F5; when the PR has migrations, also
  `cd D:\GitHub\sml-erp` and
  `docker compose -f deploy/docker-compose.dev.yml --env-file .env restart backend`;
  when dependencies or Dockerfiles change, `... up -d --build` instead of `restart backend`.
- He asked to be **told when one of his decisions looks wrong** (and why), and for replies to
  his decision lists as **.txt files**. Ask when something is unclear or seems wrong for the
  business; record every answer in the backlog (and spec 8.4) as "owner, <date>". When he does
  not answer, take the recommended default, say so, and record it as a default he can change.
- **Security:** never ask for or handle the mailbox (SMTP) password: the Admin types it into
  Settings → Email in the ERP. The Commercial Bank statement PDF he sent holds account data:
  keep it out of the repository.
- Attribution: commit messages end with the `Co-Authored-By:` and `Claude-Session:` lines, and PR
  bodies end with the "Generated with Claude Code" line and the session link, **as given in the
  new session's own system reminder**.

## 4. The owner's PC (where he tests)

Windows, Docker Desktop, GitHub Desktop; repository at `D:\GitHub\sml-erp` with `.env`; ERP at
**http://localhost:8080**. Docker needed DNS `8.8.8.8, 1.1.1.1`. Demo data:
`python manage.py load_demo_data` (runs only the missing parts; refuses on production). Demo
users `clerk@`, `accountant@`, `director@`, `cashier@`, `sales@`, `salesmanager@`, `purchasing@`,
`stores@`, `qc@demo.sml.lk`, password `Demo-SML-2026!`, one shared TOTP entry.
Staff will test on his PC at times he allocates; servers are bought only when everything passes.

## 5. The owner's decisions (respect them)

All are recorded in the spec (8.4) and the backlogs. The ones most likely to matter next:

**General and earlier phases**
- Every voucher: Clerk → Accountant → Director, no thresholds. Cashier methods: cheque,
  transfer, cash, card, QR (LankaQR).
- The Director approves every quotation before it is printed or sent; quotation limits are
  warnings (Admin sets, Director confirms; defaults 1% minimum margin, no maximum).
- Who sees costing: Sales Manager, Accountant, Director and the quotation's creator.
- Customer advances: the Accountant's approval is enough.
- Amendments are started by the Clerk only. Open paper vouchers at go-live are typed in and
  approved again (unpaid balance only).
- Opening stock is counted and loaded at go-live (P16-15, built).
- Accounting follows the usual standards: GRNI, supplier advances, price differences into stock
  cost (IAS 2), foreign purchases at each transaction date's rate (IAS 21). The auditors'
  confirmation is still awaited (a summary was sent to them).
- VAT 18%. SSCL: one dated rate (2.5%) charged on a share per code (VAT-SSCL-M 85% = 2.125%,
  services 100% = 2.5%, VAT-SSCL-R 50% = 1.25%); rates entered by the Admin in Settings → Tax
  rates and **confirmed by the Director**.
- Tax invoice codes: WS = **W1**, IM = **I1**, HO = **H1** (Admin enters them in Settings →
  Divisions). Invoice numbers like 26NOV_W1_01, monthly per division. Amounts shown as
  115,750.00; dates on tax invoices MM/DD/YYYY.
- SVAT ended 1 Oct 2025: no SVAT line.
- One stores person; a single Admin account (no backup Admin).

**Phase 2 (answers of 2–3 Nov 2026)**
- **Current accounting system: QuickBooks** (exports to Excel). Migration (P2-28) should read
  QuickBooks' own Excel exports (trial balance, A/R aging detail, A/P aging detail, item list)
  as well as templates.
- **Financial year April–March.** Phase 2 goes live **all at once on 1 April** (year to agree).
- **Manual journals:** the Director approves (every one).
- **Tax invoices:** prepared by Sales or the Accountant; issued by the Director, the Accountant
  and **chosen salespeople**: special action **"Issue tax invoices"** (`issue_tax_invoices`),
  held by the Director and Accountant roles, granted one by one by the Admin as a sensitive
  grant the Director confirms. The Sales Manager too only when granted.
- **Credit notes:** approved by the **Director**, or by a person the Admin gives **"Approve
  credit notes"** (`approve_credit_notes`) to, confirmed by the Director.
- **Credit limits (P2-08): block.** A customer over the credit limit or with overdue invoices
  gets no new sales order or tax invoice until the Director allows that document.
- **Withholding tax: none currently.** Build P2-12 switched off (nothing happens unless the
  Accountant sets WHT up).
- **No payment gateway / no Pay Now button.** When a customer asks to pay by card, SML sends a
  **OnePay** payment link. P2-27 becomes: invoice tracking (sent, viewed, paid) plus recording
  the OnePay link sent for an invoice and the card payment received.
- **Finished goods (question 4): default taken, no answer** — delivery notes and returned goods
  change no stock until production (Phase 3). He may still decide otherwise before P2-18.
- **Depreciation classes (P2-19):** proposed to him (land, buildings, plant and machinery,
  moulds and tooling, motor vehicles, furniture and fittings, office and computer equipment)
  with typical methods and rates; **he will send the auditors' methods and rates.** Make
  classes and rates editable by the Accountant; moulds may later depreciate by shots.

## 6. Waiting on the owner (information to come to you)

| What | For | Status |
| --- | --- | --- |
| Depreciation method and rate per class, from the auditors | P2-19 | He will send "soon" |
| QuickBooks Excel exports: trial balance, A/R aging detail (open invoices), A/P aging detail (open bills), item list | P2-28 | He will send "soon" |
| Bank statement exports in **Excel/CSV**, one per bank (only a Commercial Bank **PDF** so far) | P2-15 | Asked |
| The auditors' reply to the accounting summary | Go-live | Waiting |
| Finished-goods decision (question 4) if he wants stock from delivery notes before Phase 3 | P2-18 | Default taken |
| How OnePay links are made (from a OnePay merchant portal by hand, or an API?) | P2-27 | Ask when P2-27 starts |
| GitHub Team upgrade (to enforce PR + checks on `main`, decision 0003) | Before go-live | Later |
| Hostinger VPS (production + test), Backblaze B2 bucket and key | P1-12 | After testing |

## 7. Things the owner (or his Admin/staff) must do in the ERP

- Admin: enter **W1, I1, H1** (Settings → Divisions) and the **company TIN** (Settings →
  Company) — tax invoices are refused without them.
- Admin: enter the SSCL and VAT rates (Settings → Tax rates); the **Director confirms** them.
- Admin: grant **Issue tax invoices** / **Approve credit notes** to chosen people (user page);
  the Director confirms.
- Staff UAT on his PC with the shared test document (Docs artifact: UAT guide
  https://claude.ai/artifact/4cJLdjTHo3a5ut6N7NGTGH). Auditors' summary doc:
  https://claude.ai/artifact/DjYHjkhdVqoTrePDibXFEG.
- Later: type the mailbox password into Settings → Email himself (mail.smlengineers.com, port
  465 SSL, user accounts@smlengineers.com).

## 8. Your next work, in order (`docs/backlog/phase-2.md`)

Notes from this session's design so far; read the backlog text of each task too.

- **P2-07 Customer receipts and allocation.** The Cashier records money in (cheque, transfer,
  cash, card, QR; "record_receipt" action already exists for advances), allocated to one or
  more issued invoices of a customer; existing **customer advances** (`apps/sales/advances.py`,
  liability `customer_advances`) set off against invoices of their order. Posting: Dr bank /
  Undeposited funds (system role `undeposited_funds`) for cheques until deposited (P2-14),
  Cr Accounts receivable **with the customer** (ledger lines now carry `customer`; AR lines
  require it). Post-dated cheques wait for their date. An invoice's open balance =
  total − credit notes − allocations; never allocate more. Consider who approves (the
  Accountant approves advances today).
- **P2-08 Statements, aging, credit limits** — **block** (section 5) with a Director release
  per document, logged. Reminders by email from the finance mailbox (document email kind
  `customer_statement` exists in `core/email_catalogue.py`).
- **P2-09 Export invoices** — tax invoices are **LKR only** now (`invoices.create` refuses
  other currencies); add the customer's currency at the day's rate, realised exchange
  differences on receipts (system roles `exchange_gain`/`exchange_loss` exist).
- P2-10 supplier statements and payables aging; P2-11 payment cancellation / spoiled cheques /
  foreign-currency payments; **P2-12 WHT built switched off**; P2-13 reorder alerts; P2-14
  cheque register and deposits; P2-15 bank statement import (Commercial Bank PDF layout: date,
  description, debit, credit, balance with Cr/Dr; templates per bank editable); P2-16 bank
  reconciliation; P2-17 petty cash; P2-18 stock issues and count; P2-19 fixed assets (classes
  above); P2-20 tax reports; P2-21 revaluation; P2-22 budgets; P2-23 month/year-end close
  (until then the balance sheet shows "Profit to date, not yet closed to retained earnings");
  P2-24 cash flow and dashboard; P2-25 planner; P2-26 report builder; **P2-27 = OnePay link
  and invoice tracking**; **P2-28 migration from QuickBooks exports**; P2-29 parallel run and
  go-live (1 April).

## 9. Technical notes (learned the hard way)

**The workspace.** No PyPI/npm access and no Django or node_modules locally: you cannot run
tests. Only `ruff` works: `/root/.local/bin/ruff check .` and `ruff format .` in `backend/`
(line length 100; migrations excluded). **Migrations are written by hand**; CI's
`makemigrations --check` verifies them. **CI is the test runner.** Read every test you write
against the real helpers first; most failed runs this session were test-setup mistakes.

**GitHub through `gh api`** (no `git push` problems; push with `git push -u origin <branch>`):
- Create a draft PR: `gh api repos/SML-Engineers/sml-erp/pulls -f title=... -f head=<branch> -f base=main -F draft=true -F body=@file --jq .number`
- Update a PR body: `gh api -X PATCH repos/SML-Engineers/sml-erp/pulls/<n> -F body=@file`
- Checks of the head commit: `gh api repos/SML-Engineers/sml-erp/commits/$(git rev-parse HEAD)/check-runs --jq '.check_runs[] | "\(.name): \(.status) \(.conclusion) \(.id)"'`
- Failure details: `gh api repos/SML-Engineers/sml-erp/actions/jobs/<id>/logs | grep -E "FAILED|E  |Error"`,
  or `.../check-runs/<id>/annotations`. Re-run a flaky job (e.g. Docker Hub 500):
  `gh api -X POST repos/SML-Engineers/sml-erp/actions/jobs/<id>/rerun`.
- The draft PR runs lock files, backend and frontend; full stack and production stack run only
  once the PR is marked ready. This session used a helper script, run in the background with
  a long timeout (5400000 ms), that waits for the draft checks, marks the PR ready if green
  (`gh api -X POST repos/SML-Engineers/sml-erp/pulls/<n>/ccr/ready_for_review` — an endpoint of
  this Claude environment's GitHub proxy; if it does not exist in yours, mark ready with
  `gh pr ready <n>` or ask), waits for the full run and prints the results. Recreate it in
  your scratchpad. A watcher started for an older commit may time out: always re-check the
  head commit's checks before reporting.

**Backend patterns**
- Logic in a service module per feature (`apps/sales/invoices.py`, `credit_notes.py`,
  `deliveries.py`, `apps/accounting/manual.py`, `recurring.py`, `reports.py` …); views thin;
  domain errors (`SalesError`, `AccountingError`, …) → 400 `{"detail": ...}`.
- **Permissions:** every view subclasses `AreaAccess` with `access_area`; optional
  `access_write_level` (default "manage") and new **`access_also_area`** (either area is
  enough, e.g. delivery notes sales/stores, invoices sales/accounting). Levels: view ⊂ enter ⊂
  manage; **approve includes only view**, so approver endpoints use
  `access_write_level = "view"` and the service/engine checks the role.
- **Special actions** (`apps/core/access_defaults.py` `ACTIONS`, `SENSITIVE_ACTIONS`,
  `ROLE_ACTIONS_V2..V5` + a core migration granting them to roles). Sensitive grants work only
  once the Director confirms. `effective_access(user)` is **cached on the user object** for the
  request: in tests, reload the user (`User.objects.get(pk=...)`) after granting.
- **Approval engine** `apps/core/approvals.py`: register a `DocumentType` (new optional
  `approver_action`: holders of that action count as the final role, used by credit notes);
  seed an `ApprovalRule` (level 2, director) and an `ApprovalReminder` in the app's migration;
  add the type to `tests/test_approval_reminders.py`'s expected set. Use `submit`, `approve`,
  `send_back`, `reject`, `state_of`, `why_not`, `waiting_for`, `history` (log field
  `acted_at`). Nobody approves their own document.
- **Numbers:** `apps.core.numbering.allocate(doc_type, division=..., on_date=...)` inside the
  transaction; seed the `NumberSeries` in a migration. Tax invoices and credit notes get their
  number only when issued/approved (no gaps).
- **Journal:** `apps.accounting.journal.post(user, entry_date=, narration=, lines=[Line(account,
  debit, credit, division, supplier, description, customer)], source_type=, source_id=)` and
  `reverse(...)`. Income/expense lines need a division; **AR lines need the customer**; the
  payment-lock trigger refuses Dr AP / Cr bank unless `source_type='supplier_payment'`.
  `apps/accounting/sources.py` maps `source_type` → document page for drill-down: **add every
  new posting document there.**
- **DB guards** pattern: a `BEFORE UPDATE OR DELETE` trigger on the header (status
  transitions, fields frozen after draft, delete only drafts) and a child trigger on lines; test
  them with `.update()` inside `transaction.atomic()` and `pytest.raises(DatabaseError)`.
- Taxes: `apps.accounting.taxes.calculate(tax_code, net, on_date)` (per-line rounding, SSCL then
  VAT on net+SSCL); `TaxComponent.sales_account` holds the payable account; `label` is printed.
  Sales accounts per division: `sales.SalesAccount` (goods, tooling), page Accounts → Sales accounts.
- Exports: `apps/core/exports.py` `response(fmt, title=, subtitle=, columns=[Column], rows=,
  filename=, user=, totals=True)`; rows with `STRONG` print bold; `?export=xlsx|pdf`.
- Printing: `apps/sales/document_pdf.py` (letterhead, Styles, money, qty); tax invoice
  `invoice_printing.py`, credit note `credit_note_printing.py`, delivery note
  `delivery_printing.py`. Tests read PDFs with `render(..., compress=False)`.
- Document email: `apps/core/document_email.draft/send`, kinds in `core/email_catalogue.py`
  (see `apps/sales/invoice_email.py`).
- Tests (pytest, `tests/test_*.py`): `from .test_access import as_user, person`; files via an
  autouse `InMemoryStorage` fixture; tax rates via `taxes.add_rate(accountant, component,
  effective_from=date(2024,1,1), rate=...)`; `Company.objects.filter(pk=1).update(tin=...)`;
  `customers.create_customer(..., confirmed=True)` when names repeat;
  `workflow.record_outcome` returns the updated quotation (use it); every sales order line needs
  a delivery schedule; `tests/test_tax_invoices.py` has `make_order` / `deliver` helpers that
  other tests import (`from . import test_tax_invoices as base`).

**Frontend patterns**
- Pages `src/pages`, API clients `src/api`, routes `src/App.tsx`, menu `src/layout/menu.ts`
  (items need view on `area`, or on new `alsoArea`), wording in `src/i18n/en.json` (edit with a
  Python json load/dump keeping key order, `ensure_ascii=False, indent=2`, trailing newline).
- Components: `DataTable`, `SearchSelect` (combobox; choose with `mouseDown` in tests),
  `ExportLinks`, `SendEmailForm`, `JournalLines` (shared journal line editor). Decimals:
  `formatDecimal`, `formatQuantity`, `sumDecimal` (`src/lib/decimal.ts`).
- Tests: Vitest + Testing Library; `mockApi({"GET /api/v1/x/?a=1": {body}})` — URLs must match
  exactly; use a **function route** when the page refetches after an action; `renderAt(path,
  element, routePath)`. Optional new API fields are typed optional so older fixtures compile.

## 10. Open loose ends

- Backlog P2-27 text still says PayHere; rewrite it for OnePay links when starting it.
- The "Sales Manager" demo user can prepare but not issue invoices until granted.
- UAT tasks P1-12, P15-12, P16-14 stay open until the owner's staff test and the servers exist.
- Promised documents: test scripts per role exist in the UAT guide for phases 1–1.6; Phase 2
  needs its own when it nears completion; a go-live checklist (1 April) at P2-29.
