# SP-Base-Relay v2.0 — Multi-Destination Architecture Plan

## Document Status
- **Created**: March 16, 2026
- **Updated**: March 16, 2026 (Design review decisions added)
- **Status**: Approved — Ready for implementation
- **Version**: 2.0.0 (Major release with breaking changes)

---

## Executive Summary

SP-Base-Relay v2.0 transforms the system from a single-destination RTCM relay (GPS Source → Sure-Path Server) into a multi-destination broadcast system (GPS Source → N Destinations). This enables simultaneous publishing to:
- **Sure-Path** server (existing, custom protocol)
- **NTRIP casters** (RTK2go, Onocoy, rtkdirect, etc.) via NTRIP v1.0/v2.0
- **Local TCP server** for LAN clients

---

## Architectural Decisions

### Decision 1: Concurrency Model — A+ Threading
**Choice**: Threading with per-destination queues, async-ready interface design

**Rationale**:
- Existing codebase is threading-based and production-stable
- Serial/Bluetooth input sources are inherently blocking I/O
- Each destination gets its own thread — natural fault isolation
- 4-5 destinations means manageable thread count (~10-15 threads)
- Minimal migration risk from existing v1.0 code
- "Async-ready" means the TCP server destination can use asyncio internally

**Architecture**:
```
                          ┌─ Queue ──▶ [SurePath Thread] ──▶ Sure-Path Server
[Input Thread] ──▶ [Broadcaster] ─┤─ Queue ──▶ [NTRIP Thread]   ──▶ NTRIP Caster
                          └─ Queue ──▶ [TCP Srv Thread]  ──▶ Local TCP Clients
```

### Decision 2: NTRIP Protocol — v1.0 + v2.0, Default v2.0
**Choice**: Support both NTRIP versions, v2.0 as the default

**Rationale**:
- v2.0 is HTTP-compliant (better firewall/proxy traversal)
- v1.0 is simpler and universally supported
- Delta between implementations is ~40 lines of code
- Target casters: RTK2go, Onocoy, rtkdirect (all support both)

### Decision 3: Message Filtering — Allowlist/Blocklist/Pass-All
**Choice**: Per-destination RTCM message type ID filtering

**Modes**:
- `pass_all`: No filtering, raw chunks forwarded (zero overhead)
- `allowlist`: Only specified message IDs pass through
- `blocklist`: All messages pass except specified IDs

**Implementation**: Filtering occurs in the broadcast hub before queueing, using existing `RTCMMessageDecoder` for frame parsing.

### Decision 4: Metrics — Per-Destination Labels (Clean Slate)
**Choice**: Replace global metrics with per-destination Prometheus labels

**Rationale**: With 4-5 destinations, operators need per-destination visibility. Breaking change is acceptable for a major version.

### Decision 5: TCP Server — Async Inside Thread (A+ Pattern)
**Choice**: Multi-client TCP server using `asyncio.start_server()` inside its own thread

**Rationale**: Elegantly handles many simultaneous clients while fitting the threading architecture.

### Decision 6: Configuration — `destinations:` List Format
**Choice**: Replace `server:` with `destinations:` list, each with name/type/enabled/filter/config

**Breaking Change**: Old `server:` format rejected with clear migration message.

---

## NTRIP Protocol Specification

### Terminology
| Term | Role | Our Implementation |
|---|---|---|
| NTRIP Server | Pushes RTCM from base station to caster | **This is what we build** |
| NTRIP Caster | Hub that distributes data to clients | RTK2go, Onocoy, rtkdirect |
| NTRIP Client | Rover/consumer receiving corrections | Not our concern |

### NTRIP v1.0 Server-to-Caster Protocol
```
# 1. TCP connect to caster:port (typically 2101)

# 2. Send SOURCE request
SOURCE <mountpoint_password>\r\n
Source-Agent: NTRIP sp-base-relay/2.0\r\n
\r\n

# 3. Receive response
ICY 200 OK\r\n
\r\n

# 4. Stream raw RTCM binary data continuously
<raw RTCM bytes...>
```

### NTRIP v2.0 Server-to-Caster Protocol
```
# 1. TCP connect to caster:port (typically 2101)

# 2. Send HTTP POST
POST /<mountpoint> HTTP/1.1\r\n
Host: <caster_host>\r\n
Ntrip-Version: Ntrip/2.0\r\n
Authorization: Basic <base64(username:password)>\r\n
User-Agent: NTRIP sp-base-relay/2.0\r\n
Transfer-Encoding: chunked\r\n
\r\n

# 3. Receive response
HTTP/1.1 200 OK\r\n
\r\n

# 4. Stream RTCM data using HTTP chunked encoding
<hex_length>\r\n
<rtcm_binary_data>\r\n
0\r\n
\r\n
```

