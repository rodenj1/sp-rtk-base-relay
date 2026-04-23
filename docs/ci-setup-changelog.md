# CI / Coverage Setup — Changelog & Design Notes

> **Purpose** — captures **what** was changed, **why**, and the dead-ends
> we hit while bootstrapping GitHub Actions + Codecov for
> `sp-rtk-base-relay`.  Intended as a companion to `docs/ci-setup.md`
> (which is the operator-facing *how-to*) — this document is the
> historical record.
>
> **Timeframe** — April 21, 2026 (single day; 9 commits)
> **Branch** — `main`
> **Final state** — 3-job workflow running on every push/PR, coverage +
> test-results uploaded to Codecov, README badges live.

---

## Timeline / Commit Index

| # | Commit    | Scope                                                           |
|---|-----------|-----------------------------------------------------------------|
| 1 | `d411db9` | Initial workflow + adopt ruff (replacing black)                 |
| 2 | `d6fb14f` | Fix pre-existing strict type-check errors surfaced by CI        |
| 3 | `bbb9e98` | Upgrade deprecated Node.js 20 actions to Node.js 24             |
| 4 | `c4182cd` | Switch coverage from gist/shields.io to Codecov (OIDC)          |
| 5 | `59b904b` | Consolidate test-results upload into codecov-action             |
| 6 | `086ac83` | Empty commit — trigger first Codecov upload after onboarding    |
| 7 | `f1926f6` | Switch Codecov upload from OIDC to CODECOV_TOKEN (private repo) |
| 8 | `632b1cb` | Add Codecov badge token to README; update memory bank           |

---

## 1 · Initial Workflow + Ruff Migration (`d411db9`)

**Goal** — stand up CI from scratch: lint, multi-Python test matrix, build.

### Files added
- `.github/workflows/ci.yml`
- `docs/ci-setup.md`

### Files modified
- `pyproject.toml`
  - Added `3.13` classifier.
  - Removed `black` from `[dependency-groups.dev]`.
  - Added `ruff>=0.6.0` + a full `[tool.ruff]` configuration:
    - `line-length = 88`, `target-version = "py310"`.
    - Rule sets enabled: `E, W, F, I, B, UP, N, SIM, RUF`.
    - `[tool.ruff.lint.ignore]` legacy baseline populated with the ~20
      rule codes we didn't want to fix in the same commit — marked as a
      follow-up task.
- `README.md`
  - Changed title to **SP-RTK-Base-Relay**.
  - Added three status badges (CI, coverage, ruff).

### Automated refactor in the same commit
- `uv run ruff check --fix` + `uv run ruff format` applied across **74
  files**.  Pre-existing 1 117 unit tests kept passing; coverage stayed
  at 89.35 %.

### Workflow structure (3 jobs)

```
lint (py3.12, blocking)
    ↓
test (matrix: 3.10 / 3.11 / 3.12 / 3.13, fail-fast: false)
    ↓
build distribution (py3.12)
```

| Job   | Steps                                                                   |
|-------|-------------------------------------------------------------------------|
| lint  | `ruff check` → `ruff format --check` → `mypy --strict` → `pyright` → `pylint` (advisory) |
| test  | `uv sync --locked --all-extras` → `pytest` with XML/HTML/JUnit coverage → upload artifacts |
| build | `uv build` → upload `dist/`                                              |

**Design decisions:**
- `concurrency: { group: ci-<ref>, cancel-in-progress: true }` so new
  pushes supersede in-flight runs.
- All third-party actions pinned to **full commit SHAs** (not tags) for
  supply-chain safety — Dependabot can still bump them.
- `uv` chosen as the installer — native lock-file support, single tool
  for env + dep management, matches local dev.
- Python 3.10 floor (not 3.11) to keep the matrix honest against the
  project's declared `requires-python`.
- `fail-fast: false` so one Python version's failure doesn't cancel the
  other three.

---

## 2 · Strict-Type-Check Fixes (`d6fb14f`)

**Symptom** — first CI run went red with mypy/pyright errors.  Local
`mypy src` had been clean before, but CI runs in a pristine venv without
our IDE's cached inference.

### Root cause
`dbus-fast`'s `ProxyInterface` exposes `call_*` methods via runtime
`__getattr__`.  Mypy can't follow that — pyright can.  The two tools
disagreed per-method.

