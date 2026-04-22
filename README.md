# SP-RTK-Base-Relay

A Python service that relays RTCM correction data from RTK GPS base stations to **multiple destinations** simultaneously — Sure-Path servers, NTRIP casters, and local TCP clients.

[![CI](https://github.com/rodenj1/sp-rtk-base-relay/actions/workflows/ci.yml/badge.svg)](https://github.com/rodenj1/sp-rtk-base-relay/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/rodenj1/REPLACE_WITH_GIST_ID/raw/sp-rtk-base-relay-coverage.json)](https://github.com/rodenj1/sp-rtk-base-relay/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

> **Coverage badge**: After merging, follow [`docs/ci-setup.md`](docs/ci-setup.md) to create a public gist + PAT, then replace `REPLACE_WITH_GIST_ID` above with your Gist ID.

## Overview

SP-Base-Relay v2.1 is a production-ready multi-destination RTCM relay and **embeddable Python library**. A single GPS input source (TCP, serial, or Bluetooth) feeds correction data to any combination of destinations — proprietary Sure-Path servers, NTRIP v1.0/v2.0 casters (RTK2go, Onocoy, rtkdirect), and local TCP rebroadcast servers.

### Key Features

- 🔀 **Multi-Destination Broadcast**: Fan-out RTCM data to 1–N destinations simultaneously
- 🌐 **NTRIP v1.0 + v2.0**: Push corrections to any NTRIP caster (RTK2go, Onocoy, rtkdirect)
- 📡 **TCP Rebroadcast Server**: Serve corrections to LAN rovers via TCP
- 🔐 **Sure-Path Protocol**: Custom `INIT:user:pass*` auth with `$HB$` heartbeat monitoring
- 🔌 **Multiple Input Sources**: TCP (RTKBase), Serial UART, USB Serial, Bluetooth GPS
- 🎯 **Per-Destination Filtering**: Pass-all, allowlist, or blocklist RTCM message types per destination
- 📊 **Per-Destination Prometheus Metrics**: Individual throughput, errors, queue depth per destination
- 🔄 **Automatic Recovery**: Exponential backoff reconnection per destination — independent fault isolation
- 🔧 **Self-Healing Bluetooth**: Automatic Bluetooth GPS recovery without manual intervention
- 🛡️ **Production Ready**: Systemd integration, structured logging, comprehensive error handling
- 🧪 **Well Tested**: 88% code coverage with 1,106 passing tests
- 🧩 **Embeddable Library** (v2.1): `RelayEngine` API for programmatic control by external applications
- 📢 **Real-Time Events** (v2.1): EventBus with typed events for state change notifications
- 🔌 **Hot Plug Destinations** (v2.1): Add/remove/start/stop destinations while running

## Architecture

```
                              ┌──▶ [SurePath Thread] ──▶ Sure-Path Server
[Input Source] ──▶ [BroadcastHub] ─┤──▶ [NTRIP Thread]   ──▶ RTK2go / Onocoy / etc.
  TCP / Serial       Fan-out    │──▶ [NTRIP Thread]   ──▶ rtkdirect
  / Bluetooth       + Filter    └──▶ [TCP Srv Thread]  ──▶ LAN Rover Clients
                                        │
                                [Prometheus Metrics] ◄──── per-destination labels
```

Each destination runs in its own thread with an independent queue, so a failure in one destination never affects the others.

## Quick Start

### Installation

```bash
git clone https://github.com/rodenj1/sp-rtk-base-relay.git
cd sp-rtk-base-relay
sudo ./tools/install.sh
```

### Configuration

Edit `/etc/sp-rtk-base-relay/config.yaml` (or see `config.example.yaml`):

```yaml
input:
  source: "tcp"
  config:
    host: "192.168.1.100"
    port: 3000

destinations:
  - name: surepath
    type: surepath
    enabled: true
    filter:
      mode: pass_all
    config:
      host: "server.example.com"
      port: 50010
      username: "USER01"
      password: "abc1"

  - name: rtk2go
    type: ntrip
    enabled: true
    filter:
      mode: pass_all
    config:
      caster: "rtk2go.com"
      port: 2101
      mountpoint: "MY_MOUNT"
      password: "my_password"
      version: "2.0"

  - name: local_tcp
    type: tcp_server
    enabled: false
    filter:
      mode: pass_all
    config:
      host: "0.0.0.0"
      port: 5016
      max_clients: 10

metrics:
  enabled: true
  port: 8080

logging:
  level: "INFO"
  format: "json"
```

### Running

```bash
# As a systemd service
sudo systemctl start sp-rtk-base-relay

# Or foreground
sp-rtk-base-relay --config config.yaml --foreground
```

## Destination Types

### Sure-Path (`surepath`)
Custom proprietary protocol with `INIT:user:pass*` authentication and `$HB$` heartbeat monitoring. Wraps the battle-tested v1.x RTCMClient.

### NTRIP (`ntrip`)
Pushes RTCM corrections to NTRIP casters. Supports both protocol versions:
- **v2.0** (default): HTTP POST + Basic auth + chunked transfer encoding
- **v1.0**: SOURCE auth + raw binary streaming

Tested against RTK2go, Onocoy, and rtkdirect.

### TCP Server (`tcp_server`)
Local TCP rebroadcast server for LAN clients. Multiple rovers can connect and receive corrections simultaneously. Features max_clients enforcement and per-client write timeout for backpressure handling.

## Message Filtering

Each destination can independently filter RTCM messages by type ID:

```yaml
filter:
  mode: pass_all          # Forward everything (zero overhead)

filter:
  mode: allowlist         # Only forward these message types
  message_ids: [1005, 1077, 1087, 1097, 1127]

filter:
  mode: blocklist         # Forward everything except these
  message_ids: [4072]     # Drop proprietary messages
```

## Monitoring

### Prometheus Metrics

Per-destination metrics with `{destination="..."}` labels:

| Metric | Type | Description |
|--------|------|-------------|
| `sp_rtk_base_relay_dest_bytes_sent_total` | Counter | Bytes sent per destination |
| `sp_rtk_base_relay_dest_messages_sent_total` | Counter | Messages sent per destination |
| `sp_rtk_base_relay_dest_messages_dropped_total` | Counter | Queue overflow drops per destination |
| `sp_rtk_base_relay_dest_connection_status` | Gauge | Connection state (1/0) per destination |
| `sp_rtk_base_relay_dest_errors_total` | Counter | Errors per destination |
| `sp_rtk_base_relay_dest_queue_depth` | Gauge | Queue depth per destination |
| `sp_rtk_base_relay_input_connection_status` | Gauge | Input source connection state |
| `sp_rtk_base_relay_input_seconds_since_last_data` | Gauge | No-data watchdog |
| `sp_rtk_base_relay_tcp_server_connected_clients` | Gauge | TCP server client count |
| `sp_rtk_base_relay_service_uptime_seconds` | Gauge | Service uptime |

### Grafana Dashboard

Import `templates/grafana_dashboard.json` for a pre-built v2 dashboard with per-destination panels, throughput graphs, and the no-data watchdog.

## Input Sources

| Source | Use Case | Config Key |
|--------|----------|------------|
| `tcp` | RTKBase integration, network base stations | `host`, `port`, `timeout` |
| `serial` | Direct GNSS receiver via UART | `port`, `baudrate` |
| `usb_serial` | USB-to-serial adapters | `port`, `baudrate` |
| `bluetooth` | Bluetooth GPS devices | `device_address`, `channel` |

## Project Structure

```
sp-rtk-base-relay/
├── src/sp_rtk_base_relay/
│   ├── main.py                      # Service orchestration (v2)
│   ├── config.py                    # YAML config with destinations: list
│   ├── metrics.py                   # Per-destination Prometheus metrics
│   ├── exceptions.py                # DestinationError, NtripError, etc.
│   ├── logger.py                    # Structured logging
│   ├── rtcm_decoder.py             # RTCM 3.x frame parser
│   └── core/
│       ├── broadcast_hub.py         # Fan-out coordinator (input → N queues)
│       ├── message_filter.py        # Per-destination RTCM filtering
│       ├── rtcm_client.py           # Sure-Path protocol client
│       ├── connection_states.py     # Connection state machine
│       ├── bluetooth_manager.py     # Bluetooth GPS recovery
│       ├── destinations/
│       │   ├── base_destination.py       # ABC + queue + stats
│       │   ├── destination_factory.py    # Registry-based factory
│       │   ├── surepath_destination.py   # Sure-Path server
│       │   ├── ntrip_destination.py      # NTRIP v1.0 + v2.0
│       │   └── tcp_server_destination.py # Async TCP rebroadcast
│       └── input_sources/
│           ├── base_input.py        # Input ABC
│           ├── tcp_input.py         # TCP input
│           ├── serial_input.py      # Serial input
│           └── bluetooth_input.py   # Bluetooth input
├── tests/                           # 942 tests, 88% coverage
│   ├── unit/                        # Unit tests (26 test files)
│   ├── integration/                 # Hardware integration tests
│   ├── manual/                      # Manual production tests
│   └── fixtures/                    # Mock servers and generators
├── tools/                           # Install/uninstall, systemd, bluetooth
├── templates/                       # Grafana dashboard v2
├── docs/                            # Documentation
│   ├── v2-architecture-plan.md      # Full architecture + design decisions
│   ├── deployment-guide.md          # Installation & deployment
│   ├── metrics-guide.md             # Prometheus metrics reference
│   └── bluetooth-*.md               # Bluetooth GPS guides
└── config.example.yaml              # v2 configuration template
```

## Development

```bash
# Clone and install
git clone https://github.com/rodenj1/sp-rtk-base-relay.git
cd sp-rtk-base-relay
uv sync --all-extras
source .venv/bin/activate

# Run tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/sp_rtk_base_relay --cov-report=html
```

### Code Quality Standards
- Python 3.10+ with modern type hints (`dict`, `list`, `X | None`)
- PEP8 code style, pyright strict mode
- >88% test coverage (942 tests)
- UV package management

## CLI Usage

```
sp-rtk-base-relay [OPTIONS]

Options:
  --version                Show version and exit
  -c, --config PATH        Configuration file path
  --validate               Validate configuration and exit
  --generate-config        Generate example configuration
  --foreground             Run in foreground
  --log-level LEVEL        Override log level
```

## Embedded Usage (v2.1)

SP-Base-Relay can be used as a **Python library** by external applications (e.g., GPS configuration UIs). The `RelayEngine` facade provides full programmatic control:

```python
from sp_rtk_base_relay import RelayEngine
from sp_rtk_base_relay.config import InputConfig, DestinationConfig

# 1. Create engine with input source
engine = RelayEngine(InputConfig(source="tcp", config={"host": "192.168.1.100", "port": 3000}))

# 2. Start with destinations
engine.start([
    DestinationConfig(name="rtk2go", type="ntrip", enabled=True,
                      config={"caster": "rtk2go.com", "port": 2101,
                              "mountpoint": "MY_MOUNT", "password": "pass"}),
])

# 3. Hot-add a destination while running
engine.add_destination(DestinationConfig(
    name="local_tcp", type="tcp_server", enabled=True,
    config={"host": "0.0.0.0", "port": 5016}
))

# 4. Get typed status snapshot
status = engine.get_status()
print(f"Running: {status.is_running}, Destinations: {len(status.destinations)}")

# 5. Subscribe to real-time events
sub = engine.subscribe_events()
event = sub.get_event(timeout=1.0)
if event:
    print(f"Event: {event.event_type} — {event.message}")
sub.close()

# 6. Stop when done (releases serial port for other tools)
engine.stop()
```

### Exported API

| Symbol | Description |
|--------|-------------|
| `RelayEngine` | High-level facade — start/stop/manage relay |
| `EventBus` | Pub/sub event system |
| `EventSubscription` | Per-subscriber event queue (iterable) |
| `RelayEvent` | Typed event (event_type, message, timestamp, payload) |
| `RelayStatus` | Frozen status snapshot |
| `DestinationStatus` | Per-destination status |
| `InputStatus` | Input source status |

See **[Relay Engine API Spec](docs/relay-engine-api-spec.md)** for the full technical specification.

## Migration from v1.x

v2.0 is a **breaking change**. Key differences:

| v1.x | v2.0 |
|------|------|
| `server:` config key | `destinations:` list |
| Single destination | 1–N destinations |
| Global metrics | Per-destination `{destination="..."}` labels |
| `DataPipelineCoordinator` | `BroadcastHub` + `DestinationFactory` |
| v1 Grafana dashboard | v2 dashboard with `$destination` variable |

See `config.example.yaml` for the new format. Old `server:` configs are detected with a clear migration error message.

## Documentation

- **[Relay Engine API Spec](docs/relay-engine-api-spec.md)**: Full v2.1 programmatic API reference
- **[v2.1 Architecture Plan](docs/v2.1-architecture-plan.md)**: Embeddable relay engine design
- **[v2.0 Architecture Plan](docs/v2-architecture-plan.md)**: Multi-destination design with 7 DRs
- **[Configuration Reference](configuration-reference.md)**: Complete config guide (YAML + programmatic)
- **[Deployment Guide](docs/deployment-guide.md)**: Installation and systemd setup
- **[Metrics Guide](docs/metrics-guide.md)**: Prometheus metrics reference
- **[Bluetooth Recovery](docs/bluetooth-recovery.md)**: Self-healing Bluetooth GPS

## License

MIT License — see [LICENSE](LICENSE).

## Project Status

**Current Version**: 2.1.0
- ✅ Multi-destination broadcast (Sure-Path, NTRIP v1.0/v2.0, TCP server)
- ✅ Per-destination message filtering and Prometheus metrics
- ✅ BroadcastHub fan-out architecture with independent fault isolation
- ✅ Embeddable RelayEngine API with EventBus and typed status (v2.1)
- ✅ 1,106 tests, 88% coverage, production-stable

---

**Made with ❤️ for the RTK GPS community**