### Connection Management
- Reconnection with exponential backoff (same pattern as Sure-Path)
- TCP keepalive enabled for connection health monitoring
- No custom heartbeat (unlike Sure-Path) — casters expect continuous data flow
- Data flow monitoring: detect stale connections by tracking last successful send

---

## Module Structure

```
src/sp_base_relay/
├── main.py                           # Refactored service orchestration (v2)
├── config.py                         # Refactored config with destinations: list
├── metrics.py                        # Rewritten with per-destination labels
├── exceptions.py                     # Add NtripError, DestinationError
├── rtcm_decoder.py                   # Unchanged
├── logger.py                         # Unchanged
├── core/
│   ├── broadcast_hub.py              # NEW — reads source, fans out to destinations
│   ├── message_filter.py             # NEW — RTCM message filtering logic
│   ├── rtcm_client.py                # Kept for Sure-Path (wrapped by destination)
│   ├── connection_states.py          # Unchanged
│   ├── data_pipeline.py              # DEPRECATED (replaced by broadcast_hub)
│   ├── bluetooth_manager.py          # Unchanged
│   ├── input_sources/                # Unchanged
│   │   ├── base_input.py
│   │   ├── serial_input.py
│   │   ├── tcp_input.py
│   │   ├── bluetooth_input.py
│   │   └── input_factory.py
│   └── destinations/                 # NEW — destination module package
│       ├── __init__.py
│       ├── base_destination.py       # Abstract base class for all destinations
│       ├── destination_factory.py    # Factory for creating destinations from config
│       ├── surepath_destination.py   # Wraps RTCMClient behind BaseDestination
│       ├── ntrip_destination.py      # NTRIP v1/v2 server implementation
│       └── tcp_server_destination.py # TCP serial server (async inside thread)
```

---

## Configuration Format (v2)

```yaml
# === GPS Source (single, unchanged concept) ===
input:
  source: tcp                         # tcp | serial | usb_serial | bluetooth
  config:
    host: 192.168.0.242
    port: 3000
    timeout: 5.0

# === Destinations (1 to many) ===
destinations:
  - name: surepath
    type: surepath
    enabled: true
    filter:
      mode: pass_all
    config:
      host: 91.186.9.136
      port: 50010
      username: RODEN01
      password: dae5
      connection_timeout: 10
      heartbeat_timeout: 30
      retry_initial_delay: 15
      retry_max_delay: 60
      retry_multiplier: 2.0

  - name: rtk2go
    type: ntrip
    enabled: true
    filter:
      mode: blocklist
      message_ids: [4072]
    config:
      caster: rtk2go.com
      port: 2101
      mountpoint: RODEN01
      password: my_rtk2go_password
      username: ""
      version: "2.0"
      retry_initial_delay: 10
      retry_max_delay: 120
      retry_multiplier: 2.0
      connection_timeout: 15

  - name: onocoy
    type: ntrip
    enabled: true
    filter:
      mode: pass_all
    config:
      caster: servers.onocoy.com
      port: 2101
      mountpoint: MY_ONOCOY_MOUNT
      password: my_onocoy_password
      version: "2.0"
      retry_initial_delay: 10
      retry_max_delay: 120

  - name: rtkdirect
    type: ntrip
    enabled: true
    filter:
      mode: allowlist
      message_ids: [1005, 1077, 1087, 1097, 1127, 1230]
    config:
      caster: caster.rtkdirect.com
      port: 2101
      mountpoint: MY_MOUNT
      password: my_password
      version: "1.0"
      retry_initial_delay: 10
      retry_max_delay: 120

  - name: local_tcp
    type: tcp_server
    enabled: false
    filter:
      mode: pass_all
    config:
      host: 0.0.0.0
      port: 5016
      max_clients: 10

# === Global Settings ===
metrics:
  enabled: true
  host: 0.0.0.0
  port: 8080

logging:
  level: INFO
  format: json
  file: /var/log/sp-base-relay.log
  max_size_mb: 50
  backup_count: 3

service:
  daemon: false
```

---

## Per-Destination Metrics (v2)

