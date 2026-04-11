# Product Context

## Why SP-Base-Relay Exists

SP-Base-Relay solves integration problems in the RTK GPS ecosystem where existing tools like RTKLIB's `str2str` cannot handle custom authentication protocols or multi-destination broadcasting to diverse correction services simultaneously.

## Problems It Solves

### 1. Custom Protocol Support (v1.x)
- **Problem**: Standard NTRIP clients and `str2str` don't support custom authentication protocols
- **Solution**: Native support for the specific `INIT:username:password*` authentication sequence
- **Impact**: Enables RTK base stations to connect to previously incompatible correction services

### 2. Multi-Destination Broadcasting (v2.0 — NEW)
- **Problem**: Base station operators need to publish corrections to multiple services simultaneously (Sure-Path, RTK2go, Onocoy, rtkdirect) but `str2str` only supports one output at a time
- **Solution**: Single-source to N-destination broadcast hub with per-destination filtering, independent connection management, and fault isolation
- **Impact**: One relay process replaces 3-4 separate tools, with unified monitoring

### 3. NTRIP Server Integration (v2.0 — NEW)
- **Problem**: Running separate NTRIP server instances per caster is fragile and hard to monitor
- **Solution**: Built-in NTRIP v1.0 and v2.0 server protocol support with per-caster configuration
- **Impact**: Direct NTRIP publishing to RTK2go, Onocoy, rtkdirect from a single service

### 4. RTKBase Integration Gap
- **Problem**: RTKBase users need custom RTCM server connectivity but no existing service supports it
- **Solution**: Drop-in service that integrates with RTKBase's multi-service architecture
- **Impact**: Extends RTKBase's capability without modifying core system

### 5. Reliability and Monitoring
- **Problem**: Network-based correction services need robust connection management
- **Solution**: Advanced retry logic, heartbeat monitoring, and Prometheus metrics (v2: per-destination)
- **Impact**: Production-ready reliability with operational visibility per destination

### 6. Multiple Input Source Support
- **Problem**: Different deployment scenarios require different connection methods
- **Solution**: Unified interface supporting serial, USB, TCP, and Bluetooth inputs
- **Impact**: Single tool handles diverse hardware configurations

### 7. Embeddable Relay Engine (v2.1 — COMPLETE)
- **Problem**: The planned GPS Base Station Web UI needs programmatic control over the relay — starting/stopping relay, managing destinations, observing status — but sp-base-relay v2.0 only exposes a CLI/config-file interface
- **Solution**: v2.1 adds a `RelayEngine` facade API, EventBus for real-time events, typed status snapshots, and dynamic destination management (hot add/remove/start/stop)
- **Impact**: sp-base-relay becomes a reusable Python library that external applications can embed and control in-process, without sacrificing its standalone CLI capability

### 8. GPS Device Management (gps-webui — Planned)
- **Problem**: Base station operators need to identify, configure, and monitor their u-blox GPS receiver (survey-in, RTCM output settings, base station mode) but currently rely on u-center (Windows-only) or manual UBX commands
- **Solution**: gps-webui provides a web-based interface for device identification, configuration, and backup/restore using PyUBX2, with smart port handling (separate UBX+RTCM ports = no relay interruption; shared port = serial handoff)
- **Impact**: Complete browser-based management of the GPS base station — from initial configuration through ongoing monitoring — without needing Windows or u-center

## User Experience Goals

### For RTK Base Station Operators
- **Seamless Integration**: Works alongside existing RTKBase services
- **Reliable Operation**: Automatic recovery from network issues
- **Easy Configuration**: YAML-based configuration with clear documentation
- **Monitoring Visibility**: Prometheus metrics for integration with monitoring stacks

### For GNSS Professionals
- **Low Latency**: Minimal processing delay for time-critical corrections
- **High Reliability**: Robust error handling and automatic reconnection
- **Professional Quality**: Complete logging, metrics, and diagnostic capabilities
- **Flexible Deployment**: Supports various hardware and network configurations

### For System Administrators  
- **Standard Service Management**: Systemd integration for familiar operations
- **Comprehensive Logging**: Structured logging for troubleshooting
- **Health Monitoring**: Clear indicators of service health and performance
- **Easy Installation**: Standard Python packaging with automated setup scripts

## How It Should Work

### Core Workflow (v2.0)
1. **Startup**: Read v2 config, create destinations from `destinations:` list, start BroadcastHub
2. **Data Flow**: Input → BroadcastHub → per-destination MessageFilter → Queue → Destination Thread → Server
3. **Error Recovery**: Per-destination exponential backoff — one failure doesn't affect others
4. **Health Reporting**: Per-destination Prometheus metrics with `{destination="name"}` labels
5. **Graceful Shutdown**: Clean disconnection across all destinations and resource cleanup

### Integration with RTKBase
- **Service Discovery**: Appears in RTKBase service management alongside other `str2str` services
- **Configuration**: Managed through RTKBase settings (future integration)
- **Monitoring**: Health status visible in RTKBase diagnostic interface
- **Resource Sharing**: Uses RTKBase's TCP stream output as input source

### Operational Characteristics
- **Always Available**: Designed for 24/7 operation with automatic recovery
- **Resource Efficient**: Minimal CPU and memory footprint
- **Network Resilient**: Handles network interruptions gracefully
- **Observable**: Rich metrics and logging for operational insight
