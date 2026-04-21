# Active Context

## Current Work Focus

**Primary Objective**: SP-RTK-Base-Relay v2.1 COMPLETE + project renamed → Next: sp-base integration (April 2026)

**Status**: v2.1 Phases 0–5 COMPLETE. Project renamed `sp-base-relay` → `sp-rtk-base-relay` on `main` (April 21, 2026, commit `f9c2a35`). Phase 6 (cleanup) pending. sp-base integration next.

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
1. **Phase 6**: sp-rtk-base-relay cleanup (remove probe_gps.py, revert pyubx2, README, integration tests)

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
