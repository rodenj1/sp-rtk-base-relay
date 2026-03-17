# Active Context

## Current Work Focus

**Primary Objective**: SP-Base-Relay v2.0 — Multi-Destination Architecture (March 2026)

**Status**: Phase 2B COMPLETE. Ready for Phase 3 (NTRIP Destination).

**Branch**: `feature/v2-multi-destination` (latest: commit b455542)

### v2.0 Phase 1 — Foundation Complete ✅

| Session | Deliverable | Tests | Commit |
|---|---|---|---|
| 1A | MessageFilter, BaseDestination, DestinationStats, exception types | 78 | (part of 0d238ec) |
| 1B | Config v2 — destination configs, filter configs, env overrides, old format detection | 60+ | 0d238ec |
| 1C | BroadcastHub — fan-out coordinator with frame parsing, watchdog, reconnection | 46 | f0e1b4f |
| 1D | DestinationFactory — registry-based creation from config | 27 | 3064ff9 |

### v2.0 Phase 2A — SurePathDestination Complete ✅ (March 17, 2026)

| Session | Deliverable | Tests | Commit |
|---|---|---|---|
| 2A | SurePathDestination — RTCMClient wrapper behind BaseDestination | 31 | 7b3fc9d |

### v2.0 Phase 2B — main.py v2 Refactor Complete ✅ (March 17, 2026)

| Session | Deliverable | Tests | Commit |
|---|---|---|---|
| 2B | main.py v2 — BroadcastHub + DestinationFactory orchestration | 53 (rewritten) | b455542 |

**Total v2 new tests**: ~276 new tests (832 total, up from 556 in v1.x)

### Design Review Decisions (DR-1 through DR-7)
1. **DR-1**: Dual-path frame parsing — parse only when filtering needed
2. **DR-2**: Queue overflow — drop newest, clear on reconnect, maxsize=100
3. **DR-3**: Separate Broadcast Thread between input and destinations
4. **DR-4**: Config migration — documentation only, no CLI tool
5. **DR-5**: NTRIP connection health — send() failure + backoff
6. **DR-6**: NTRIP STR records — deferred to post-v2.0
7. **DR-7**: Input no-data watchdog — passive logging

### Architecture Document
Full architecture plan: `docs/v2-architecture-plan.md`

---

## Next Steps — Phase 3: NTRIP Destination

**Effort**: 2-3 sessions | **Dependencies**: Phase 2 (DONE)

1. `NtripDestination` implementing BaseDestination
2. NTRIP v1.0 protocol (SOURCE + raw stream)
3. NTRIP v2.0 protocol (HTTP POST + chunked transfer)
4. Mock NTRIP caster for testing
5. RTK2go real-world testing

---

## v2.0 Development Phases

### Phase 1: Foundation — COMPLETE ✅
### Phase 2A: SurePathDestination — COMPLETE ✅
### Phase 2B: main.py v2 Refactor — COMPLETE ✅
### Phase 3: NTRIP Destination — NOT STARTED
### Phase 4: Metrics v2 — NOT STARTED
### Phase 5: TCP Server Destination — NOT STARTED (Low Priority)
### Phase 6: Integration & Polish — NOT STARTED

---

## Key Decisions Log

### March 16-17, 2026 — v2.0 Architecture & Phase 1
- Threading over Asyncio (A+ pattern)
- NTRIP v2.0 default, v1.0 supported
- Clean slate metrics with per-destination labels
- `destinations:` list config format (breaking change from `server:`)
- DestinationFactory uses registry pattern (same as InputSourceFactory)
- BroadcastHub has dual-path: raw fast-path for pass_all, parsed for filtered

---

## Important Patterns and Preferences

### v2.0 Architecture Patterns
- **Strategy Pattern**: Input sources AND destinations (factory + ABC)
- **Registry Pattern**: DestinationFactory.register() for type discovery
- **Fan-Out Pattern**: BroadcastHub → N destination queues
- **A+ Pattern**: Threading for orchestration, asyncio available internally

### Code Quality Standards
- Python 3.10+ with type hints (modern syntax: `dict`, `list`, `X | None`)
- >90% unit test coverage using Pytest
- Zero pylance/pyright issues in strict mode
- PEP8 standards
- UV package management
