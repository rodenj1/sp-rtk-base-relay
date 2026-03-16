# System Patterns

## Architecture Overview

### v2.0 Multi-Destination Architecture (March 2026)

SP-Base-Relay v2.0 transforms from a single-destination relay into a multi-destination broadcast system using a fan-out pattern:

```
                              ┌─ Queue ──▶ [SurePath Thread]  ──▶ Sure-Path Server
[Input Thread] ──▶ [BroadcastHub] ─┤─ Queue ──▶ [NTRIP Thread]    ──▶ NTRIP Caster(s)
                              └─ Queue ──▶ [TCP Server Thread] ──▶ Local TCP Clients
```

### Detailed Component View
```
┌─────────────────────┐    ┌──────────────────────────────────────────────────────┐
│ Input Sources       │    │ sp-base-relay v2.0                                  │
│ - Serial UART       │    │                                                      │
│ - USB Serial        │────│─▶ [BroadcastHub]                                    │
│ - TCP (RTKBase)     │    │       │ message_filter per destination               │
│ - Bluetooth SPP     │    │       ├─▶ Queue ─▶ SurePathDestination ──▶ SP Server │
└─────────────────────┘    │       ├─▶ Queue ─▶ NtripDestination   ──▶ RTK2go    │
                           │       ├─▶ Queue ─▶ NtripDestination   ──▶ Onocoy    │
┌─────────────────────┐    │       ├─▶ Queue ─▶ NtripDestination   ──▶ rtkdirect │
│ Prometheus Metrics  │◄───│       └─▶ Queue ─▶ TcpServerDest      ──▶ LAN       │
│ (per-destination)   │    │                                                      │
└─────────────────────┘    │ [MetricsCollector v2 — per-destination labels]       │
                           └──────────────────────────────────────────────────────┘
┌─────────────────────┐
│ Configuration       │
│ - config.yaml v2    │    destinations: list format (breaking change from v1)
│ - per-dest filters  │
└─────────────────────┘
```

### v1.x Architecture (October 2025 — February 2026, DEPRECATED)
```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│ Input Sources       │────│ sp-base-relay       │────│ Custom RTCM Server  │
│ - Serial/TCP/BT     │    │ DataPipelineCoord.  │    │ (Sure-Path only)    │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
```

## Key Design Patterns

### 1. Strategy Pattern — Input Sources & Destinations (v1 + v2)
**Purpose**: Unified interfaces for both input sources AND output destinations
**Implementation**:
```python
# Input sources (v1, unchanged)
class InputSource(ABC):
    @abstractmethod
    def connect(self) -> bool: ...
    @abstractmethod  
    def read_data(self) -> bytes | None: ...
    @abstractmethod
    def disconnect(self) -> None: ...

# Destinations (v2 NEW)
class BaseDestination(ABC):
    @abstractmethod
    def start(self) -> None: ...
    @abstractmethod
    def send(self, data: bytes) -> bool: ...
    @abstractmethod
    def stop(self) -> None: ...
    @abstractmethod
    def get_stats(self) -> DestinationStats: ...
```

### 2. Fan-Out Pattern — BroadcastHub (v2 NEW)
**Purpose**: Single input stream distributed to N destination queues
**Implementation**:
- BroadcastHub reads from input thread, optionally parses RTCM frames
- Per-destination MessageFilter (pass_all/allowlist/blocklist) applied before queueing
- Each destination has its own `queue.Queue` for fault isolation
- `pass_all` mode skips frame parsing entirely for zero overhead

### 3. Observer Pattern — Per-Destination Metrics (v2 Enhanced)
**Purpose**: Decouple metrics collection with per-destination visibility
**Implementation**:
- Each destination exposes `get_stats() -> DestinationStats`
- MetricsCollector v2 polls stats and exports with `{destination="name"}` labels
- Global metrics for input source and service-level health

### 4. Circuit Breaker Pattern — Connection Management (v1 + v2)
**Purpose**: Prevent cascading failures and implement intelligent retry
**Implementation**:
- Track connection failure rates per destination (independent)
- Exponential backoff with configurable initial/max delay per destination
- One destination failure does NOT affect others (thread isolation)

### 5. Factory Pattern — DestinationFactory (v2 NEW)
**Purpose**: Create destination instances from config
**Implementation**:
- Parses `destinations:` list from config v2
- Creates appropriate destination type (surepath/ntrip/tcp_server)
- Validates per-destination config and filter settings

### 6. A+ Pattern — Async Inside Thread (v2 NEW)
**Purpose**: Use asyncio where beneficial while keeping threading architecture
**Implementation**:
- TCP Server destination uses `asyncio.start_server()` inside its own thread
- Elegantly handles many simultaneous clients
- Thread provides isolation; asyncio provides efficient I/O multiplexing

