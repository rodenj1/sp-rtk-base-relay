# Active Context

## Current Work Focus

**Primary Objective**: SP-RTK-Base-Relay v2.1 COMPLETE + project renamed + CI added → Next: sp-base integration (April 2026)

**Status**: v2.1 Phases 0–5 COMPLETE. Project renamed `sp-base-relay` → `sp-rtk-base-relay` on `main` (April 21, 2026, commit `f9c2a35`). GitHub Actions CI workflow added and **GREEN** on `main` (April 21, 2026, run 24759164665) — lint + matrix unit tests on Python 3.10/3.11/3.12/3.13 + build all passing. Phase 6 (cleanup) pending. sp-base integration next.

### CI Added (April 21, 2026)

`.github/workflows/ci.yml` — 3 jobs:
- **lint** (py3.12): ruff check + ruff format --check + mypy + pyright (blocking); pylint (advisory).
- **test** (matrix: 3.10/3.11/3.12/3.13, `fail-fast: false`): `uv sync --locked --all-extras` → `uv run pytest` with XML/HTML/JUnit coverage; uploads artifacts. Coverage badge updates on push to main via Gist + shields.io (gated on `GIST_SECRET`).
- **build** (py3.12): `uv build` → dist artifact.

Triggers: push to main, PRs to main, manual dispatch. `concurrency.cancel-in-progress: true`. All actions pinned to full SHAs.

Supporting changes (commit `d411db9`):
- `pyproject.toml`: added py3.13 classifier, removed `black`, added `ruff>=0.6.0` + `[tool.ruff]` config (line-length 88, py310 target, E/W/F/I/B/UP/N/SIM/RUF rule sets, legacy baseline `ignore` list).
- Auto-applied `ruff check --fix` + `ruff format` across 74 files; 1,117 tests still pass, coverage 89.35%.
- `docs/ci-setup.md` — workflow overview + one-time Gist/PAT setup for coverage badge.
- `README.md` — CI + coverage + ruff badges added; title updated to `SP-RTK-Base-Relay`.

Follow-up fix (commit `d6fb14f`) — resolved pre-existing mypy/pyright strict errors surfaced by the new CI:
- Added mypy module override for `bluetooth_manager` + `bluetooth_input` (dbus-fast `ProxyInterface` uses runtime `__getattr__` for `call_*` methods — mypy cannot follow; pyright unaffected).
- Cast `ProxyInterface` → `Any` at two pyright errors in `bluetooth_manager.py` (`call_set`/`call_get`) with explanatory comments.
- Annotated `HeartbeatMonitor.socket` attribute so mypy no longer marks defensive None-check as unreachable.
- Simplified redundant poison-pill check in `TcpServerDestination._broadcast_loop`.
- Fixed `repr` of non-utf8 auth response bytes (`{response!r}`).
- Added `dbus_fast` to mypy `ignore_missing_imports`.
- Misc pyright-strict annotation clean-ups in `config.py`, `logger.py`, `serial_input.py`, `tcp_input.py`, `rtcm_client.py`.
- All local checks clean: ruff + ruff format + mypy strict + pyright strict; 1,117 tests pass at 89.34% coverage. CI green.

Node.js 24 upgrade (commit `bbb9e98`) — addressed GitHub's Node.js 20 deprecation warnings surfaced on the first green run:
- `actions/checkout` v5.0.0 → **v6.0.2** (SHA `de0fac2e…`).
- `actions/upload-artifact` v4.6.2 → **v6.0.0** (SHA `b7c566a7…`) — v6 is the first release that defaults to Node 24 and requires Actions runner ≥ 2.327.1.
- `schneegans/dynamic-badges-action` v1.7.0 → **v1.8.0** (SHA `0e50b8ba…`) — (subsequently removed when switching to Codecov).
- `astral-sh/setup-uv@v8.1.0` already runs on Node 24; unchanged.
- Verified clean via run **24759388902** — success with no deprecation warnings.

Coverage badge migrated to **Codecov**, iterated through three configurations before settling on token auth:

1. **Initial (OIDC)** — commit `c4182cd` switched to `codecov/codecov-action@v6.0.0` with `use_oidc: true` + separate `codecov/test-results-action@v1.2.1`.  Workflow ran green but badge showed "unknown" and `app.codecov.io/gh/rodenj1/sp-rtk-base-relay` returned 404.
2. **Consolidation** — commit `59b904b` cleared the `codecov/test-results-action` deprecation annotation by calling `codecov-action` twice instead (second invocation with `report_type: test_results`).  Run `24759889898` green; badge still broken.
3. **Final (token auth)** — commit `f1926f6`.  Root cause: `sp-rtk-base-relay` is a **private repo**, and Codecov's OIDC tokenless upload is public-repo-only.  Every OIDC upload was being rejected with HTTP 500 by `ingest.codecov.io` (visible only via `gh run view --log` — the action itself was silent because `fail_ci_if_error: false`).  Run `24760379477` on `f1926f6` shows the fix working:
   ```
   info -- Your upload is now processing. When finished, results will be
   available at: https://app.codecov.io/github/rodenj1/sp-rtk-base-relay/
                 commit/f1926f6f137b440089f9c9beaf0cd295f0f666ed
   info -- Process Upload complete
   ```

