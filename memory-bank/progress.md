# Progress

## Current Status — v2.1 Planning COMPLETE (March 26, 2026)

**v1.x**: All phases complete (production-running)
**v2.0**: All phases complete (956 tests, 88.46% coverage, commit 8f4f79a)
**v2.1**: Planning complete. Ready to begin implementation.
**Version**: 2.0.0 (will become 2.1.0)
**Tests**: 956 passing, 88.46% coverage

Architecture plans:
- v2.0: `docs/v2-architecture-plan.md`
- v2.1: `docs/v2.1-architecture-plan.md`
- UI integration: `docs/ublox_gps_webui_planning.md`

---

## v2.1 Development Plan — Embeddable Relay Engine

### Purpose
Enhance sp-base-relay so it can be used as a Python dependency by the planned GPS Base Station Web UI project (gps-webui). Core relay purpose unchanged.

### Design Decisions (DR-8 through DR-14)
- DR-8: In-process integration (UI imports sp-base-relay directly)
- DR-9: Programmatic config (no YAML required for embedded use)
- DR-10: Polling + Event Bus (snapshot + push events)
- DR-11: Hot add/remove destinations (zero interruption to other dests)
- DR-12: Per-destination start/stop (independent control)
- DR-13: RelayEngine facade (single API class for external consumers)
- DR-14: Full backward compatibility (CLI, YAML, Prometheus unchanged)

### Phase 1: Event Bus System — NOT STARTED
**New**: `src/sp_base_relay/core/events.py`, `tests/unit/test_events.py`
**Estimated**: 1 session

- [ ] `RelayEvent` frozen dataclass (event_type, message, timestamp, payload)
- [ ] `EventSubscription` class (queue-based, iterable, closeable)
- [ ] `EventBus` class (thread-safe emit, subscribe, unsubscribe, ring buffer)
- [ ] Event type string constants (hub.*, input.*, destination.*, engine.*)
- [ ] Tests: ~80-100

### Phase 2: Typed Status Snapshots — NOT STARTED
**New**: `src/sp_base_relay/core/status.py`, `tests/unit/test_status.py`
**Estimated**: 0.5 sessions

- [ ] `DestinationStatus` frozen dataclass
- [ ] `InputStatus` frozen dataclass
- [ ] `RelayStatus` frozen dataclass
- [ ] `build_relay_status()` builder function
- [ ] Tests: ~30-40

### Phase 3: Dynamic Destination Management — NOT STARTED
**Modified**: `broadcast_hub.py`, `base_destination.py`
**Estimated**: 1-1.5 sessions

- [ ] Thread-safe destination list (lock-protected, copy-on-read)
- [ ] `BroadcastHub.add_destination()` — hot-add while running
- [ ] `BroadcastHub.remove_destination()` — hot-remove while running
- [ ] `BroadcastHub.stop_destination()` / `start_destination()` — per-dest control
- [ ] Event emissions in BroadcastHub (optional event_bus param)
- [ ] Event emissions in BaseDestination (optional event_bus param)
- [ ] Recalculate `_any_needs_parsing` on add/remove
- [ ] Tests: ~60-80

### Phase 4: RelayEngine Facade — NOT STARTED
**New**: `src/sp_base_relay/engine.py`, `tests/unit/test_engine.py`
**Modified**: `main.py`, `__init__.py`
**Estimated**: 1.5 sessions

- [ ] `RelayEngine` class with full lifecycle API
- [ ] Destination management (add, remove, start, stop)
- [ ] Status & events (get_status, subscribe_events, get_recent_events)
- [ ] Refactor `main.py` to use RelayEngine internally
- [ ] Update `__init__.py` exports
- [ ] Tests: ~60-80

### Phase 5: Integration Tests & Documentation — NOT STARTED
**Estimated**: 1 session

- [ ] Integration tests: full lifecycle with real TCP sockets
- [ ] README.md: add "Embedded Usage" section
- [ ] configuration-reference.md: add programmatic config section
- [ ] Memory bank updates

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

**Total v2 tests**: 956 (up from 556 in v1.x)

---

## v2.0 Module Map (Current)

```
src/sp_base_relay/
├── config.py                    # v2 destination configs + old format detection
├── metrics.py                   # Per-destination Prometheus labels + tcp_server gauge
├── exceptions.py                # DestinationError, NtripError
├── core/
│   ├── message_filter.py        # FilterConfig + MessageFilter
│   ├── broadcast_hub.py         # Fan-out coordinator
│   └── destinations/
│       ├── __init__.py
│       ├── base_destination.py   # ABC + queue + stats
│       ├── destination_factory.py # Registry-based factory
│       ├── surepath_destination.py # RTCMClient wrapper
│       ├── ntrip_destination.py  # NTRIP v1.0 + v2.0 server
│       └── tcp_server_destination.py # Asyncio TCP server
```

---

## v1.x Completed Work (October 2025 — February 2026)

All v1.x phases complete. See previous progress entries.

---

## GPS Base Station Web UI Project (gps-webui)

### Planning Status: COMPLETE (March 26, 2026)
- Architecture documented in `docs/ublox_gps_webui_planning.md`
- sp-base-relay is a dependency, not renamed
- gps-webui owns u-blox device config (via PyUBX2), relay logic stays in sp-base-relay
- FastAPI + NiceGUI for web framework
- Serial port handoff pattern: relay owns port when running, PyUBX2 when stopped

### Prerequisite: sp-base-relay v2.1 must be complete before gps-webui development begins

---

## Known Issues / Risks

- ⚠️ v2.0 is a breaking change from v1.x (config format, metrics names)
- ⚠️ Phase 10 (PyPI packaging) still not started from v1.x
- ⚠️ v2.1 adds optional params to BroadcastHub/BaseDestination — must maintain backward compat
- ✅ v1.x Sure-Path connection is production-stable
- ✅ All 956 unit tests passing
- ✅ v2.1 design decisions documented and approved