## Component Relationships

### v2.0 Core Service Dependencies
```
SPBaseRelay (main v2)
├── ConfigManager (reads config.yaml v2 — destinations: list)
├── InputSource (created by InputFactory — unchanged)
├── BroadcastHub (NEW — reads input, fans out to destinations)
│   ├── MessageFilter per destination (pass_all/allowlist/blocklist)
│   ├── SurePathDestination (wraps RTCMClient)
│   ├── NtripDestination (NTRIP v1/v2 protocol)
│   ├── NtripDestination (another caster)
│   └── TcpServerDestination (local TCP server)
├── MetricsCollector v2 (per-destination Prometheus labels)
└── SignalHandler (graceful shutdown)
```

### v2.0 Threading Model
- **Main Thread**: Service coordination, signal handling
- **Input Thread**: Continuous reading from input source (unchanged)
- **Broadcast Thread**: Frame parsing, filtering, queue distribution
- **Destination Threads**: One per enabled destination (independent)
  - SurePath thread: Custom INIT auth + $HB$ heartbeat
  - NTRIP thread(s): SOURCE/HTTP POST auth + raw/chunked streaming
  - TCP Server thread: asyncio event loop for multi-client broadcast
- **Metrics Thread**: Prometheus HTTP server (if enabled)

### v1.x Component Dependencies (DEPRECATED)
```
SPBaseRelay (main v1)
├── ConfigManager → InputManager → RTCMClient
├── DataPipelineCoordinator (3-thread: input, coordinator, heartbeat)
└── MetricsCollector (global metrics only)
```

### Error Propagation (v2 Enhanced)
- Input errors: Log and attempt reconnection, continue operation
- Destination errors: Independent per-destination — one failure doesn't affect others
- Configuration errors: Fail fast with clear error messages (detect old v1 format)
- System errors: Graceful shutdown with resource cleanup across all destinations

## Key Technical Decisions

### v1.x Decisions (Still Active)
1. **No RTCM Validation**: Pass-through mode — minimize latency, trust input source
2. **YAML Configuration**: config.yaml with env var overrides
3. **Prometheus Metrics**: Industry-standard monitoring
4. **Exponential Backoff Retry**: Prevent server overload during outages
5. **Threading Over Async**: Simpler debugging, better library compatibility

### v2.0 Decisions (March 2026)
6. **A+ Threading**: Per-destination threads with async-ready interfaces. TCP server uses asyncio internally.
7. **NTRIP v1.0 + v2.0**: Both supported, v2.0 default. ~40 lines delta between implementations.
8. **Per-Destination Filtering**: pass_all (zero overhead) / allowlist / blocklist on RTCM message type IDs
9. **Clean Slate Metrics**: Breaking change — per-destination Prometheus labels replace global metrics
10. **`destinations:` Config Format**: Breaking change from v1 `server:` — list of typed destination configs
11. **BroadcastHub Replaces DataPipeline**: Fan-out pattern instead of single-destination coordinator

## Critical Implementation Paths

### v1.x Sure-Path Authentication (Unchanged)
```
Connect TCP → Send INIT:user:pass* → Receive $HB$ → Start heartbeat monitoring
```

### v2.0 NTRIP v1.0 Server-to-Caster (NEW)
```
Connect TCP → Send SOURCE <password>\r\n → Receive ICY 200 OK → Stream raw RTCM
```

### v2.0 NTRIP v2.0 Server-to-Caster (NEW)
```
Connect TCP → POST /<mount> HTTP/1.1 + Basic Auth → Receive HTTP 200 → Stream chunked RTCM
```

### v2.0 Broadcast Data Flow (NEW)
```
Input Thread → BroadcastHub → [per-dest MessageFilter] → Queue → Destination Thread → Server
```

### Error Recovery (v1 + v2)
```
Detect failure → Log error → Close connections → Wait (exponential backoff) → Retry
```

## Integration Points

### RTKBase Integration (Future)
- **Service Management**: Systemd service compatible with RTKBase patterns
- **Configuration**: Eventual integration with RTKBase settings.conf
- **Logging**: Compatible logging format and location
- **Dependencies**: BindsTo relationship with str2str_tcp.service

### Monitoring Integration
- **Prometheus**: Metrics endpoint at /metrics
- **Logging**: Structured JSON logging for log aggregation
- **Health Checks**: HTTP endpoint for container orchestration

### System Integration
- **Systemd**: Native service definition with proper dependencies
- **Packaging**: Standard Python packaging for pip/UV installation  
- **Configuration**: YAML with environment variable override support