Final configuration:
- `codecov/codecov-action@v6.0.0` (SHA `57e3a136…`) invoked twice (coverage + test-results), both with `token: ${{ secrets.CODECOV_TOKEN }}`.
- `CODECOV_TOKEN` repository secret set via `gh secret set CODECOV_TOKEN` (upload token from app.codecov.io onboarding page).  Note: this UUID was exposed in chat history during setup and should be **rotated via Codecov → Settings → Coverage** when convenient.
- `id-token: write` permission removed from the `test` job (no longer needed).
- README badge uses the separate read-only **badge token** `T5XTVO92KQ` as `?token=...` query param — safe to commit, grants read-only access to the badge SVG for this single branch only.
- `docs/ci-setup.md` fully rewritten to document the private-repo token flow (upload token vs badge token), with a short section on how to swap back to OIDC if the repo ever goes public.

**Codecov setup complete.** Badge renders live coverage percentage from latest successful upload; dashboard at <https://app.codecov.io/github/rodenj1/sp-rtk-base-relay> shows commit-by-commit trend, flaky-test analytics, and PR coverage comments.

**Previous**: v2.1 merged to `main` via PR #5 → PR #6 (`origin/main` at `313f951`). Prior v2.0 work at commit 8f4f79a.
**Branch**: `main` (all v2.1 work merged; working directly on main going forward)

### Rename Summary (April 21, 2026)

The project was renamed from `sp-base-relay` → `sp-rtk-base-relay` to more accurately reflect its purpose (providing RTCM corrections for RTK base stations) in preparation for public release. Commit `f9c2a35` on `main`.

Changes:
- Python package directory: `src/sp_base_relay/` → `src/sp_rtk_base_relay/` (`git mv`, history preserved)
- Console script: `sp-base-relay` → `sp-rtk-base-relay`
- systemd unit: `tools/systemd/sp-base-relay.service` → `sp-rtk-base-relay.service`
- `pyproject.toml`: `name`, `[project.scripts]`, `[project.urls]`, pytest `--cov=` path updated
- Global string replacement across 82 tracked text files (src/, tests/, docs/, memory-bank/, tools/, templates/, examples/, README, configs)
- `uv.lock` regenerated for `sp-rtk-base-relay==2.1.0`
- GitHub repo renamed via `gh repo rename`; `origin` remote updated to `https://github.com/rodenj1/sp-rtk-base-relay.git`
- All **1,117** unit tests pass, coverage **89.49%**
- Deployment note: existing installations must `sudo systemctl disable --now sp-base-relay && sudo systemctl daemon-reload`, then reinstall via `tools/install.sh` to pick up the renamed `sp-rtk-base-relay.service`.


### v2.1 Implementation Summary

v2.1 enhances sp-rtk-base-relay to be usable as a **Python dependency** by the sp-base web UI project. The core purpose remains unchanged: RTCM relay.

Architecture plan: `docs/v2.1-architecture-plan.md`
UI integration plan: `docs/ublox_gps_webui_planning.md` (historical — plans now in sp-base memory bank)
API spec: `docs/relay-engine-api-spec.md`

### v2.1 Development Phases

| Phase | Deliverable | Status | Tests |
|---|---|---|---|
| P0 | Feature branch + version bump 2.1.0 | ✅ COMPLETE | — |
| P1 | Event Bus system (`events.py`) | ✅ COMPLETE | 31 tests |
| P2 | Typed status snapshots (`status.py`) | ✅ COMPLETE | 16 tests |
| P3 | Dynamic destination management (`broadcast_hub.py`) | ✅ COMPLETE | 67 tests |
| P4 | RelayEngine facade (`engine.py`) + `__init__.py` exports | ✅ COMPLETE | 27 tests |
| P5 | Documentation & API spec | ✅ COMPLETE | — |
| P6 | Cleanup (remove probe tools, docs polish) | 📋 TODO | — |

**Total unit tests**: 1,106 passing

### Next Steps
1. **(Optional) Rotate `CODECOV_TOKEN`** via Codecov → Settings → Coverage — the UUID was exposed in chat history during setup. Not urgent (private repo, Codecov only), but good hygiene.
2. **Phase 6**: sp-rtk-base-relay cleanup (remove probe_gps.py, revert pyubx2, README, integration tests)
3. **Lint baseline cleanup**: address items in `[tool.ruff.lint.ignore]` legacy baseline in follow-up PRs, then remove the ignores one-by-one

---

## Important Patterns and Preferences

### v2.1 Implemented Patterns
- **Facade Pattern**: RelayEngine wraps BroadcastHub + events + status
- **Observer/Pub-Sub Pattern**: EventBus with subscriber queues + ring buffer
- **Copy-on-Read Pattern**: Thread-safe destination list in broadcast loop
- **Builder Pattern**: `build_relay_status()` constructs frozen snapshots

### Existing Patterns (Unchanged)
- Strategy Pattern (InputSource, BaseDestination ABCs)
- Registry Pattern (DestinationFactory)
- Fan-Out Pattern (BroadcastHub → N queues)
- A+ Pattern (Threading + asyncio for TCP server)

### Code Quality Standards
- Python 3.10+ with type hints (modern syntax: `dict`, `list`, `X | None`)
- >90% unit test coverage using Pytest
- Zero pylance/pyright issues in strict mode
- PEP8 standards
- UV package management
