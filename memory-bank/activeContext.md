# Active Context

## Current Work Focus

**Primary Objective**: SP-Base-Relay v2.1 COMPLETE → Next: gps-webui (April 2026)

**Status**: v2.1 Phases 0–5 COMPLETE. Phase 6 (cleanup) pending. gps-webui next.

**Previous**: v2.0 Phase 6 COMPLETE. All v2.0 features merged (commit 8f4f79a).
**Branch**: `feature/v2.1-relay-engine` (branched from `feature/v2-multi-destination`)

### v2.1 Implementation Summary

v2.1 enhances sp-base-relay to be usable as a **Python dependency** by the planned GPS Base Station Web UI project (gps-webui). The core purpose remains unchanged: RTCM relay.

Architecture plan: `docs/v2.1-architecture-plan.md`
UI integration plan: `docs/ublox_gps_webui_planning.md`
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

### Next Steps (Priority Order)
1. **Phase 6**: sp-base-relay cleanup (remove probe_gps.py, revert pyubx2, README, integration tests)
2. **Phase 7**: gps-webui project scaffolding (new repo)
3. **Phase 8**: Device info & identification (PyUBX2 in gps-webui)
4. **Phase 9**: GPS configuration UI
5. **Phase 10**: Relay dashboard

---

## Key Architecture Decisions (April 2026)

### DR-15: Device Info/Config Lives in gps-webui
- **Decision**: All PyUBX2 interaction (device querying, GPS configuration) belongs in gps-webui, NOT sp-base-relay
- **Rationale**: sp-base-relay is a pure RTCM relay. Adding PyUBX2 would add unnecessary complexity and an unrelated dependency.
- **Impact**: sp-base-relay stays focused; gps-webui owns all u-blox device management

### DR-16: Two-Port Architecture Support
- **Separate ports** (e.g., FTDI UART for UBX, Bluetooth for RTCM): No relay interruption needed for device queries/config
- **Shared port** (single USB/UART for both): Must use serial port handoff (stop relay → UBX session → restart)
- **Impact**: gps-webui must detect which configuration is in use and adapt behavior accordingly

### DR-17: Serial Port Handoff Pattern
- Already implemented in RelayEngine (`engine.stop()` is synchronous, releases port immediately)
- Documented in API spec with code examples
- gps-webui uses this for shared-port configurations

---

## Hardware Findings (April 2026)

### Test GPS Receiver — u-blox ZED-F9P
| Field | Value |
|---|---|
| Module | ZED-F9P |
| Firmware | HPG 1.12 |
| Protocol | 27.11 |
| Software | EXT CORE 1.00 (61b2dd) |
| Hardware | 00190000 |
| Constellations | GPS, GLONASS, Galileo, BeiDou, QZSS |

### Port Configuration (Scenario 2 — Separate Ports)
- **UBX Config**: `/dev/ttyUSB0` via FTDI FT232 adapter @ 57600 baud
- **RTCM Relay**: Bluetooth serial (dedicated RTCM output)
- **Result**: Can query/configure GPS while relay runs uninterrupted

---

## GPS Base Station Web UI Project (gps-webui)

### Key Architecture Decisions
- sp-base-relay is a **dependency** of gps-webui, not renamed or restructured
- gps-webui owns u-blox device configuration (via PyUBX2), NOT sp-base-relay
- Two-port support: separate UBX + RTCM = no relay interruption
- Shared-port support: serial handoff via engine.stop()/start()
- FastAPI + NiceGUI for web framework
- In-process integration — gps-webui imports RelayEngine directly

### gps-webui Startup Flow
```
1. Query device info (UBX-MON-VER) — identify GPS module
2. Check if relay port is different from UBX port
   → Separate: start relay immediately, query device anytime
   → Shared: defer relay until after device config
3. Check base station configuration
4. Offer survey backup if configured
5. Start relay with user-configured destinations
```

### Dependency Graph
```
gps-webui → sp-base-relay (relay engine)
gps-webui → pyubx2 (u-blox device queries & config)
gps-webui → pyubxutils (backup/restore)
gps-webui → fastapi + nicegui (web UI)
```

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