### Fixes
- `pyproject.toml` — added a mypy module override that disables
  `no-any-return` / `attr-defined` for `bluetooth_manager` and
  `bluetooth_input` specifically, plus `dbus_fast` added to
  `ignore_missing_imports`.
- `src/sp_rtk_base_relay/core/bluetooth_manager.py` — two `cast(Any, ...)`
  escape hatches on `call_set` / `call_get`, with comments explaining the
  runtime-`__getattr__` reason.
- `src/sp_rtk_base_relay/core/rtcm_client.py`
  - Annotated `HeartbeatMonitor.socket: socket.socket | None` so mypy
    stops marking the defensive `if self.socket is None` as unreachable.
  - `repr` of non-utf8 auth-response bytes now uses `{response!r}`.
- `src/sp_rtk_base_relay/core/destinations/tcp_server_destination.py` —
  removed the duplicate poison-pill check in `_broadcast_loop`.
- Misc pyright-strict annotation cleanup in `config.py`, `logger.py`,
  `serial_input.py`, `tcp_input.py`.

**Result:** Run **24759164665** green across all 4 Python versions.
1 117 tests pass at 89.34 % coverage.

---

## 3 · Node.js 24 Upgrade (`bbb9e98`)

**Symptom** — the first green run emitted GitHub's soft deprecation
warnings:

> *"Node.js 20 actions are deprecated.  Please update the following
> actions to use Node.js 24: actions/checkout, actions/upload-artifact."*

### Action-by-action bumps

| Action                               | From   | To     | SHA (7-char) | Notes                                                    |
|--------------------------------------|--------|--------|--------------|----------------------------------------------------------|
| `actions/checkout`                   | 5.0.0  | 6.0.2  | `de0fac2`    | First Node-24 major.                                     |
| `actions/upload-artifact`            | 4.6.2  | 6.0.0  | `b7c566a`    | Requires Actions runner ≥ 2.327.1 (GitHub-hosted: auto). |
| `schneegans/dynamic-badges-action`   | 1.7.0  | 1.8.0  | `0e50b8b`    | Subsequently removed when we switched to Codecov.         |
| `astral-sh/setup-uv`                 | 8.1.0  | —      | —            | Already on Node 24.                                       |

Verified via run **24759388902** — deprecation warnings gone, still green.

---

## 4 · Coverage Badge: First Codecov Attempt (OIDC) — `c4182cd`

**Problem** — the original `d411db9` workflow used the classic
*schneegans/dynamic-badges-action* + a secret gist + shields.io approach
for the coverage badge.  That requires:

1. A personal access token with gist scope (`GIST_SECRET`).
2. A manually-created gist.
3. A custom "Extract coverage percent" + "Determine badge color" bash
   step before the badge update.

I judged it too much moving parts — any of the three pieces going stale
(PAT expiry, gist deleted, shields.io cache) leaves a broken badge.
Codecov's Actions-OIDC flow promised *zero secrets* for public repos.

### Change
Replaced the badge pipeline with:

- `codecov/codecov-action@57e3a13` (v6.0.0) — uploads `coverage.xml`
  with `use_oidc: true`.
- `codecov/test-results-action@0fa95f0` (v1.2.1) — uploads JUnit XML
  for flaky-test analytics.
- Removed `schneegans/dynamic-badges-action` + the two helper bash
  steps.
- README badge URL → `https://codecov.io/gh/rodenj1/sp-rtk-base-relay/branch/main/graph/badge.svg`
  (unauthenticated).
- Added job-scoped `permissions: { contents: read, id-token: write }` on
  `test` (required for OIDC token minting).
- `docs/ci-setup.md` rewritten for the OIDC flow.

**Result:** workflow ran green but **the badge showed "unknown"** and
`app.codecov.io/gh/rodenj1/sp-rtk-base-relay` returned 404.  At the time
I thought "Codecov just needs the repo onboarded, no code change needed"
and moved on to clean up a deprecation warning.

---

## 5 · Consolidate Test-Results Upload (`59b904b`)

**Symptom** — `codecov/test-results-action` surfaced its own deprecation
notice: *"Use codecov-action with report_type: test_results instead."*

### Change
Deleted the `codecov/test-results-action` step.  Replaced with a **second
invocation** of `codecov/codecov-action@v6`, this time with
`report_type: test_results` and `files: ./pytest-junit.xml`.

That single workflow now calls `codecov-action` twice: once for coverage,
once for test results.

**Result:** Run **24759889898** green, no more annotations.  Badge still
broken.  This is where the rabbit hole began.

---

