# Active Context

## Current Work Focus

**Primary Objective**: SP-RTK-Base-Relay v2.1 COMPLETE + project renamed + CI added → Next: sp-base integration (April 2026)

**Status**: v2.1 Phases 0–5 COMPLETE. Project renamed `sp-base-relay` → `sp-rtk-base-relay` on `main` (April 21, 2026, commit `f9c2a35`). GitHub Actions CI workflow added (April 21, 2026) — lint + matrix unit tests on Python 3.10/3.11/3.12/3.13 + build. Phase 6 (cleanup) pending. sp-base integration next.

### CI Added (April 21, 2026)

`.github/workflows/ci.yml` — 3 jobs:
- **lint** (py3.12): ruff check + ruff format --check + mypy + pyright (blocking); pylint (advisory).
- **test** (matrix: 3.10/3.11/3.12/3.13, `fail-fast: false`): `uv sync --locked --all-extras` → `uv run pytest` with XML/HTML/JUnit coverage; uploads artifacts. Coverage badge updates on push to main via Gist + shields.io (gated on `GIST_SECRET`).
- **build** (py3.12): `uv build` → dist artifact.

Triggers: push to main, PRs to main, manual dispatch. `concurrency.cancel-in-progress: true`. All actions pinned to full SHAs.

Supporting changes:
- `pyproject.toml`: added py3.13 classifier, removed `black`, added `ruff>=0.6.0` + `[tool.ruff]` config (line-length 88, py310 target, E/W/F/I/B/UP/N/SIM/RUF rule sets, legacy baseline `ignore` list).
- Auto-applied `ruff check --fix` + `ruff format` across 74 files; 1,117 tests still pass, coverage 89.35%.
- `docs/ci-setup.md` — workflow overview + one-time Gist/PAT setup for coverage badge.
- `README.md` — CI + coverage + ruff badges added; title updated to `SP-RTK-Base-Relay`.

One-time manual setup required post-merge: create public Gist, create PAT with `gist` scope, add `GIST_SECRET` + `COVERAGE_GIST_ID` repo secrets, replace `REPLACE_WITH_GIST_ID` in README. See `docs/ci-setup.md`.

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
1. **CI post-merge**: create Gist + PAT, add repo secrets, update README gist ID placeholder (see `docs/ci-setup.md`)
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
