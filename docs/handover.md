# Handover: continuing SML ERP development

Written 31 Oct 2026 at the end of a long Claude session, for the next Claude session (or any
developer) picking up the work. Read this first, then `CLAUDE.md`, then the spec sections and
backlog task you are working on.

---

## 1. The project in one paragraph

A web ERP for **SML Engineers** (Sri Lanka, LKR): a metal machining workshop (division **WS**),
a plastic injection moulding plant (**IM**) and head office (**HO**). Django 5.2 + DRF +
PostgreSQL 16 (business rules also enforced by database triggers), Celery + Redis, SeaweedFS
(S3) for files, React + TypeScript + Vite + TanStack Query, Docker Compose, Nginx, deployed to
Hostinger VPS. Repository: **SML-Engineers/sml-erp** (GitHub). Full specification:
`docs/spec.md`. Work queue: `docs/backlog/phase-1.md` (done except P1-12) and
`docs/backlog/phase-1-5.md` (in progress). **`CLAUDE.md` holds the non-negotiable rules**
(money as Decimal, balanced and immutable journals, Director approval of every payment and
voucher, segregation of duties, insert-only logs, server-side permissions, immutable codes,
dated settings, no secrets in the repo). Never weaken them.

## 2. How we work with the owner

- The owner (GitHub user **mewanthaexam1**) is not a developer. Explain everything in plain
  language, short steps, exact commands to paste. PR descriptions are written for him:
  *what changed, who can do what, how it was tested*.
- **One backlog task per branch and pull request** (`task/P15-04-machining-costing`); small
  fixes from his testing go on `fix/...` branches. Tick the task's checkbox in the backlog in
  the same PR.
- **Never push to `main`, never merge your own PR.** Open the PR, wait until **all five CI
  checks are green**, then tell the owner it can be merged. He merges and sends a **screenshot
  of the merged PR as the signal to continue**. Don't ask him to merge before checks are green.
- He tests on his own PC (see section 5) and sends screenshots. Fix what he finds as small PRs
  first; they take priority over backlog work. Keep a numbered list of his findings.
- If a requirement is unclear or wrong for the business, ask him; record his answers in
  `docs/spec.md` and the backlog ("owner's decision, <date>").