### Destination Metrics (labeled by destination name)
```
sp_base_relay_dest_bytes_sent_total{destination="..."}
sp_base_relay_dest_messages_sent_total{destination="..."}
sp_base_relay_dest_messages_filtered_total{destination="..."}
sp_base_relay_dest_connection_status{destination="..."}
sp_base_relay_dest_connection_attempts_total{destination="..."}
sp_base_relay_dest_errors_total{destination="...", error_type="..."}
sp_base_relay_dest_relay_latency_seconds{destination="..."}
sp_base_relay_dest_queue_depth{destination="..."}
sp_base_relay_dest_reconnect_attempts_total{destination="..."}
```

### Global Metrics
```
sp_base_relay_input_bytes_read_total
sp_base_relay_input_connection_status
sp_base_relay_service_uptime_seconds
sp_base_relay_active_destinations_count
sp_base_relay_rtcm_messages_by_id_total{message_id="..."}
```

---

## Development Phases

### Phase 1: Foundation — Base Destination & Broadcast Hub
**Effort**: 3-4 sessions | **Dependencies**: None

1. `BaseDestination` ABC with standard interface
2. `DestinationStats` dataclass for per-destination metrics
3. `MessageFilter` with pass_all/allowlist/blocklist modes
4. `BroadcastHub` — input thread → frame parsing → filtered fanout → destination queues
5. `DestinationFactory` — creates destinations from config
6. Config v2 — `DestinationConfig` parsing, `destinations:` list, old format detection
7. Full test suite for all new modules

### Phase 2: Sure-Path Destination Refactor
**Effort**: 1-2 sessions | **Dependencies**: Phase 1

1. `SurePathDestination` wrapping existing `RTCMClient`
2. `main.py` v2 — refactored service orchestration with broadcast hub
3. Regression testing — verify Sure-Path works identically to v1

### Phase 3: NTRIP Destination
**Effort**: 2-3 sessions | **Dependencies**: Phase 1

1. `NtripDestination` implementing `BaseDestination`
2. `NtripV1Protocol` — SOURCE auth + raw streaming
3. `NtripV2Protocol` — HTTP POST auth + chunked encoding
4. Reconnection with exponential backoff
5. Mock NTRIP caster for testing
6. Real-world testing against RTK2go

### Phase 4: Metrics v2
**Effort**: 1-2 sessions | **Dependencies**: Phase 1, 2

1. `MetricsCollector` v2 with per-destination labels
2. Grafana dashboard v2 template
3. Alerting rules for per-destination monitoring

### Phase 5: TCP Server Destination (Low Priority)
**Effort**: 1-2 sessions | **Dependencies**: Phase 1

1. `TcpServerDestination` with asyncio inside thread
2. Multi-client broadcast, backpressure handling
3. Client connect/disconnect management

### Phase 6: Integration & Polish
**Effort**: 1-2 sessions | **Dependencies**: All above

1. End-to-end integration tests
2. Config migration documentation
3. Updated README, deployment guide, example configs
4. Version bump to 2.0.0
5. Memory bank update

**Total estimated effort**: 9-15 sessions

---

## Risk Mitigations

| Risk | Mitigation |
|---|---|
| Sure-Path regression | Phase 2 specifically validates backward compatibility |
| NTRIP protocol compliance | Test against free RTK2go caster |
| Destination isolation failure | Thread-per-destination with independent queues |
| Latency increase from filtering | `pass_all` skips frame parsing entirely |
| Config migration confusion | Clear error message detecting old format |
| Thread explosion | Max ~15 threads for 5 destinations — well within limits |

---

## Breaking Changes from v1.0

1. **Config**: `server:` replaced by `destinations:` list
2. **Metrics**: All Prometheus metric names changed (per-destination labels)
3. **Module**: `DataPipelineCoordinator` replaced by `BroadcastHub`
4. **Version**: Bumped to 2.0.0
5. **Grafana Dashboard**: New template required (old dashboard incompatible)

---

## Detailed Design Review Decisions (March 16, 2026)

The following decisions were made during the pre-implementation design review session.

### DR-1: BroadcastHub Frame Parsing Strategy — Dual-Path Distribution

**Decision**: BroadcastHub uses a dual-path strategy for data distribution:

