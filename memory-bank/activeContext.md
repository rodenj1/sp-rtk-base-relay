# Active Context

## Current Work Focus

**Primary Objective**: SP-Base-Relay v2.0 — Multi-Destination Architecture (March 2026)

**Status**: Phase 3A COMPLETE. Session 3B (mock NTRIP caster integration testing) next.

**Branch**: `feature/v2-multi-destination` (latest: commit 26fe862)

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

### v2.0 Phase 3A — NtripDestination Complete ✅ (March 17, 2026)

| Session | Deliverable | Tests | Commit |
|---|---|---|---|
| 3A | NtripDestination — NTRIP v1.0 + v2.0 server, factory registration | 39 | 26fe862 |

**Total v2 new tests**: ~315 new tests (871 total, up from 556 in v1.x)

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

## Next Steps — Phase 3B: Mock NTRIP Caster Integration Testing

**Effort**: 1 session | **Dependencies**: Phase 3A (DONE)

1. Mock NTRIP caster fixture for local integration testing (no RTK2go)
2. Integration tests: v1.0 connect + stream, v2.0 connect + stream
3. Error scenario tests: auth reject, caster crash, reconnection

---

## v2.0 Development Phases

### Phase 1: Foundation — COMPLETE ✅
### Phase 2A: SurePathDestination — COMPLETE ✅
### Phase 2B: main.py v2 Refactor — COMPLETE ✅
### Phase 3A: NtripDestination — COMPLETE ✅
### Phase 3B: Mock NTRIP Caster Testing — NOT STARTED
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
