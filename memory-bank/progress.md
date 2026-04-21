# Progress

## Current Status — v2.1 Complete + Project Renamed (April 21, 2026)

**v1.x**: All phases complete (production-running)
**v2.0**: All phases complete (956 tests, 88.46% coverage, commit 8f4f79a)
**v2.1**: Phases 0–5 COMPLETE. Merged to `main` via PR #5 → PR #6. Ready for cleanup; sp-base consuming RelayEngine API.
**Rename**: Project renamed `sp-base-relay` → `sp-rtk-base-relay` on `main` (commit `f9c2a35`, April 21, 2026) in preparation for public release.
**Version**: 2.1.0
**Tests**: 1,117 unit tests passing, 89.49% coverage (post-rename verification)
**Branch**: `main` (v2.1 merged; working directly on main)
**GitHub**: `https://github.com/rodenj1/sp-rtk-base-relay` (renamed via `gh repo rename`; GitHub auto-redirects old URL)

---

## Project Rename — COMPLETE ✅ (April 21, 2026, commit `f9c2a35`)

**Motivation**: Preparing the project to go public. The new name `sp-rtk-base-relay` more accurately reflects the project's purpose: providing RTCM corrections for RTK base stations.

**Scope of changes** (all on `main` in a single commit):
- **Python package**: `src/sp_base_relay/` → `src/sp_rtk_base_relay/` via `git mv` (rename history preserved)
- **Console script entry point**: `sp-base-relay` → `sp-rtk-base-relay` (`[project.scripts]` in `pyproject.toml`)
- **pyproject.toml**: `name`, `[project.scripts]`, `[project.urls]` (Homepage/Documentation/Repository/Issues), pytest `--cov=src/sp_rtk_base_relay`
- **systemd unit**: `tools/systemd/sp-base-relay.service` → `tools/systemd/sp-rtk-base-relay.service` (install/uninstall scripts updated)
- **Global string replacement** across 82 tracked text files (`sp_base_relay` → `sp_rtk_base_relay`, `sp-base-relay` → `sp-rtk-base-relay`) spanning:
  - `src/`, `tests/unit/`, `tests/integration/`, `tests/manual/`, `tests/fixtures/`
  - `docs/`, `memory-bank/`, `examples/`, `templates/`, `tools/`
  - `README.md`, `configuration-reference.md`, `config.example.yaml`, `config.bluetooth*.yaml`
- **`uv.lock`** regenerated (`uv lock` → `sp-rtk-base-relay==2.1.0`)
- **GitHub repo** renamed: `rodenj1/sp-base-relay` → `rodenj1/sp-rtk-base-relay` via `gh repo rename`
- **Local git remote** updated: `origin` → `https://github.com/rodenj1/sp-rtk-base-relay.git`

**Verification**:
- `grep` for `sp[-_]base[-_]relay` in tracked files (excluding `uv.lock`): **zero matches**
- `uv sync`: `sp-rtk-base-relay==2.1.0` installed cleanly
- `uv run pytest`: **1,117 passed**, 89.49% coverage
- `git fetch origin`: succeeds against new URL

**Deployment note for existing installations**:
Existing hosts running the old systemd service must:
```bash
sudo systemctl disable --now sp-base-relay
sudo systemctl daemon-reload
```
...then reinstall via `tools/install.sh`, which will set up the renamed `sp-rtk-base-relay.service` unit.

**Items intentionally not changed**:
- Version stayed at `2.1.0` (no bump — rename is infrastructure, not a semantic release)
- Commit message history (refers to old name, which is historically accurate)
- Runtime/generated log files (`*.log`) — gitignored artifacts

---


Architecture plans:
- v2.0: `docs/v2-architecture-plan.md`
- v2.1: `docs/v2.1-architecture-plan.md`
- UI integration: `docs/ublox_gps_webui_planning.md`
- API spec: `docs/relay-engine-api-spec.md`

---

## v2.1 Development — Embeddable Relay Engine

### Purpose
Enhance sp-rtk-base-relay so it can be used as a Python dependency by the sp-base web UI project. Core relay purpose unchanged.

### Design Decisions (DR-8 through DR-17)
- DR-8: In-process integration (UI imports sp-rtk-base-relay directly)
- DR-9: Programmatic config (no YAML required for embedded use)
- DR-10: Polling + Event Bus (snapshot + push events)
- DR-11: Hot add/remove destinations (zero interruption to other dests)
- DR-12: Per-destination start/stop (independent control)
- DR-13: RelayEngine facade (single API class for external consumers)
- DR-14: Full backward compatibility (CLI, YAML, Prometheus unchanged)
- DR-15: Device info/config lives in sp-base, NOT sp-rtk-base-relay
- DR-16: Two-port architecture support (separate UBX + RTCM ports = no relay interruption)
- DR-17: Serial port handoff for shared-port configs (stop relay → UBX session → restart)

### Phase 0: Feature Branch + Version Bump — COMPLETE ✅
- Created `feature/v2.1-relay-engine` branch
- Bumped version to 2.1.0 in `pyproject.toml` and `__init__.py`

### Phase 1: Event Bus System — COMPLETE ✅
**New**: `src/sp_rtk_base_relay/core/events.py`, `tests/unit/test_events.py`
- [x] `RelayEvent` frozen dataclass (event_type, message, timestamp, payload)
- [x] `EventSubscription` class (queue-based, iterable, closeable)
- [x] `EventBus` class (thread-safe emit, subscribe, unsubscribe, ring buffer)
- [x] Event type string constants (hub.*, input.*, destination.*, engine.*)
- [x] 31 tests passing

