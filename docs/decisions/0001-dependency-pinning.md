# 0001 — Dependency versions

**Status:** temporary, to be finished in P0-02.

## Context

The project skeleton (P0-01) was written in a workspace that cannot reach the Python and
npm package registries. Exact versions could therefore not be resolved and locked there.

## Decision

- `backend/requirements*.txt` and `frontend/package.json` bound each package to its current
  major (and for Django, minor) release line, e.g. `Django>=5.2,<5.3`.
- CI installs from these bounds on GitHub's servers and uploads the resolved versions as
  build artifacts (`backend-installed-versions`, `frontend-package-lock`).

## Follow-up (P0-02)

Commit exact locks from a CI run that passed: `backend/requirements.lock.txt` (installed by the
Dockerfile and CI) and `frontend/package-lock.json` (installed with `npm ci`). After that,
dependency upgrades are deliberate pull requests, never silent.
