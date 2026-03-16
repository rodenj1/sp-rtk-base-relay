# Progress

## Current Status — v2.0 Planning Complete (March 16, 2026)

**v1.x**: All phases complete (556 tests, ~90% coverage, production-running)
**v2.0**: Architecture planning complete, Phase 1 implementation ready to begin

Full architecture plan: `docs/v2-architecture-plan.md`

---

## v2.0 Development Progress

### Phase 1: Foundation — Base Destination & Broadcast Hub
**Status**: NOT STARTED | **Effort**: 3-4 sessions

- [ ] `BaseDestination` ABC with standard interface
- [ ] `DestinationStats` dataclass
- [ ] `MessageFilter` (pass_all/allowlist/blocklist)
- [ ] `BroadcastHub` (replaces DataPipelineCoordinator)
- [ ] `DestinationFactory`
- [ ] Config v2 (`destinations:` list parsing)
- [ ] Test suite for all new modules

### Phase 2: Sure-Path Destination Refactor
**Status**: NOT STARTED | **Effort**: 1-2 sessions

- [ ] `SurePathDestination` wrapping RTCMClient
- [ ] `main.py` v2 with broadcast hub
- [ ] Regression testing

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

## v1.x Completed Work (October 2025 — February 2026)

### ✅ Phase 1: Core Foundation (COMPLETE)
- UV package structure, config management (89% coverage), logging (91%), exceptions (100%)
- 72 unit tests, RTCM test data generator

### ✅ Phase 2: RTCM Server Connection (COMPLETE)
- Multi-threaded TCP client with custom INIT auth + $HB$ heartbeat
- Exponential backoff retry (1s→2s→4s→8s→16s→32s→60s)
- Connection state machine (100% coverage)
- 30 RTCM client tests + 10 connection state tests

### ✅ Phase 3: Input Source Management (COMPLETE)
- Strategy pattern: Serial (84%), TCP (90%), Bluetooth, Base (90%)
- Input factory with registration system (86%)
- Python 3.10+ modern type hints throughout

### ✅ Phase 4: Data Pipeline (COMPLETE)
- 3-thread architecture (input, coordinator, heartbeat)
- Queue-based thread coordination (maxsize=10)
- Coordinated restart, no buffering design
- 100+ tests, 84% → 91% coverage

### ✅ Phase 5: Prometheus Metrics (COMPLETE)
- 17 metrics across 5 categories (96% coverage)
- Grafana dashboard (11 panels), integration examples
- Delta-based counter updates, thread-safe operations

### ✅ Phase 7: CLI & Service Management (COMPLETE)
- Full argparse CLI, SPBaseRelayService orchestration
- Signal handling, threading architecture
- 51 tests, systemd service file

### ✅ Phase 8: Bluetooth GPS Integration (COMPLETE)
- rfcomm-based Bluetooth SPP integration
- 4 helper scripts, systemd service, 500+ line docs
- RTK_BASE_ROD device configured

### ✅ Phase 9.5: dbus-fast Migration (COMPLETE)
- Migrated from pydbus (unmaintained) to dbus-fast
- Full type hint coverage, async/sync wrapper pattern
- 44/44 Bluetooth tests, 556/556 total tests passing

### ✅ Production Enhancements (COMPLETE)
- Smart logging (expected disconnects → INFO, retries → WARNING)
- Aggressive socket cleanup (errno 9 fix)
- Long-term outage handling (60 internal retries + systemd restarts)
- 15s initial retry delay for 10-minute server cycle

---

## Test Coverage (v1.x Final — February 2026)
- **556 total unit tests passing (100%)**
- **~90% overall coverage**
- config.py: 89%, logger.py: 91%, exceptions.py: 100%
- connection_states.py: 100%, rtcm_client.py: 87%, data_pipeline.py: 91%
- input_factory.py: 86%, serial_input.py: 84%, tcp_input.py: 90%
- base_input.py: 90%, metrics.py: 96%

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

Target casters: RTK2go, Onocoy, rtkdirect (currently running via external tools)

---

## Known Issues / Risks

- ⚠️ v2.0 is a breaking change (config format, metrics names)
- ⚠️ Phase 10 (PyPI packaging) still not started from v1.x
- ✅ v1.x Sure-Path connection is production-stable
- ✅ All 556 unit tests passing
