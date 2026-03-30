# Active Context

## Current Work Focus

**Primary Objective**: SP-Base-Relay v2.1 — Embeddable Relay Engine (March 2026)

**Status**: Phases 0–4 COMPLETE. Phase 5 (docs/memory bank) in progress.

**Previous**: v2.0 Phase 6 COMPLETE. All v2.0 features merged (commit 8f4f79a).
**Branch**: `feature/v2.1-relay-engine` (branched from `feature/v2-multi-destination`)

### v2.1 Implementation Summary

v2.1 enhances sp-base-relay to be usable as a **Python dependency** by the planned GPS Base Station Web UI project (gps-webui). The core purpose remains unchanged: RTCM relay.

Architecture plan: `docs/v2.1-architecture-plan.md`
UI integration plan: `docs/ublox_gps_webui_planning.md`

### v2.1 Development Phases

| Phase | Deliverable | Status | Tests |
|---|---|---|---|
| P0 | Feature branch + version bump 2.1.0 | ✅ COMPLETE | — |
| P1 | Event Bus system (`events.py`) | ✅ COMPLETE | 31 tests |
| P2 | Typed status snapshots (`status.py`) | ✅ COMPLETE | 16 tests |
| P3 | Dynamic destination management (`broadcast_hub.py`) | ✅ COMPLETE | 67 tests (16 new + 51 existing) |
| P4 | RelayEngine facade (`engine.py`) + `__init__.py` exports | ✅ COMPLETE | 27 tests |
| P5 | Integration tests & documentation | 🔄 IN PROGRESS | — |

**Total unit tests**: 1,106 passing

### v2.1 Commits (on feature/v2.1-relay-engine)
1. Phase 0: Version bump to 2.1.0
2. Phase 1: Event Bus system
3. Phase 2: Typed status snapshots
4. Phase 3: Dynamic destination management in BroadcastHub
5. Phase 4: RelayEngine facade API

### New Files Created (v2.1)
- `src/sp_base_relay/engine.py` — RelayEngine facade
- `src/sp_base_relay/core/events.py` — EventBus, RelayEvent, EventSubscription
- `src/sp_base_relay/core/status.py` — RelayStatus, DestinationStatus, InputStatus
- `tests/unit/test_engine.py` — 27 tests
- `tests/unit/test_events.py` — 31 tests
- `tests/unit/test_status.py` — 16 tests

### Modified Files (v2.1)
- `src/sp_base_relay/__init__.py` — exports RelayEngine, EventBus, RelayEvent, RelayStatus, etc.
- `src/sp_base_relay/core/broadcast_hub.py` — dynamic dest mgmt, event emissions, threading.Lock
- `pyproject.toml` — version 2.1.0

---

## v2.1 Design Decisions (DR-8 through DR-14)

| ID | Decision | Rationale |
|---|---|---|
| DR-8 | In-process integration model | UI imports sp-base-relay directly; no IPC/HTTP needed |
| DR-9 | Programmatic config | UI builds Config/DestinationConfig objects in Python |
| DR-10 | Polling + Event Bus for status | Snapshot polling + push events for discrete changes |
| DR-11 | Hot add/remove destinations | Without stopping the hub or other destinations |
| DR-12 | Per-destination start/stop | Individual destinations controlled independently |
| DR-13 | RelayEngine facade | Single high-level API class for external consumers |
| DR-14 | Backward compatibility | CLI, YAML, Prometheus all unchanged |

---

## GPS Base Station Web UI Project (gps-webui)

### Key Architecture Decisions
- sp-base-relay is a **dependency** of gps-webui, not renamed or restructured
- gps-webui owns u-blox device configuration (via PyUBX2), NOT sp-base-relay
- Serial port handoff: relay owns port when running, PyUBX2 owns it when stopped
- FastAPI + NiceGUI for web framework
- In-process integration — gps-webui imports RelayEngine directly

### Dependency Graph
```
gps-webui → sp-base-relay (relay engine)
gps-webui → pyubx2 (u-blox device config)
gps-webui → pyubxutils (backup/restore)
gps-webui → fastapi + nicegui (web UI)
```

---

## Previous v2.0 Work (Complete)

All v2.0 phases complete (Phases 1-6). 956 tests passing at v2.0 completion.
See `docs/v2-architecture-plan.md` for v2.0 details.

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
