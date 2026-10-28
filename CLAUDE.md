# SML ERP — instructions for Claude Code

Web-based ERP for SML Engineers, a company with two production divisions: a metal
machining workshop and a plastic injection moulding plant (Sri Lanka, base currency LKR).

- **Full specification:** `docs/spec.md`. Read the sections relevant to your task before
  writing code. If the spec and these instructions disagree, stop and ask.
- **Work queue:** `docs/backlog/`. Work on one task at a time, in order, unless told otherwise.
  Tick the task's checkbox in the backlog file in the same pull request that completes it.

## Tech stack

| Layer | Choice |
| --- | --- |
| Backend | Python 3.12, Django 5.2 LTS, Django REST Framework |
| Database | PostgreSQL 16 |
| Jobs | Celery + Redis |
| Files | S3-compatible storage (SeaweedFS in Docker), via `django-storages` |
| Frontend | React + TypeScript, Vite, TanStack Query, TanStack Table, React Router |
| i18n | Django i18n + `react-i18next` (English first; Sinhala and Tamil later) |
| Tests | `pytest` + `pytest-django` (backend), Vitest + Testing Library (frontend) |
| Run / deploy | Docker Compose, Nginx, Hostinger Ubuntu VPS |

Do not add another framework, ORM, UI kit or state library without asking.

## Repository layout

```
backend/
  config/            Django settings, urls, celery
  apps/
    core/            users, roles, permissions, company, cost centres, number series,
                     audit log, approval engine, notifications, settings pages
    masters/         suppliers, customers, banks, divisions, sections, machines, shifts, currencies
    accounting/      chart of accounts, journal entries, periods
    vouchers/        Phase 1: voucher types, vouchers, lines, attachments, workflow
    payments/        Phase 1: supplier payments
  tests/
frontend/
  src/
    pages/  components/  api/  i18n/
deploy/              docker-compose files, nginx config, backup scripts
docs/                spec.md, backlog/, decisions/
```

Later phases add apps (`sales`, `purchasing`, `inventory`, `quality`, `production`, `payroll`)
following the same pattern.

## Non-negotiable rules

These protect the company's money and records. Never weaken them, even if a task seems to ask.

1. **Money is `NUMERIC(18,2)` / `DecimalField(max_digits=18, decimal_places=2)` and Python
   `Decimal`.** Never `float` anywhere money, quantities or rates are calculated or stored.
   Quantities and rates use `DecimalField` with an explicit precision.
2. **Journal entries must balance.** Total debits = total credits, checked in the service and
   by a database constraint/trigger.
3. **Posted journal entries are never updated or deleted.** Corrections are reversing entries.
4. **No supplier payment without Director approval.** Enforced in the UI, the payment service
   and a PostgreSQL trigger (spec 4.6). Payments may never exceed the approved amount.
5. **Segregation of duties.** A user cannot approve a document they created, or approve at
   two levels of the same document.
6. **Every voucher needs all three levels** (Clerk → Accountant → Director). No type or amount
   skips the Director.
7. **Audit log and approval log are insert-only.** No role, including Admin, can edit them.
8. **Permissions are checked on the server** for every API endpoint, never only in the UI.
9. **Codes used on transactions are immutable**; master records with history are deactivated,
   never deleted.
10. **Document numbers** come from the number-series service inside the saving transaction.
11. **Dated settings** (rates, limits, exchange rates) are effective-dated; old documents keep
    the values in force when they were created.
12. **No secrets in the repository.** Use environment variables and `.env.example`.

## How to work

- One backlog task per branch and pull request. Branch name: `task/P1-07-voucher-entry`.
- Write tests for every business rule, including the failure cases (e.g. "payment for an
  unapproved voucher is refused"). A task is not done until its acceptance criteria are tests
  that pass.
- Business logic lives in `services.py` per app, not in views or serializers. Views stay thin.
- Use database transactions for anything that writes more than one row.
- Migrations: never edit a migration that has been merged to `main`; add a new one.
  Database triggers and constraints are created in migrations (`RunSQL`) and tested.
- Keep the API RESTful under `/api/v1/`. The frontend uses only this API.
- UI: table- and form-heavy, clean and readable; approval and shop-floor pages must work on a
  phone. Keep visual conventions consistent across pages.
- Run `make test` (or the documented equivalent) before opening a pull request, and explain in
  the PR description what changed and how it was tested, in plain language a non-developer
  owner can follow.
- If a requirement is unclear or seems wrong for the business, ask instead of guessing.

## Glossary

| Term | Meaning |
| --- | --- |
| L1 / Clerk | Accounts Clerk: creates vouchers, uploads scanned invoices |
| L2 / Accountant | Verifies and codes vouchers; first approval |
| L3 / Director | Final approval |
| Voucher | Request to pay a supplier (or petty cash, transfer, reimbursement), with invoice scans |
| Division → Section → Machine | Factory structure, e.g. Workshop → Manual Milling → M-MIL-01 |
| Cost centre | Workshop, Moulding, Administration; every income/expense line carries one |
| GRN | Goods received note |
| OEE | Overall equipment effectiveness = availability × performance × quality |
