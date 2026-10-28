# SML ERP

Web-based ERP for SML Engineers: payment voucher approval, financial accounting, sales,
goods receipt and inspection, and production for the machining workshop and the injection
moulding plant.

| Document | Purpose |
| --- | --- |
| [docs/spec.md](docs/spec.md) | Full system design specification |
| [docs/backlog/phase-1.md](docs/backlog/phase-1.md) | Task list for Phase 0 + 1 (core and payment vouchers) |
| [docs/decisions/](docs/decisions/) | Records of technical decisions |
| [CLAUDE.md](CLAUDE.md) | Standing instructions for Claude Code |

## Phases

| Phase | Scope |
| --- | --- |
| 0 + 1 | Core foundation, admin settings, payment voucher approval, supplier payments |
| 1.5 | Customers, quotations, proforma invoices, sales orders, export sales |
| 2 | Financial accounting, goods receipt and incoming inspection; 2b payroll |
| 3 | Production, supervisor entry pages, job and production order profitability |

## Running it on a developer machine

Needs Docker (with Docker Compose) and `make`.

```bash
make up      # first run builds everything; open http://localhost:8080
make test    # backend and frontend tests
make logs    # follow the logs
make down    # stop (data is kept)
make help    # all commands
```

`make up` creates `.env` from `.env.example` on the first run. Those values are for a
developer's own machine only; servers get their own secrets, which are never committed.

| Address | What |
| --- | --- |
| http://localhost:8080 | The application (React app and API through Nginx) |
| http://localhost:8080/api/v1/health/ | API health check |

## Structure

```
backend/    Django + Django REST Framework (config/, apps/, tests/)
frontend/   React + TypeScript (Vite)
deploy/     Docker Compose and Nginx configuration
docs/       Specification, backlog, decisions
```

Every pull request is checked automatically on GitHub (lint, tests, a production build,
and the full stack started with `make up` and tested with `make test`).
