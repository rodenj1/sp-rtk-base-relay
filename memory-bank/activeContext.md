# Active Context

## Current Work Focus

**Primary Objective**: SP-Base-Relay v2.1 — Embeddable Relay Engine (March 2026)

**Status**: Planning COMPLETE. Ready to begin implementation.

**Previous**: v2.0 Phase 6 COMPLETE. All v2.0 features merged (commit 8f4f79a).
**Next**: v2.1 development on new feature branch.

### v2.1 Planning Summary

v2.1 enhances sp-base-relay to be usable as a **Python dependency** by the planned GPS Base Station Web UI project (gps-webui). The core purpose remains unchanged: RTCM relay.

Architecture plan: `docs/v2.1-architecture-plan.md`
UI integration plan: `docs/ublox_gps_webui_planning.md`

### v2.1 Design Decisions (DR-8 through DR-14)

| ID | Decision | Rationale |
|---|---|---|
| DR-8 | In-process integration model | UI imports sp-base-relay directly; no IPC/HTTP needed |
| DR-9 | Programmatic config | UI builds Config/DestinationConfig objects in Python |
| DR-10 | Polling + Event Bus for status | Snapshot polling + push events for discrete changes |
| DR-11 | Hot add/remove destinations | Without stopping the hub or other destinations |
| DR-12 | Per-destination start/stop | Individual destinations controlled independently |
| DR-13 | RelayEngine facade | Single high-level API class for external consumers |
| DR-14 | Backward compatibility | CLI, YAML, Prometheus all unchanged |

### v2.1 Development Phases

| Phase | Deliverable | Status | Estimated Sessions |
|---|---|---|---|
| P1 | Event Bus system (events.py) | NOT STARTED | 1 |
| P2 | Typed status snapshots (status.py) | NOT STARTED | 0.5 |
| P3 | Dynamic destination management (BroadcastHub enhancements) | NOT STARTED | 1-1.5 |
| P4 | RelayEngine facade (engine.py) + main.py refactor | NOT STARTED | 1.5 |
| P5 | Integration tests & documentation | NOT STARTED | 1 |

### New Files Planned
- `src/sp_base_relay/engine.py` — RelayEngine facade
- `src/sp_base_relay/core/events.py` — EventBus, RelayEvent, EventSubscription
- `src/sp_base_relay/core/status.py` — RelayStatus, DestinationStatus, InputStatus

### Modified Files Planned
- `src/sp_base_relay/core/broadcast_hub.py` — dynamic dest mgmt, event emissions, dest lock
- `src/sp_base_relay/core/destinations/base_destination.py` — optional event_bus, event emissions
- `src/sp_base_relay/core/destinations/destination_factory.py` — passes event_bus
- `src/sp_base_relay/main.py` — refactored to use RelayEngine internally
- `src/sp_base_relay/__init__.py` — updated exports

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

All v2.0 phases complete (Phases 1-6). 956 tests passing. 88.46% coverage.
See `docs/v2-architecture-plan.md` for v2.0 details.

---

## Key Decisions Log

### March 26, 2026 — v2.1 Planning
- DR-8: In-process integration (UI imports sp-base-relay)
- DR-9: Programmatic config (no YAML required for embedded use)
- DR-10: Polling + Event Bus (snapshot + push events)
- DR-11: Hot add/remove destinations (zero interruption)
- DR-12: Per-destination start/stop
- DR-13: RelayEngine facade API
- DR-14: Full backward compatibility

### March 16-17, 2026 — v2.0 Architecture (DR-1 through DR-7)
- DR-1 through DR-7 unchanged (see v2.0 docs)

---

## Important Patterns and Preferences

### v2.1 New Patterns
- **Facade Pattern**: RelayEngine wraps BroadcastHub + events + status
- **Observer/Pub-Sub Pattern**: EventBus with subscriber queues + ring buffer
- **Copy-on-Read Pattern**: Thread-safe destination list in broadcast loop

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
