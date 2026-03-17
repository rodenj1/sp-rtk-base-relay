# Active Context

## Current Work Focus

**Primary Objective**: SP-Base-Relay v2.0 — Multi-Destination Architecture (March 2026)

**Status**: Phase 1 Session 1A complete. Session 1B (Config v2) ready to begin.

**Branch**: `feature/v2-multi-destination` (commit `9269df9`)

### v2.0 Planning & Design Review (March 16, 2026)
Architecture planning + detailed design review completed. Key decisions:

1. **Concurrency Model**: A+ Threading — per-destination queues with async-ready interface
2. **NTRIP Protocol**: Both v1.0 and v2.0 supported, v2.0 as default
3. **Message Filtering**: Per-destination RTCM message type ID filtering (pass_all/allowlist/blocklist)
4. **Metrics**: Clean slate v2.0 — per-destination Prometheus labels
5. **TCP Server**: Multi-client async inside thread (A+ pattern), low priority
6. **Configuration**: `destinations:` list format replacing `server:` section

### Design Review Decisions (DR-1 through DR-7)
7. **DR-1**: Dual-path frame parsing — parse only when filtering needed; `pass_all` gets raw chunks; metrics decoding post-send per destination thread
8. **DR-2**: Queue overflow — drop newest (non-blocking), clear queue on reconnect, `maxsize=100`, track drops metric
9. **DR-3**: Separate Broadcast Thread — acts as coordinator between input and destinations
10. **DR-4**: Config migration — documentation only, no CLI migration tool
11. **DR-5**: NTRIP connection health — industry standard `send()` failure + exponential backoff (same for v1 & v2)
12. **DR-6**: NTRIP STR records — deferred to post-v2.0
13. **DR-7**: Input no-data watchdog — passive logging (WARNING after 30s, Prometheus gauge)

### Architecture Document
Full architecture plan with DR decisions: `docs/v2-architecture-plan.md`

---

## Previous Work (Completed)

### v1.x Development (October 2025 — February 2026) - ALL COMPLETE
- ✅ Phase 1: Core Foundation (config, logging, exceptions)
- ✅ Phase 2: RTCM Server Connection (RTCMClient, heartbeat, auth)
- ✅ Phase 3: Input Source Management (serial, tcp, bluetooth)
- ✅ Phase 4: Data Pipeline (DataPipelineCoordinator)
- ✅ Phase 5: Prometheus Metrics & Monitoring
- ✅ Phase 6: Testing Infrastructure (556 tests, ~90% coverage)
- ✅ Phase 7: CLI & Service Management (main.py)
- ✅ Phase 8: Bluetooth GPS Integration
- ✅ Phase 9.5: dbus-fast Migration (type safety)
- ✅ Production logging optimization, socket cleanup, long-term outage handling

---

## v2.0 Development Phases

### Phase 1: Foundation — Base Destination & Broadcast Hub
**Status**: NOT STARTED | **Effort**: 3-4 sessions | **Dependencies**: None

Deliverables:
1. `BaseDestination` ABC (`core/destinations/base_destination.py`)
2. `DestinationStats` dataclass
3. `MessageFilter` (`core/message_filter.py`) — pass_all/allowlist/blocklist
4. `BroadcastHub` (`core/broadcast_hub.py`) — input thread → frame parsing → filtered fanout
5. `DestinationFactory` (`core/destinations/destination_factory.py`)
6. Config v2 — `DestinationConfig` parsing, `destinations:` list
7. Full test suite

### Phase 2: Sure-Path Destination Refactor
**Status**: NOT STARTED | **Effort**: 1-2 sessions | **Dependencies**: Phase 1

Deliverables:
1. `SurePathDestination` (`core/destinations/surepath_destination.py`)
2. `main.py` v2 — refactored with broadcast hub
3. Regression testing vs v1 behavior

### Phase 3: NTRIP Destination
**Status**: NOT STARTED | **Effort**: 2-3 sessions | **Dependencies**: Phase 1

Deliverables:
1. `NtripDestination` (`core/destinations/ntrip_destination.py`)
2. NTRIP v1.0 protocol (SOURCE auth + raw streaming)
3. NTRIP v2.0 protocol (HTTP POST + chunked encoding)
4. Mock NTRIP caster for testing
5. Real-world testing against RTK2go

### Phase 4: Metrics v2
**Status**: NOT STARTED | **Effort**: 1-2 sessions | **Dependencies**: Phase 1, 2

Deliverables:
1. `MetricsCollector` v2 with per-destination labels
2. Grafana dashboard v2 template
3. Alerting rules

### Phase 5: TCP Server Destination (Low Priority)
**Status**: NOT STARTED | **Effort**: 1-2 sessions | **Dependencies**: Phase 1

Deliverables:
1. `TcpServerDestination` (`core/destinations/tcp_server_destination.py`)
2. asyncio.start_server() inside thread
3. Multi-client broadcast, backpressure

### Phase 6: Integration & Polish
**Status**: NOT STARTED | **Effort**: 1-2 sessions | **Dependencies**: All above

Deliverables:
1. End-to-end integration tests
2. Updated docs, README, example configs
3. Version bump to 2.0.0

---

## Key Decisions Log

### March 16, 2026 — v2.0 Architecture Planning
- **Threading over Asyncio**: Chosen for minimal migration risk, natural isolation, and compatibility with blocking serial/Bluetooth I/O
- **A+ Pattern**: Async-ready design allowing asyncio internally for TCP server destination
- **NTRIP v2.0 Default**: HTTP-compliant, better firewall traversal, recommended by casters
- **Clean Slate Metrics**: Breaking change acceptable for major version — per-destination labels essential for 4-5 simultaneous destinations
- **3 NTRIP Casters**: User currently uses Onocoy, RTK2go, rtkdirect (mixture of v1 and v2)

### Previous Decisions (v1.x)
- Threading over async (initial decision, reaffirmed for v2.0)
- YAML configuration with env var overrides
- Prometheus metrics for monitoring
- No RTCM validation (pass-through for latency)
- Exponential backoff retry pattern

---

## Important Patterns and Preferences

### v2.0 Architecture Patterns
- **Strategy Pattern**: Used for both input sources AND destinations (factory + ABC)
- **Observer Pattern**: Per-destination metrics collection via stats polling
- **Fan-Out Pattern**: BroadcastHub distributes data to N destination queues
- **A+ Pattern**: Threading for orchestration, asyncio available internally for specific destinations

### Code Quality Standards (Maintained)
- Python 3.10+ with type hints (modern syntax: `dict`, `list`, `X | None`)
- >90% unit test coverage using Pytest
- Zero pylance/pyright issues in strict mode
- PEP8 standards
- UV package management