## 6 · Diagnosing the Broken Badge (no commit — log investigation)

The dashboard at `https://app.codecov.io/gh/rodenj1/sp-rtk-base-relay`
was returning **404 Not Found** in the browser.  My first theory was
"the badge just needs a push to `main` to render for the first time."
That was wrong.

### Smoking gun
`gh run view <run-id> --log` on the most recent successful CI run
revealed:

```
info -- Found 1 coverage files to report
info -- > /home/runner/.../coverage.xml
warning -- Response status code was 500. --- {"retry": 0}
warning -- Request failed. Retrying --- {"retry": 0}
warning -- Response status code was 500. --- {"retry": 1}
warning -- Request failed. Retrying --- {"retry": 1}
warning -- Response status code was 500. --- {"retry": 2}
warning -- Request failed. Retrying --- {"retry": 2}
Exception: Request failed after too many retries.
  URL: https://ingest.codecov.io/upload/github/rodenj1::::sp-rtk-base-relay/upload-coverage
==> Failed to run upload-coverage
```

Three separate retries, each a 500, then the action exited non-zero —
but because we had `fail_ci_if_error: false` the workflow still went
green.  The action was **silently failing on every single run**.

### Onboarding attempt
Per Codecov docs the first fix is to confirm the repo is linked at
`app.codecov.io`.  Initial look: `sp-rtk-base-relay` was **missing** from
the repo list.  Fixed by:

1. Clicking **Resync** on the Codecov org page.
2. The repo appeared with a padlock icon 🔒 — Codecov recognising it as
   private.
3. Clicking **Configure** to enable it.

Onboarded, but a fresh run (`086ac83`, empty commit) still produced the
same HTTP 500 cascade.

### Actual root cause
**Codecov's OIDC tokenless upload is public-repo-only.**  Buried in the
action's README — not mentioned on the setup wizard that you reach from
app.codecov.io.  A private repo that attempts `use_oidc: true` gets its
OIDC token minted successfully by GitHub, accepted by Codecov's gateway,
and then rejected by the storage layer with a 500.  No clear 401/403 —
just a 500 + retries.

`gh repo view --json isPrivate` → `{"isPrivate": true}`.  The repo was
renamed from `sp-base-relay` in preparation for a public release but
hadn't been flipped to public yet.

---

## 7 · Switch to Token Auth (`f1926f6`)

**Goal** — get uploads working on the private repo without changing
visibility.

### Secret setup (out-of-band)
From the Codecov setup page (Settings → Coverage tab after
onboarding), copied the upload token (a UUID):

```bash
echo "<upload-token>" | gh secret set CODECOV_TOKEN
```

### Workflow diff

- Removed `id-token: write` from the `test` job's `permissions:` block
  (OIDC no longer used).
- Updated the top-of-file comment to reflect token auth.
- Both Codecov invocations:
  - `use_oidc: true` → removed.
  - `token: ${{ secrets.CODECOV_TOKEN }}` → added.

### Docs rewrite
`docs/ci-setup.md` (the operator-facing how-to) rewritten end-to-end:

1. How to link the repo at app.codecov.io (Resync + GitHub App perms).
2. How to copy the upload token and store it as `CODECOV_TOKEN`.
3. How to grab the **separate read-only badge token** from
   *Settings → Badges & Graphs* (different from the upload token).
4. An optional `codecov.yml` starter config (patch-coverage target,
   1 % threshold tolerance, PR-comment layout).
5. How to swap back to OIDC if the repo ever goes public.

### Verification
Run **24760379477** on `f1926f6` — the golden log line:

```
info -- Your upload is now processing. When finished, results will be
available at:
https://app.codecov.io/github/rodenj1/sp-rtk-base-relay/commit/f1926f6...
info -- Process Upload complete
```

Zero retries.  Upload → processing in ~300 ms.

---

## 8 · README Badge Token (`632b1cb`)

**Last mile** — on a private repo, even the badge SVG requires
authentication.  Without the token Codecov returns 404 on the badge URL.

### Two-token model (important distinction)

| Token        | Format                                 | Where used                        | Commit-safe? |
|--------------|----------------------------------------|-----------------------------------|--------------|
| Upload token | UUID (36 chars, `d0609ae1-...`)        | `gh secret set CODECOV_TOKEN`     | **No**       |
| Badge token  | Short alphanumeric (10 chars, `T5XTVO92KQ`) | README badge URL `?token=...` | **Yes**      |