- If **all** destinations use `pass_all` → skip frame parsing entirely, forward raw chunks to all queues (zero overhead, identical to v1 behavior)
- If **any** destination uses allowlist/blocklist → parse RTCM frames, then:
  - `pass_all` destinations still get raw chunks (no overhead for them)
  - Filtered destinations get only the frames that pass their filter (complete RTCM frames, not raw chunks)
- **Metrics frame decoding remains post-send** in each destination thread (not in the BroadcastHub). Each destination thread tracks what messages it actually sent.

**Rationale**: Avoids unnecessary frame parsing overhead for `pass_all` destinations while sharing a single parse operation across all filtered destinations.

### DR-2: Queue Overflow Strategy — Drop Newest, Clear on Reconnect

**Decision**:
- Per-destination queues with `maxsize=100`
- When queue is full: **silently drop new data** for that destination (non-blocking `put_nowait`, no effect on other destinations)
- When destination reconnects after outage: **clear the queue** entirely, start fresh with new incoming data
- Track drops with `sp_base_relay_dest_messages_dropped_total{destination="..."}` metric

**Rationale**: Stale RTCM correction data is useless — a 30-second-old correction has no value. When a destination reconnects, it should receive only fresh data, not drain a backlog of obsolete corrections.

### DR-3: BroadcastHub — Separate Broadcast Thread

**Decision**: Use a dedicated Broadcast Thread between the Input Thread and Destination Threads.

```
[Input Thread] → input_queue → [Broadcast Thread] → dest_queues → [Dest Threads]
```

**Rationale**: The separate thread acts as a **central coordinator** that:
1. Decouples input health from destination health
2. Manages the "input source is down" state (clears stale queues, logs warnings)
3. Allows input thread to focus purely on reconnection while broadcast thread manages destination side
4. Keeps destination connections alive during input outages (caster connections are expensive to re-establish)

### DR-4: Config Migration — Documentation Only

**Decision**: No migration CLI tool. When v2 detects old `server:` key in config:
- Print clear error message with migration instructions
- Reference `config.example.yaml` and migration notes in README
- Provide `config.v2.example.yaml` showing the full new format

**Rationale**: Single primary user, straightforward migration, migration tool adds test/maintenance burden for one-time use.

### DR-5: NTRIP Connection Health — Industry Standard (send() + Backoff)

**Decision**: Follow the same approach as the BKG reference NtripServer implementation:
1. **Primary detection**: `send()` / `sendall()` failure → immediate reconnect with exponential backoff
2. **TCP keepalive**: Enable `SO_KEEPALIVE` with OS defaults as safety net (not tuned aggressively)
3. **No custom watchdog timer** — not needed because we're continuously sending data (1-5 Hz)
4. Applies to **both NTRIP v1 and v2** (same unidirectional "fire and forget" pattern)

**Research findings**:
- NTRIP v1.0 spec: *"A loss of the TCP connection will be automatically recognized by the TCP sockets"*
- BKG reference implementation: reconnects with exponential backoff on TCP error
- RTK2go/SNIP: caster disconnects "dead" server connections after ~12 seconds of no data
- All major open-source implementations (BKG, go-gnss, de-bkg) rely on `send()` failure, not keepalive tuning

**Rationale**: Industry-proven approach. Since GPS data flows at 1-5 Hz, a dead connection is detected within seconds by the next `send()` failure. No need for aggressive keepalive or custom watchdog timers.

### DR-6: NTRIP Source Table (STR Records) — Deferred

**Decision**: Defer STR record support to post-v2.0 or Phase 6.

**Rationale**:
- All three target casters (RTK2go, Onocoy, rtkdirect) accept connections without STR records
- SNIP/RTK2go auto-generates STR records from the data stream
- Adding STR records means adding config fields for lat/lon, GNSS systems, etc. — scope creep for v2.0
- Can be added later as optional config if needed

### DR-7: Input "No Data" Watchdog — Passive Logging

**Decision**: BroadcastHub tracks `last_data_received_time` and provides passive monitoring:
- Log WARNING after 30 seconds of no data from input source
- Expose `sp_base_relay_input_seconds_since_last_data` Prometheus gauge
- **Do not force reconnect** — input source manages its own connection health
- When input dies, natural cascade handles destination reconnection:
  1. Input dies → no data flows → casters disconnect us after ~12s → destination threads detect → reconnect loops
  2. Input reconnects → data resumes → destination threads reconnect → fresh data flows

**Rationale**: Provides operator visibility through logs and Grafana without adding complexity. The natural cascade of disconnections handles recovery without explicit coordination.
