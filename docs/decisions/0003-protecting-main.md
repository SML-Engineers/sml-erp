# 0003 — Protecting the main branch

**Status:** accepted on 2026-10-28: Option B (free plan, agreed practice) during development;
revisit before Phase 1 go-live (backlog P1-12).

## Context

Backlog task P0-02 requires that `main`, the code that will run the company's books, can only
change through a pull request whose automatic checks have passed. GitHub enforces this with
branch protection rules (or rulesets). For a **private** repository owned by an organization on
the **GitHub Free** plan, GitHub does not offer them: the API answers "Upgrade to GitHub Pro or
make this repository public to enable this feature."

Making the repository public is not an option for an ERP holding financial logic.

## Options

| Option | Enforced by GitHub | Cost |
| --- | --- | --- |
| A. Upgrade the SML-Engineers organization to **GitHub Team** | Yes: no direct pushes to `main`; merge only when CI passes | Per user per month; only people with access to the code count (likely 1–2) |
| B. Stay on Free, by agreed practice | No: relies on everyone (people and Claude) always using pull requests and waiting for green checks | Free |

## Recommendation

Option A once the system holds real data (before go-live of Phase 1 at the latest). Until then
Option B is workable: Claude Code always works on a task branch, opens a pull request, and
reports the CI result before asking the owner to merge.

## Settings to apply after upgrading (Option A)

Ruleset on `main`: require a pull request before merging; require status checks "Lock files
present and current", "Backend tests", "Frontend tests" and "Full stack (make up, make test)"
to pass; require branches to be up to date; block force pushes and deletion. Claude Code can
apply these through the API once the plan allows it.
