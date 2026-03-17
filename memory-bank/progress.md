# Progress

## Current Status — v2.0 Phase 2B COMPLETE (March 17, 2026)

**v1.x**: All phases complete (production-running)
**v2.0**: Phase 2B complete. Phase 3 (NTRIP Destination) next.
**Branch**: `feature/v2-multi-destination`
**Tests**: 832 passing (~276 new v2 tests), zero regressions

Full architecture plan with DR decisions: `docs/v2-architecture-plan.md`

---

## v2.0 Development Progress

### Phase 1: Foundation — Base Destination & Broadcast Hub ✅ COMPLETE
**Status**: COMPLETE (4 sessions: 1A, 1B, 1C, 1D) | **Effort**: 4 sessions

- [x] `BaseDestination` ABC with standard interface (88% coverage)
- [x] `DestinationStats` dataclass
- [x] `MessageFilter` (pass_all/allowlist/blocklist) (100% coverage)
- [x] `DestinationError` / `NtripError` exception types (100% coverage)
- [x] Config v2 — `destinations:` list parsing, `DestinationFilterConfig`, `SurePathDestinationConfig`, `NtripDestinationConfig`, `TcpServerDestinationConfig`, per-dest env overrides, old v1.x format detection (DR-4). 60+ new tests. (Session 1B, commit `0d238ec`)
- [x] `BroadcastHub` — fan-out coordinator with dual-path distribution (DR-1), frame parsing, no-data watchdog (DR-7), input reconnection. 46 tests. (Session 1C, commit `f0e1b4f`)
- [x] `DestinationFactory` — registry-based creation from `DestinationConfig`. 27 tests. (Session 1D)
- [x] RTCMGenerator `to_bytes()` bug fix (incorrect length field + CRC)

### Phase 2A: SurePathDestination ✅ COMPLETE
**Status**: COMPLETE (Session 2A, commit `7b3fc9d`) | **Effort**: 1 session

- [x] `SurePathDestination` wrapping RTCMClient (composition pattern)
- [x] Backoff-aware `_attempt_connect` override using RTCMClient retry delay
- [x] `build_surepath_destination` factory builder, auto-registered
- [x] 31 new tests

### Phase 2B: main.py v2 Refactor ✅ COMPLETE
**Status**: COMPLETE (Session 2B, commit `b455542`) | **Effort**: 1 session

- [x] `main.py` v2 with BroadcastHub + DestinationFactory (~200 lines, down from 400+)
- [x] Removed DataPipelineCoordinator, _restart_pipeline, _create_rtcm_client
- [x] Added _create_destinations, _start_hub, public BaseDestination.is_connected property
- [x] `test_main.py` fully rewritten (53 tests)
- [x] 832/832 passing, zero regressions

### Phase 3: NTRIP Destination
**Status**: NOT STARTED | **Effort**: 2-3 sessions

- [ ] `NtripDestination` implementing BaseDestination
- [ ] NTRIP v1.0 protocol (SOURCE + raw stream)
- [ ] NTRIP v2.0 protocol (HTTP POST + chunked)
- [ ] Mock NTRIP caster for testing
- [ ] RTK2go real-world testing

### Phase 4: Metrics v2
**Status**: NOT STARTED | **Effort**: 1-2 sessions

- [ ] `MetricsCollector` v2 with per-destination labels
- [ ] Grafana dashboard v2
- [ ] Alerting rules

### Phase 5: TCP Server Destination (Low Priority)
**Status**: NOT STARTED | **Effort**: 1-2 sessions

- [ ] `TcpServerDestination` (asyncio inside thread)
- [ ] Multi-client broadcast
- [ ] Backpressure handling

### Phase 6: Integration & Polish
**Status**: NOT STARTED | **Effort**: 1-2 sessions

- [ ] End-to-end integration tests
- [ ] Updated docs, README, example configs
- [ ] Version bump to 2.0.0

---

## v2.0 Module Map (Phase 2A Complete)

```
src/sp_base_relay/
├── config.py                    # v2 destination configs + old format detection
├── exceptions.py                # DestinationError, NtripError added
├── core/
│   ├── message_filter.py        # NEW — FilterConfig + MessageFilter
│   ├── broadcast_hub.py         # NEW — fan-out coordinator
│   └── destinations/
│       ├── __init__.py           # Exports + auto-registers surepath
│       ├── base_destination.py   # NEW — ABC + queue + stats
│       ├── destination_factory.py # NEW — registry-based factory
│       └── surepath_destination.py # NEW — RTCMClient wrapper
```

---

## v1.x Completed Work (October 2025 — February 2026)

### ✅ All v1.x Phases Complete
- Phase 1: Core Foundation (config, logging, exceptions)
- Phase 2: RTCM Server Connection (RTCMClient, heartbeat, auth)
- Phase 3: Input Source Management (serial, tcp, bluetooth)
- Phase 4: Data Pipeline (DataPipelineCoordinator)
- Phase 5: Prometheus Metrics & Monitoring
- Phase 7: CLI & Service Management
- Phase 8: Bluetooth GPS Integration
- Phase 9.5: dbus-fast Migration
- Production enhancements (logging, socket cleanup, outage handling)

---

## v2.0 Key Architectural Decisions (March 16, 2026)

| Decision | Choice | Rationale |
|---|---|---|
| Concurrency | A+ Threading | Minimal risk, natural isolation, async-ready |
| NTRIP Version | v1.0 + v2.0, default v2.0 | Max compatibility, 3 casters use mix |
| Filtering | pass_all/allowlist/blocklist | Per-destination RTCM message type ID |
| Metrics | Clean slate, per-dest labels | 4-5 destinations need individual visibility |
| TCP Server | Async inside thread | Multi-client, A+ pattern |
| Config | `destinations:` list | Breaking change from `server:` |

---

## Known Issues / Risks

- ⚠️ v2.0 is a breaking change (config format, metrics names)
- ⚠️ Phase 10 (PyPI packaging) still not started from v1.x
- ✅ v1.x Sure-Path connection is production-stable
- ✅ All 832 unit tests passing
