# CI / GitHub Actions Setup

This document describes the CI pipeline for `sp-rtk-base-relay` and the one-time
setup required to enable the dynamic coverage badge.

## Overview

The CI workflow (`.github/workflows/ci.yml`) runs on:

- Every push to `main`
- Every pull request targeting `main`
- Manual trigger (`workflow_dispatch` from the Actions tab)

In-progress runs on the same branch are cancelled when new commits arrive
(`concurrency.cancel-in-progress: true`).

## Jobs

### 1. `lint` — Lint & Type Check
Fast-fail quality gate running on Python 3.12:

| Step | Tool | Blocking? |
|---|---|---|
| Lint | `ruff check .` | ✅ Yes |
| Format check | `ruff format --check .` | ✅ Yes |
| Strict types | `mypy src` | ✅ Yes |
| Strict types | `pyright src` | ✅ Yes |
| Advisory lint | `pylint src` | ❌ Advisory (`continue-on-error`) |

### 2. `test` — Unit Tests (matrix)
Runs the full unit-test suite across **Python 3.10, 3.11, 3.12, 3.13**
on `ubuntu-latest`. `fail-fast: false`, so all versions always report.

- `uv sync --locked --all-extras`
- `uv run pytest` with coverage (XML + HTML + JUnit)
- Coverage threshold enforced via `--cov-fail-under=70` in `pyproject.toml`
- Artifacts uploaded:
  - `coverage-report` (XML + HTML, from Python 3.12 only)
  - `pytest-junit-py<VERSION>` (JUnit XML, all versions, even on failure)

### 3. `build` — Package Build
Runs after `test` passes. Verifies the package still builds cleanly:

- `uv build` → `dist/*.whl` and `dist/*.tar.gz`
- Uploads the `dist/` directory as an artifact

## Coverage Badge — One-Time Setup

The coverage badge uses a **public GitHub Gist** + **shields.io** (no third-party
services). Follow these steps once to activate it.

### Step 1 — Create a public Gist

1. Go to https://gist.github.com
2. Create a **public** gist with:
   - **Filename**: `sp-rtk-base-relay-coverage.json`
   - **Content** (placeholder; the workflow will overwrite):
     ```json
     { "schemaVersion": 1, "label": "coverage", "message": "unknown", "color": "lightgrey" }
     ```
3. Click **Create public gist**.
4. Copy the **Gist ID** from the URL
   (e.g. `https://gist.github.com/rodenj1/abc123def456...` → `abc123def456...`).

### Step 2 — Create a Personal Access Token

1. Go to https://github.com/settings/tokens?type=beta (fine-grained token) or
   https://github.com/settings/tokens/new (classic).
2. For a **classic** token: scope = `gist` only. Expiration: ≥ 90 days.
3. For a **fine-grained** token: resource = just the gist, permission
   **Gists: Read and write**.
4. Copy the token value **once** — GitHub won't show it again.

### Step 3 — Add repo secrets

In https://github.com/rodenj1/sp-rtk-base-relay/settings/secrets/actions,
click **New repository secret** and add two secrets:

| Name | Value |
|---|---|
| `GIST_SECRET` | The PAT from Step 2 |
| `COVERAGE_GIST_ID` | The Gist ID from Step 1 |

### Step 4 — Verify

Push any commit to `main` (or manually run the workflow from the Actions tab).
The `test (Python 3.12)` job will:

1. Parse `coverage.xml` → compute the coverage percent
2. Pick a badge color (red < 60, yellow < 70, yellowgreen < 80, green < 90, brightgreen ≥ 90)
3. Write `{schemaVersion, label, message, color}` to your gist

shields.io reads the gist JSON and serves a live SVG badge at:

```
https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/rodenj1/<GIST_ID>/raw/sp-rtk-base-relay-coverage.json
```

### Step 5 — Update the README badge URL

After Step 4 succeeds, edit `README.md` and replace `<GIST_ID>` in the coverage
badge URL with your actual gist ID.

> **Until the secrets are configured**, the badge-update step is silently
> skipped (`if: env.GIST_SECRET != ''`) and CI continues to pass. The badge in
> the README will just show "unknown" until the gist is populated.

## Troubleshooting

### "uv sync --locked" fails with "lock file is out of date"
Run `uv lock` locally and commit the updated `uv.lock`.

### A Python version's tests fail but others pass
Check `pytest-junit-py<VERSION>` artifact on that run. Common causes:
- Version-specific stdlib behavior (asyncio, typing runtime)
- Third-party library support gaps (most often on new 3.13 release)

### Coverage badge shows "unknown"
1. Check the Actions run for the `Update coverage badge` step.
2. Verify both `GIST_SECRET` and `COVERAGE_GIST_ID` are set in repo secrets.
3. Verify the PAT hasn't expired.
4. Badge updates only on **push to main** — PRs don't update it.

### Ruff flags code that was just fine
Check `[tool.ruff.lint.ignore]` in `pyproject.toml`. The legacy baseline
ignores a set of rules that were present when ruff was introduced — address
them in follow-up PRs and remove the ignores one-by-one.
