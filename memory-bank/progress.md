# Progress

## Current Status — v2.1 Phases 0–5 COMPLETE (April 10, 2026)

**v1.x**: All phases complete (production-running)
**v2.0**: All phases complete (956 tests, 88.46% coverage, commit 8f4f79a)
**v2.1**: Phases 0–5 COMPLETE. Ready for cleanup. sp-base consuming RelayEngine API.
**Version**: 2.1.0
**Tests**: 1,106 unit tests passing
**Branch**: `feature/v2.1-relay-engine` (from `feature/v2-multi-destination`)

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
- ✅ All 1,106 unit tests passing
- ✅ v2.1 design decisions documented and approved
- ✅ Backward compatibility maintained (all existing tests pass unmodified)
- ✅ API technical spec complete for UI integration
- ✅ ZED-F9P hardware validated with pyubx2
