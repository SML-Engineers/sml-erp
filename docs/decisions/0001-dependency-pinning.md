# 0001 — Dependency versions

**Status:** accepted (P0-01, completed in P0-02).

## Decision

Two kinds of file, for the backend and the frontend:

| Purpose | Backend | Frontend |
| --- | --- | --- |
| Allowed version ranges, edited by people | `backend/requirements.in`, `backend/requirements-dev.in` | `frontend/package.json` |
| Exact versions, generated, never edited by hand | `backend/requirements.lock.txt`, `backend/requirements-dev.lock.txt` (with SHA-256 hashes) | `frontend/package-lock.json` |

- Docker images and CI install **only** from the lock files (`pip install --require-hashes`,
  `npm ci`), so every machine runs exactly the same, verified packages.
- The **Dependency locks** workflow (`.github/workflows/locks.yml`) regenerates the locks when
  the ranges change on a task branch and commits them to that branch. They reach `main` only
  through the pull request, after CI has passed.
- **Dependabot** proposes updates monthly (and security fixes as soon as they are known) as
  pull requests, each tested by CI before anyone merges it.

## Why

The workspace where development happens cannot reach the package registries, so the locks are
generated on GitHub's servers. Exact pins with hashes also protect against a tampered or
silently changed package reaching the servers that hold the company's financial data.

## Changing a dependency

1. Edit the range in `requirements*.in` or `package.json` on a task branch and push.
2. The locks workflow commits new lock files to the branch.
3. Push any further commit so CI runs against the new locks, then review the pull request.
