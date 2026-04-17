# Configuration Reference — SP-Base-Relay v2.1

## Overview

SP-Base-Relay v2.1 supports two configuration modes:

1. **YAML Configuration** (standalone CLI) — `destinations:` list for multi-destination broadcast
2. **Programmatic Configuration** (v2.1 embedded library) — Python objects via `RelayEngine` API

The YAML format is a **breaking change** from v1.x — the old `server:` key is no longer supported.

## Configuration File Locations

Configuration is loaded from the first found location:

1. **Command line**: `--config /path/to/config.yaml`
2. **Environment variable**: `SP_BASE_RELAY_CONFIG=/path/to/config.yaml`
3. **User directory**: `~/.config/sp-base-relay/config.yaml`
4. **System directory**: `/etc/sp-base-relay/config.yaml`
5. **Current directory**: `./config.yaml`

---

## Complete Example Configuration

See `config.example.yaml` for a full annotated example. Below is a minimal production configuration:

```yaml
input:
  source: "tcp"
  config:
    host: "192.168.1.100"
    port: 3000
    timeout: 5.0

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

metrics:
  enabled: true
  host: "0.0.0.0"
  port: 8080

logging:
  level: "INFO"
  format: "json"
  file: "/var/log/sp-base-relay.log"
  max_size_mb: 50
  backup_count: 3

service:
  daemon: false
```

---

## Configuration Sections

### Input Source (`input:`)

Configures the single GPS data source. Only one source type can be active.

```yaml
input:
  source: "<type>"          # Required: tcp, serial, usb_serial, bluetooth
  config:                    # Required: source-specific parameters
    <key>: <value>
```

#### TCP Input (RTKBase / Network Base Station)
```yaml
input:
  source: "tcp"
  config:
    host: "192.168.1.100"   # Required: Host to connect to
    port: 3000              # Required: Port (1-65535)
    timeout: 5.0            # Connection/read timeout in seconds (>0)
    buffer_size: 4096       # Read buffer size in bytes
```

#### Serial Input (Direct GNSS Receiver)
```yaml
input:
  source: "serial"           # or "usb_serial"
  config:
    port: "/dev/ttyUSB0"    # Required: Serial device path
    baudrate: 115200         # Required: 9600-921600
    bytesize: 8             # Data bits: 5, 6, 7, 8
    parity: "N"             # N=None, E=Even, O=Odd, M=Mark, S=Space
    stopbits: 1             # 1, 1.5, or 2
    timeout: 1.0            # Read timeout in seconds (>0)
    rtscts: false           # Hardware flow control
    xonxoff: false          # Software flow control
```

#### Bluetooth Input
```yaml
input:
  source: "bluetooth"
  config:
    device_address: "AA:BB:CC:DD:EE:FF"
    channel: 1
```

---

### Destinations (`destinations:`)

A list of 1 or more destinations. Each destination receives RTCM data from the input source. At least one must be `enabled: true`.

Every destination entry has the same top-level structure:

```yaml
destinations:
  - name: "<unique_name>"      # Required: alphanumeric + underscores/hyphens
    type: "<destination_type>"  # Required: surepath, ntrip, or tcp_server
    enabled: true               # Optional: default true
    filter:                     # Optional: default pass_all
      mode: "pass_all"          # pass_all, allowlist, or blocklist
      message_ids: []           # Required if allowlist/blocklist
    config:                     # Required: type-specific parameters
      <key>: <value>
```

**Duplicate names are not allowed.** Names are used as Prometheus metric labels.

#### Filter Configuration

| Mode | Description | `message_ids` Required? |
|------|-------------|------------------------|
| `pass_all` | Forward all messages (zero overhead — no frame parsing) | No (must be empty) |
| `allowlist` | Only forward messages with these RTCM type IDs | Yes |
| `blocklist` | Forward all messages except these RTCM type IDs | Yes |