- Attribution: commits end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` and a `Claude-Session:` line;
  PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)` and the
  session link (use whatever the new session's system reminder says).

## 3. Where things stand (31 Oct 2026)

**Phase 0 + Phase 1 (payment vouchers): complete**, except **P1-12 UAT and go-live**, which
waits for the domain, the servers and Backblaze B2 (section 6). Built: users, roles, 2FA,
access overrides and review, audit log, approval engine with reminders, number series,
divisions/sections/machines, shifts and rosters, currencies and exchange rates, quotation
limits, suppliers/payees with bank-detail controls, company bank accounts and cheque books,
chart of accounts, journal and periods, taxes (QuickBooks style), document email, voucher
types, voucher entry → Accountant review/coding (with division splits) → Director bulk approval,
row actions (print with COPY watermark, delete, send down, withdraw), amendments, cancellation,
supplier payments (DB trigger: no payment without Director approval, never above approved),
voucher reports, dashboard, hosting files (`docs/hosting.md`), nightly encrypted backups with
restic (`docs/backups.md`), demo data command.

**Phase 1.5 (sales documents), backlog `docs/backlog/phase-1-5.md`:**

| Task | State | PR |
| --- | --- | --- |
| P15-00 plan | merged | #58 |
| P15-01 Customers and contacts | merged | #59 |
| P15-02 Costing rates (materials per kg, division overhead/margin/setup rate) | merged | #60 |
| P15-03 Quotation entry (new `apps/sales`) | merged | #62 |
| **P15-04 Machining costing** | **next** | – |
| P15-05 Moulding costing and tooling | to do | – |
| P15-06 Approval, revisions, status | to do | – |
| P15-07 Printed quotation and email | to do (needs owner's sample) | – |
| P15-08 Proforma invoices + packing list | to do (needs owner's sample) | – |
| P15-09 Customer advances | to do | – |
| P15-10 Sales orders | to do | – |
| P15-11 Sales reports and dashboard | to do | – |
| P15-12 UAT and go-live | to do | – |

Recent fix PRs from the owner's testing (all merged): #55 nginx re-resolves the backend after
a rebuild; #56 Pay button label invisible (`.page a` beat `.button-link`), no approval counts
on the Cashier's dashboard; #57 searchable account picker (`components/SearchSelect.tsx`),
Approve saves coding first, roomier coding row, first queue item opens, payee box shown from
the start and closes after choice, invoice lines fit, drawn paperclip icon
(`components/FilesIcon.tsx`), Actions button beside the title; #61 Vite polling so screens update
after a Pull on Windows.

**Open PR not ours:** #23 (Dependabot, TypeScript 5.8 → 5.9). Check its CI; if green, tell
the owner it can be merged.

## 4. Owner's decisions to respect

Recorded in the spec and backlog; the important ones:

- **Every voucher needs all three levels** (Clerk → Accountant → Director); no thresholds.
- **Cashier payment methods:** cheque, bank transfer, cash, card and QR (LankaQR).
- **Quotations (31 Oct 2026):** the **Director approves every quotation before it is printed
  or sent**, including by email. The division's quotation limits (min margin %, max value) are
  shown to the Director as **warnings**, not as the approval trigger. Until approved, a PDF is
  a draft marked NOT APPROVED and cannot be emailed.
- **Who sees costing:** Sales Manager, Accountant, Director and the quotation's creator; not
  other Sales Executives. Never on the customer's PDF/email.
- **Customer advances:** the Accountant's approval is enough (not the Director's).
- **Packing list with the proforma** (P15-08): cartons, qty per carton, net/gross weight,
  carton dimensions, totals, as its own page.
- Hosting: Hostinger VPS (KVM 4 production, KVM 2 test), India data centre. Backups to
  Backblaze B2. Domain: not bought yet; advised a **.lk CAT2** domain.
- SVAT ended 1 Oct 2025: no SVAT line on documents.
- Interactive QuickBooks-style features are placed in later phases (spec 7A).

## 5. The owner's PC (local testing)

- Windows, Intel, **Docker Desktop**, PowerShell. Repository cloned with **GitHub Desktop** to
  `D:\GitHub\sml-erp` (the old ZIP copy `D:\SMLERP` is no longer used). `.env` lives there.
- Docker Engine needed `"dns": ["8.8.8.8","1.1.1.1"]` (his router's IPv6 DNS failed in Docker).
- ERP at **http://localhost:8080**. His Admin account: mewantha@smlengineers.com.
- **Update routine:** GitHub Desktop → Fetch origin → Pull origin, then F5. When a PR adds
  **migrations**, also:
  `docker compose -f deploy/docker-compose.dev.yml --env-file .env restart backend`
  (the dev backend runs `migrate` only at start). When dependencies or Dockerfiles change:
  `... up -d --build`. Tell him which is needed in every "ready to merge" message.
- **Demo data** is loaded (`python manage.py load_demo_data`, refuses on production, once
  only): users `clerk@`, `accountant@`, `director@`, `cashier@demo.sml.lk`, password
  `Demo-SML-2026!`, one shared TOTP entry. Names: Nimal Perera (Clerk), Kumari Silva
  (Accountant), Ruwan Jayasinghe (Director), Sunil Fernando (Cashier). He has walked the whole
  voucher journey with them. There is **no demo Sales Executive yet**; to try sales he must
  give a user the Sales Executive role. Adding one (plus customers, materials and rates) to
  the demo command is a sensible small task.
- He was told: the Sales Manager and Director **approve**, they do not enter; the Accountant
  only views sales.

## 6. Waiting on the owner

- **Quotation and proforma samples** (PDF/photo) for P15-07/P15-08 layout. He tried to attach
  them on 31 Oct but only a screenshot arrived; ask again before P15-07.
- Domain purchase (.lk CAT2); two Hostinger VPS; Backblaze B2 bucket + key → then set up the
  test server together using `docs/hosting.md` and `docs/backups.md`, then production (P1-12).
- Accountant's payroll answers; one bank statement export per bank used; finance mailbox SMTP
  details; tax rates to enter; tax-invoice codes per division; quotation limits (Director);
  decision whether the Accountant may start amendments.
- Promised but not yet written: **test scripts per role** (Clerk, Accountant, Director,
  Cashier, and later Sales) with expected results, and a **go-live checklist** (data loading,
  who does what). Good to produce as documents (Docs artifacts) when he asks or at P1-12.
- Known follow-ups: payment cancellation (reversing entry / spoiled cheque) and
  foreign-currency supplier payments are not built yet.

## 7. Technical notes and gotchas (learned the hard way)

**Environment of the Claude session.** The cloud workspace had **no access to PyPI or npm**,
so backend tests and frontend tests could not run locally: only
`/root/.local/bin/ruff check .` and `ruff format .` (run in `backend/`, on everything including
tests). **Migrations were written by hand** and verified by CI's "no missing migration" check.
CI is the test runner: push, then poll checks.

**GitHub via `gh api`:**
- Create PR: `gh api repos/SML-Engineers/sml-erp/pulls -f base=main -f head=<branch> -f title=... -F body=@file --jq .number`
- Poll checks in a background loop:
  `gh api repos/SML-Engineers/sml-erp/commits/<sha>/check-runs --jq '.check_runs[] | "\(.name)|\(.status)|\(.conclusion)|\(.id)"'`
- Read failures: `gh api repos/SML-Engineers/sml-erp/check-runs/<id>/annotations` (logs are
  not downloadable; `actions/jobs/<id> --jq .steps` shows which step failed).
- Update a PR body: `gh api -X PATCH repos/.../pulls/<n> -F body=@file`.

**CI jobs (only on pull requests):** lock files; backend (ruff, makemigrations --check,
deployment checks, pytest); frontend (typecheck, vitest, build); full stack (`make up`,
`make test`); production stack (HTTPS like the servers, including a backup → wipe → restore
round trip).

**Backend patterns:**
- Business logic in `services.py` (or a named module like `customers.py`,
  `costing_rates.py`); views thin. Errors are domain exceptions (`MastersError`,
  `VoucherError`, `SalesError`) turned into 400 `{"detail": ...}`; duplicate warnings use 409
  with `warnings` and `needs_confirmation`.
- Every endpoint's permission class must subclass `AreaAccess` with `access_area` in `AREAS`
  (a test walks all URLs), or be listed in that test as reviewed.
- **Access levels:** `IMPLIES` = view ⊂ enter ⊂ manage, and approve ⊃ view only. **Approve does
  not include Enter**: the Sales Manager and Director cannot reach `enter` endpoints. Give
  approver actions their own endpoint with `access_write_level = "approve"` (see
  `CustomerActiveView`).
- Inactive roles grant nothing; the Sales Executive and Sales Manager roles were switched on
  in `core/0016`. Later-phase roles (purchasing etc.) are still off.
- Codes fixed once used: `first_used_at` + `masters_code_guard` trigger; dated rates:
  `masters_rate_guard` (refuses update/delete once `effective_from <= today` in Asia/Colombo).
  Django's `PROTECT` FKs often fire before the trigger in tests: test the trigger through an
  update (e.g. changing the code), not a delete.
- Audit: `apps.core.audit.register(Model)` in the app's `ready()`; label changes with
  `audit_context(event, reason)`.
- Numbers: `apps.core.numbering.allocate(document_type, division=..., on_date=...)` inside the
  saving transaction. Series exist for quotation (`QL{YY}{MM}{DD}{XX}`), proforma
  (`PI-{YYYY}-{NNNN}`), customer (`C{NNNN}`), payee, voucher, payment.
- Taxes: `apps.accounting.taxes.calculate(tax_code, net, on_date)` → per-line rounding;
  `taxes.mark_used`. Exchange rates: `masters.currencies.rate_on(currency, date)`,
  `to_lkr`, `mark_rate_used`.
- Files: PDF/JPG/PNG checked by magic bytes, ≤ 20 MB, SHA-256 duplicate warnings (vouchers
  and quotations do it the same way). Tests use `InMemoryStorage` via a fixture.
- Exports: `core/exports.py` (xlsx, pdf); export query parameter is `?export=xlsx|pdf`
  (`format` is reserved by DRF). Excel import pattern: `masters/excel.py` (all or nothing,
  `dry_run`, every refused row listed, floats read via `Decimal(repr(value))`).
- Tests: `tests/test_*.py`, fixtures defined locally; `from .test_access import as_user,
  person` (`person(email, *roles, divisions=..., all_divisions=...)`).

**Frontend patterns:**
- Pages in `src/pages`, API clients in `src/api`, menu in `src/layout/menu.ts` (item visible
  when the user can *view* its area), routes in `src/App.tsx`, all wording in
  `src/i18n/en.json` (edit with a JSON load/dump script to keep formatting).
- `DataTable` (`money: true` adds a Total row; `noTotal: true` for rates and prices).
  `SearchSelect` for long lists (role `combobox`/`option`; choose with `mouseDown` in tests).
  `formatDecimal`, `formatQuantity` (drops trailing zeros), `sumDecimal` in `src/lib/decimal.ts`.
- Tests: Vitest + Testing Library with `mockApi({"METHOD /api/v1/path/": {body}})`; URLs must
  match exactly, query strings included. A function route lets the mock answer differently
  per request. `renderAt(path, element, routePath)`.
- CSS: `.page a` sets link colour, so button-style links use `a.button-link`.
- Dev server polls files (`VITE_WATCH_POLLING=1` in `deploy/docker-compose.dev.yml`).

## 8. Next task in detail: P15-04 Machining costing

Read spec 5.1 (Machining costing table) and backlog P15-04. Suggested design:

- New model `QuotationCosting` (or `QuotationLineCosting`) per quotation line, **internal
  only**, with a child table of operations: material (material FK from P15-02, stock
  dimensions or weight per piece, cutting allowance), operations (machine FK, minutes per
  piece; rate from `masters.services.rate_on(machine, quote_date)`), setup hours (division
  setup rate ÷ quantity), subcontract amount, overhead % and margin % (defaults from
  `costing_rates.costing_rate_on(division, quote_date)`, editable), giving the **suggested unit
  price** and the **margin of the price actually quoted**, also per quantity break.
- Use the rates **in force on the quotation date** and store the rates used on the costing,
  so a later rate change never alters it (rule 11). Mark materials used (`first_used_at`).
- Lines are currently **replaced** on every draft save (`services.save` deletes and recreates
  lines); costing tied to a line must survive that (key it by line number, or stop
  recreating lines and update in place). Decide before building.
- **Visibility:** costing endpoints and fields only for Sales Manager, Accountant, Director
  and the quotation's creator (owner's decision). Test that another Sales Executive and the
  customer-facing outputs never get them.
- Weight from dimensions needs the material's density (g/cm³) and form (round bar: π/4 × d² ×
  length; plate: l × w × t; etc.). Keep all arithmetic in Decimal.
- Then P15-05 (moulding: part + runner weight ÷ cavities × resin rate + masterbatch %, cycle
  time ÷ cavities → machine hours per 1,000 pcs × machine rate, reject %, packing, tooling line)
  and P15-06 (Director approval of every quotation via the approval engine: add a
  `quotation` document type and approval rule as was done for `voucher_cancellation` in
  vouchers migration 0006; warnings from `QuotationLimit`; revisions keep the number and add
  Rev n; statuses; daily expiry job; segregation of duties).

## 9. Starting the new session

Suggested first message to the new Claude session:

> Continue the SML ERP project (GitHub SML-Engineers/sml-erp). Read `docs/handover.md`,
> `CLAUDE.md`, then `docs/backlog/phase-1-5.md` and spec section 5. The next task is
> P15-04 Machining costing. Work as described in the handover: one PR per task, plain-language
> PR descriptions, tell me when all checks are green and I will merge.

The new session needs the repository attached (it can add it itself) and a GitHub token with
push access, as this one had.