The badge token grants read-only access to the single-branch SVG.  It
can't be used to upload reports or read source, so committing it is
safe.

### Change
`README.md` line 6:

```diff
-[![codecov](https://codecov.io/gh/rodenj1/sp-rtk-base-relay/branch/main/graph/badge.svg)](https://codecov.io/gh/rodenj1/sp-rtk-base-relay)
+[![codecov](https://codecov.io/gh/rodenj1/sp-rtk-base-relay/branch/main/graph/badge.svg?token=T5XTVO92KQ)](https://codecov.io/gh/rodenj1/sp-rtk-base-relay)
```

`memory-bank/activeContext.md` Codecov section rewritten to document
all three iterations (OIDC → consolidation → token) and the
root-cause diagnosis, with the verification log line embedded.

---

## Design Decisions — Cross-Cutting

### Why Codecov instead of the gist/shields.io dance?
| Criterion        | Gist + shields.io           | Codecov                  |
|------------------|-----------------------------|--------------------------|
| Moving parts     | 3 (PAT + gist + shields cache) | 1 (upload token secret)  |
| PR coverage diff | No                          | Yes (PR comments + checks) |
| Test analytics   | No                          | Yes (flaky-test detection) |
| Historical trend | No (badge only)             | Yes (commit-by-commit graph) |
| Cost             | Free                        | Free for open-source / up to 5 users |

The ~30-line gist approach gave us a number; Codecov gives us the
number + PR comments + flaky-test detection + trend charts, all for the
same authentication effort once we knew about the private-repo token
requirement.

### Why SHA-pin every action?
Supply-chain defence.  A compromised tag (the attacker force-pushes `v6`)
still can't inject code into our CI if we're pinned to a SHA.
Dependabot's `github-actions` ecosystem understands SHA-pinned entries
and opens PRs with the new SHA when upstream publishes a new release.

### Why run codecov-action twice instead of using test-results-action?
`codecov/test-results-action` was formally deprecated mid-2024.  The
official replacement is `codecov-action` with `report_type: test_results`.
Running the action twice is a tiny workflow cost and keeps us on
Codecov's supported integration path.

### Why `fail_ci_if_error: false`?
We never want a Codecov outage to turn our CI red — coverage reporting
is a nice-to-have, not a correctness gate.  The trade-off is that
silent failures (like our HTTP 500 loop) can go unnoticed; that's what
the once-per-week badge sanity check is for.

### Why only upload from Python 3.12?
Uploading from every matrix leg would give Codecov four identical reports
to reconcile — noisy dashboard, no extra signal.  3.12 is the "default"
Python (the lint job uses it too), so it's a natural choice.

---

## Known Issues / Follow-ups

- **Ruff legacy-baseline `[tool.ruff.lint.ignore]` list** — `d411db9`
  auto-fixed what it could; the remaining ~20 rule codes are ignored
  as a baseline.  They should be addressed one-by-one in follow-up PRs,
  removing each ignore as the corresponding rule is cleaned up.
- **`CODECOV_TOKEN` rotation** — the upload token was visible in chat
  history during setup.  Low urgency (private repo, only affects
  Codecov for this repo) but good hygiene to rotate via Codecov →
  Settings → Coverage → Regenerate.
- **Bluetooth strict-type overrides** — the `bluetooth_manager` /
  `bluetooth_input` mypy overrides are workarounds for dbus-fast's
  runtime-`__getattr__` API.  Upstream has a `py.typed` marker on
  roadmap; can revisit when that lands.

---

## Final Workflow Overview (state as of `632b1cb`)

```yaml
name: CI
on: { push: main, pull_request: main, workflow_dispatch }
concurrency: { group: ci-<ref>, cancel-in-progress: true }
permissions: { contents: read }

jobs:
  lint:     # py3.12   ruff + mypy + pyright + pylint (advisory)
  test:     # py3.10/3.11/3.12/3.13 matrix
            # pytest + coverage + junit
            # artifact uploads (coverage + junit per python)
            # codecov upload ×2 (coverage + test-results, 3.12 only, token-auth)
  build:    # py3.12   uv build → sdist + wheel artifact
```

**Runtime**: ~4 minutes end-to-end on GitHub-hosted `ubuntu-latest`.
**Cost**: free tier (public or private, within the 2 000-min/month
individual allowance).

Operator documentation: see `docs/ci-setup.md`.
Active state: see `memory-bank/activeContext.md` (Codecov section).