```yaml
# Examples:
filter:
  mode: pass_all

filter:
  mode: allowlist
  message_ids: [1005, 1077, 1087, 1097, 1127, 1230]

filter:
  mode: blocklist
  message_ids: [4072]          # Drop proprietary messages
```

---

#### Sure-Path Destination (`type: surepath`)

Custom proprietary protocol with `INIT:user:pass*` authentication and `$HB$` heartbeat monitoring.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | — | **Required.** Server hostname or IP |
| `port` | int | 50010 | Server port (1-65535) |
| `username` | string | — | **Required.** Authentication username |
| `password` | string | — | **Required.** Authentication password |
| `connection_timeout` | int | 10 | TCP connection timeout (seconds, >0) |
| `read_timeout` | int | 30 | Socket read timeout (seconds, >0) |
| `heartbeat_timeout` | int | 30 | `$HB$` heartbeat timeout (seconds, >0) |
| `retry_initial_delay` | int | 15 | Initial reconnect delay (seconds, >0) |
| `retry_max_delay` | int | 60 | Max reconnect delay (≥ initial) |
| `retry_multiplier` | float | 2.0 | Backoff multiplier (>1.0) |

```yaml
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
    heartbeat_timeout: 30
    retry_initial_delay: 15
    retry_max_delay: 60
```

#### NTRIP Destination (`type: ntrip`)

Pushes RTCM corrections to an NTRIP caster. Supports v1.0 and v2.0 protocols.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `caster` | string | — | **Required.** Caster hostname (e.g. `rtk2go.com`) |
| `port` | int | 2101 | Caster port (1-65535) |
| `mountpoint` | string | — | **Required.** Mount point name |
| `password` | string | — | **Required.** Caster password |
| `username` | string | `""` | Optional username (some casters require it) |
| `version` | string | `"2.0"` | Protocol version: `"1.0"` or `"2.0"` |
| `connection_timeout` | int | 15 | TCP connection timeout (seconds, >0) |
| `retry_initial_delay` | int | 10 | Initial reconnect delay (seconds, >0) |
| `retry_max_delay` | int | 120 | Max reconnect delay (≥ initial) |
| `retry_multiplier` | float | 2.0 | Backoff multiplier (>1.0) |

```yaml
- name: rtk2go
  type: ntrip
  enabled: true
  filter:
    mode: blocklist
    message_ids: [4072]
  config:
    caster: "rtk2go.com"
    port: 2101
    mountpoint: "MY_MOUNT"
    password: "my_password"
    version: "2.0"
    retry_initial_delay: 10
    retry_max_delay: 120
```

#### TCP Server Destination (`type: tcp_server`)

Local TCP rebroadcast server for LAN clients (rovers, logging tools, etc.).

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `host` | string | `"0.0.0.0"` | Bind address |
| `port` | int | 5016 | Listen port (1-65535) |
| `max_clients` | int | 10 | Maximum simultaneous clients (≥1) |

```yaml
- name: local_tcp
  type: tcp_server
  enabled: false
  filter:
    mode: pass_all
  config:
    host: "0.0.0.0"
    port: 5016
    max_clients: 10
```

---

### Metrics (`metrics:`)

Prometheus metrics HTTP endpoint configuration.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enabled` | bool | `true` | Enable/disable metrics server |
| `host` | string | `"0.0.0.0"` | Bind address |
| `port` | int | 8080 | HTTP server port (1-65535) |
| `path` | string | `"/metrics"` | Endpoint URL path (must start with `/`) |

```yaml
metrics:
  enabled: true
  host: "0.0.0.0"
  port: 8080
  path: "/metrics"
```

Access: `http://localhost:8080/metrics`

---

### Logging (`logging:`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `level` | string | `"INFO"` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` |
| `format` | string | `"json"` | `json` (structured) or `text` (human-readable) |
| `file` | string\|null | `"/var/log/sp-base-relay.log"` | Log file path (`null` for console only) |
| `max_size_mb` | int | 50 | Max log file size in MB (>0) |
| `backup_count` | int | 3 | Rotated backup files to keep (≥0) |