### Phase 2: Typed Status Snapshots — COMPLETE ✅
**New**: `src/sp_rtk_base_relay/core/status.py`, `tests/unit/test_status.py`
- [x] `DestinationStatus` frozen dataclass
- [x] `InputStatus` frozen dataclass
- [x] `RelayStatus` frozen dataclass
- [x] `build_relay_status()` builder function
- [x] 16 tests passing

### Phase 3: Dynamic Destination Management — COMPLETE ✅
**Modified**: `broadcast_hub.py`
- [x] Thread-safe destination list (lock-protected, copy-on-read)
- [x] `BroadcastHub.add_destination()` — hot-add while running
- [x] `BroadcastHub.remove_destination()` — hot-remove while running
- [x] `BroadcastHub.stop_destination()` / `start_destination()` — per-dest control
- [x] `BroadcastHub.get_destination()` / `get_destination_names()`
- [x] Event emissions in BroadcastHub (optional event_bus param)
- [x] Recalculate `_any_needs_parsing` on add/remove
- [x] Allow empty destinations list
- [x] 67 tests passing (16 new + 51 existing)

### Phase 4: RelayEngine Facade — COMPLETE ✅
**New**: `src/sp_rtk_base_relay/engine.py`, `tests/unit/test_engine.py`
**Modified**: `__init__.py`
- [x] `RelayEngine` class with full lifecycle API (start/stop/is_running)
- [x] Destination management (add, remove, start, stop, get_destination_names)
- [x] Status & events (get_status, subscribe_events, get_recent_events)
- [x] Updated `__init__.py` exports (RelayEngine, EventBus, RelayEvent, RelayStatus, etc.)
- [x] 27 tests passing

### Phase 5: Documentation & API Spec — COMPLETE ✅
- [x] Memory bank updates
- [x] Relay Engine API technical spec (`docs/relay-engine-api-spec.md`)
- [x] Hardware probe: ZED-F9P on /dev/ttyUSB0 @ 57600 baud confirmed
- [x] Two-port architecture validated (UBX on FTDI UART, RTCM on Bluetooth)
- [x] Architecture decision: device info/config belongs in sp-base

### Phase 6: sp-rtk-base-relay Cleanup — TODO 📋
- [ ] Remove `tools/probe_gps.py` (dev tool, not needed in sp-rtk-base-relay)
- [ ] Revert `pyubx2` from dev dependencies (belongs in sp-base)
- [ ] Integration tests: full RelayEngine lifecycle with real TCP sockets
- [ ] README.md: add "Embedded Usage" section
- [ ] configuration-reference.md: add programmatic config section
- [ ] Final test pass and coverage check

---

## v2.1 Module Map (Current)

```
src/sp_rtk_base_relay/
├── __init__.py              # Updated: exports RelayEngine, EventBus, RelayEvent, RelayStatus
├── engine.py                # NEW — RelayEngine facade API
├── main.py                  # Unchanged (Phase 4 main.py refactor deferred)
├── config.py                # Unchanged
├── exceptions.py            # Unchanged
├── logger.py                # Unchanged
├── metrics.py               # Unchanged
├── rtcm_decoder.py          # Unchanged
└── core/
    ├── events.py            # NEW — EventBus, RelayEvent, EventSubscription
    ├── status.py            # NEW — RelayStatus, DestinationStatus, InputStatus
    ├── broadcast_hub.py     # MODIFIED — dynamic dest mgmt, event emissions, dest lock
    ├── message_filter.py    # Unchanged
    ├── rtcm_client.py       # Unchanged
    ├── connection_states.py # Unchanged
    ├── data_pipeline.py     # Deprecated (unchanged)
    ├── bluetooth_manager.py # Unchanged
    ├── input_sources/       # Unchanged
    └── destinations/        # Unchanged
```

---

## v2.0 Development Progress (COMPLETE)

### Phase 1: Foundation — COMPLETE ✅
### Phase 2A: SurePathDestination — COMPLETE ✅
### Phase 2B: main.py v2 Refactor — COMPLETE ✅
### Phase 3A: NtripDestination — COMPLETE ✅
### Phase 3B: Mock NTRIP Caster Testing — COMPLETE ✅
### Phase 4: Metrics v2 — COMPLETE ✅
### Phase 5: TCP Server Destination — COMPLETE ✅
### Phase 6: Integration & Polish — COMPLETE ✅

**Total v2 tests**: 956 (at v2.0 completion)

---

## v1.x Completed Work (October 2025 — February 2026)

All v1.x phases complete. See previous progress entries.

---

## Known Issues / Risks

- ⚠️ v2.0 is a breaking change from v1.x (config format, metrics names)
- ⚠️ Phase 10 (PyPI packaging) still not started from v1.x
- ⚠️ main.py not yet refactored to use RelayEngine internally (deferred)
- ⚠️ BaseDestination not yet wired with event_bus param (deferred — lower priority)
- ✅ v1.x Sure-Path connection is production-stable
- ✅ All 1,117 unit tests passing (post-rename, 89.49% coverage)
- ✅ Project renamed to `sp-rtk-base-relay` (April 21, 2026, commit `f9c2a35`)
- ✅ GitHub repo renamed and `origin` remote updated
- ✅ `grep` for `sp[-_]base[-_]relay` in tracked files (excluding `uv.lock`): **zero matches**

- ✅ v2.1 design decisions documented and approved
- ✅ Backward compatibility maintained (all existing tests pass unmodified)
- ✅ API technical spec complete for UI integration
- ✅ ZED-F9P hardware validated with pyubx2