---

### Service (`service:`)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `daemon` | bool | `false` | Run as background daemon |
| `pid_file` | string | `"/var/run/sp-base-relay.pid"` | PID file location |
| `user` | string | `"sp-base-relay"` | Service user |
| `group` | string | `"sp-base-relay"` | Service group |

---

## Environment Variable Overrides

### Global Overrides

| Environment Variable | Config Path |
|---------------------|-------------|
| `SP_INPUT_SOURCE` | `input.source` |
| `SP_INPUT_TCP_HOST` | `input.config.host` |
| `SP_INPUT_TCP_PORT` | `input.config.port` |
| `SP_INPUT_TCP_TIMEOUT` | `input.config.timeout` |
| `SP_INPUT_SERIAL_PORT` | `input.config.port` |
| `SP_INPUT_SERIAL_BAUDRATE` | `input.config.baudrate` |
| `SP_METRICS_ENABLED` | `metrics.enabled` |
| `SP_METRICS_PORT` | `metrics.port` |
| `SP_LOG_LEVEL` | `logging.level` |
| `SP_LOG_FORMAT` | `logging.format` |

### Per-Destination Overrides

Use the pattern `SP_DEST_<NAME>_<FIELD>` where `<NAME>` is the destination name (uppercased):

```bash
# Override surepath destination host
export SP_DEST_SUREPATH_HOST="override.example.com"

# Override rtk2go destination password
export SP_DEST_RTK2GO_PASSWORD="secret123"

# Override NTRIP port
export SP_DEST_ONOCOY_PORT="2102"
```

---

## Configuration Validation

### CLI Validation

```bash
# Validate configuration file
sp-base-relay --config config.yaml --validate

# Generate default config
sp-base-relay --generate-config > config.yaml
```

### Key Validation Rules

- **Old format detection**: If `server:` key is present, a clear migration error is shown (DR-4)
- **Old input format**: `input.type`, `input.tcp`, `input.serial` patterns are detected and rejected
- **At least one enabled destination** is required
- **Duplicate destination names** are not allowed
- **Filter consistency**: `pass_all` mode must have empty `message_ids`; `allowlist`/`blocklist` require non-empty `message_ids`

---

## Migration from v1.x

v2.0 uses `destinations:` list instead of `server:` key. When a v1.x config is detected, a clear error message with migration instructions is displayed.

**v1.x format (no longer supported):**
```yaml
server:
  host: "server.example.com"
  port: 50010
  username: "USER01"
  password: "abc1"

input:
  type: "tcp"
  tcp:
    host: "127.0.0.1"
    port: 5015
```

**v2.0 equivalent:**
```yaml
input:
  source: "tcp"
  config:
    host: "127.0.0.1"
    port: 5015

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
```

---

## Configuration Examples

### Multi-Destination Production
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
      host: "rtcm.example.com"
      port: 50010
      username: "PROD_USER"
      password: "secure_pass"

  - name: rtk2go
    type: ntrip
    enabled: true
    filter:
      mode: blocklist
      message_ids: [4072]
    config:
      caster: "rtk2go.com"
      port: 2101
      mountpoint: "MY_MOUNT"
      password: "rtk2go_pass"
      version: "2.0"

  - name: onocoy
    type: ntrip
    enabled: true
    filter:
      mode: pass_all
    config:
      caster: "servers.onocoy.com"
      port: 2101
      mountpoint: "ONOCOY_MOUNT"
      password: "onocoy_pass"
      version: "2.0"

  - name: local_tcp
    type: tcp_server
    enabled: true
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
  file: "/var/log/sp-base-relay.log"
  max_size_mb: 100
  backup_count: 7
```

### Direct Serial Connection
```yaml
input:
  source: "serial"
  config:
    port: "/dev/ttyUSB0"
    baudrate: 115200
    bytesize: 8
    parity: "N"
    stopbits: 1
    timeout: 2.0

destinations:
  - name: surepath
    type: surepath
    enabled: true
    filter:
      mode: pass_all
    config:
      host: "server.example.com"
      port: 50010
      username: "SERIAL_USER"
      password: "serial_pass"

logging:
  level: "DEBUG"
  format: "text"
```

### Container Deployment
```yaml
input:
  source: "tcp"
  config:
    host: "rtkbase"           # Container hostname
    port: 5015

destinations:
  - name: surepath
    type: surepath
    enabled: true
    filter:
      mode: pass_all
    config:
      host: "rtcm-server.example.com"
      port: 50010
      username: "container_user"
      password: "container_pass"

metrics:
  enabled: true
  port: 8080

logging:
  level: "INFO"
  format: "json"
  file: null                  # Console only for container logs
```

---

## Loading Priority

Configuration values are resolved in this order (later overrides earlier):

1. Default values (from dataclass defaults)
2. Configuration file (YAML)
3. Environment variables (`SP_*`)
4. Command line arguments (`--log-level`, etc.)

---

## Troubleshooting

### Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `Old v1.x configuration format detected` | Config has `server:` key | Migrate to `destinations:` list format |
| `Old input configuration format detected` | Config uses `input.type` or `input.tcp` | Use `input.source` + `input.config` |
| `destinations list is required` | Missing `destinations:` key | Add at least one destination |
| `At least one destination must be enabled` | All destinations have `enabled: false` | Enable at least one |
| `Duplicate destination name` | Two destinations share a name | Use unique names |

### File Permissions
```bash
sudo chown sp-base-relay:sp-base-relay /etc/sp-base-relay/config.yaml
sudo chmod 640 /etc/sp-base-relay/config.yaml
```

---

## Programmatic Configuration (v2.1)

When using sp-base-relay as an **embedded Python library**, no YAML file is needed. Configuration is done via Python dataclass objects.

### InputConfig

```python
from sp_base_relay.config import InputConfig

# TCP input
input_cfg = InputConfig(source="tcp", config={"host": "192.168.1.100", "port": 3000})

# Serial input
input_cfg = InputConfig(source="serial", config={"port": "/dev/ttyUSB0", "baudrate": 57600})

# Bluetooth input
input_cfg = InputConfig(source="bluetooth", config={"device_address": "AA:BB:CC:DD:EE:FF", "channel": 1})
```

### DestinationConfig

```python
from sp_base_relay.config import DestinationConfig

# Sure-Path destination
surepath = DestinationConfig(
    name="surepath",
    type="surepath",
    enabled=True,
    config={"host": "server.example.com", "port": 50010,
            "username": "USER01", "password": "abc1"},
)

# NTRIP destination
rtk2go = DestinationConfig(
    name="rtk2go",
    type="ntrip",
    enabled=True,
    filter={"mode": "blocklist", "message_ids": [4072]},
    config={"caster": "rtk2go.com", "port": 2101,
            "mountpoint": "MY_MOUNT", "password": "pass", "version": "2.0"},
)

# TCP server destination
local_tcp = DestinationConfig(
    name="local_tcp",
    type="tcp_server",
    enabled=True,
    config={"host": "0.0.0.0", "port": 5016, "max_clients": 10},
)
```

### RelayEngine Usage

```python
from sp_base_relay import RelayEngine

engine = RelayEngine(input_cfg)

# Start with initial destinations
engine.start([surepath, rtk2go])

# Hot-add destinations while running
engine.add_destination(local_tcp)

# Hot-remove destinations while running
engine.remove_destination("local_tcp")

# Per-destination start/stop (pause without removing)
engine.stop_destination("rtk2go")
engine.start_destination("rtk2go")

# Status and events
status = engine.get_status()
sub = engine.subscribe_events()

# Stop the engine (releases serial port)
engine.stop()
```

See **[Relay Engine API Spec](docs/relay-engine-api-spec.md)** for the complete API reference.
