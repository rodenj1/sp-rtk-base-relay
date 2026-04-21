# SP-Base-Relay Deployment Guide

This guide provides comprehensive instructions for deploying sp-rtk-base-relay v2.0 as a systemd service on Linux systems.

## Prerequisites

### System Requirements
- **Operating System**: Linux with systemd (Ubuntu 20.04+, Debian 11+, RHEL 8+)
- **Python**: Version 3.10 or higher
- **Architecture**: x86_64, ARM64, or ARM (Raspberry Pi compatible)
- **Network**: TCP connectivity to destination servers (Sure-Path, NTRIP casters, etc.)

### Hardware Requirements
- **CPU**: Minimal (< 5% on modern systems)
- **Memory**: ~50MB RAM
- **Storage**: ~100MB for installation
- **Optional**: USB-to-serial adapter for direct GNSS receiver connections

## Installation

### Method 1: Automated (Recommended)

```bash
git clone https://github.com/rodenj1/sp-rtk-base-relay.git
cd sp-rtk-base-relay
sudo ./tools/install.sh
```

The script will:
1. Check system dependencies
2. Create system user and group (`sp-rtk-base-relay`)
3. Create required directories
4. Install the Python package
5. Generate default configuration
6. Install and enable systemd service

### Method 2: Manual

```bash
# Install package
uv pip install --system sp-rtk-base-relay

# Create system user
sudo useradd --system --no-create-home --shell /bin/false sp-rtk-base-relay

# Create directories
sudo mkdir -p /etc/sp-rtk-base-relay /var/lib/sp-rtk-base-relay /var/log/sp-rtk-base-relay
sudo chown sp-rtk-base-relay:sp-rtk-base-relay /var/lib/sp-rtk-base-relay /var/log/sp-rtk-base-relay

# Generate config
sudo sp-rtk-base-relay --generate-config > /etc/sp-rtk-base-relay/config.yaml

# Install systemd service
sudo cp tools/systemd/sp-rtk-base-relay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable sp-rtk-base-relay
```

---

## Configuration

### v2.0 Breaking Change

v2.0 replaces the old `server:` key with a `destinations:` list. If you're upgrading from v1.x, see [Configuration Reference](../configuration-reference.md#migration-from-v1x) for migration instructions.

### Basic Configuration

Edit `/etc/sp-rtk-base-relay/config.yaml`:

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
      username: "YOUR_USERNAME"
      password: "YOUR_PASSWORD"

metrics:
  enabled: true
  port: 8080

logging:
  level: "INFO"
  format: "json"
```

### Multi-Destination Configuration

Add NTRIP casters and/or TCP server alongside Sure-Path:

```yaml
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
      mode: blocklist
      message_ids: [4072]
    config:
      caster: "rtk2go.com"
      port: 2101
      mountpoint: "MY_MOUNT"
      password: "my_password"
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
```

### Input Source Options

#### TCP Input (RTKBase)
```yaml
input:
  source: "tcp"
  config:
    host: "localhost"
    port: 5015
    timeout: 5.0
```

#### Serial Input (Direct GNSS)
```yaml
input:
  source: "serial"
  config:
    port: "/dev/ttyUSB0"
    baudrate: 115200
    timeout: 1.0
```

For complete configuration options, see [Configuration Reference](../configuration-reference.md).

---

## Service Management

### Basic Commands

```bash
sudo systemctl start sp-rtk-base-relay
sudo systemctl stop sp-rtk-base-relay
sudo systemctl restart sp-rtk-base-relay
sudo systemctl status sp-rtk-base-relay
sudo systemctl enable sp-rtk-base-relay    # Auto-start on boot
```

### Viewing Logs

```bash
sudo journalctl -u sp-rtk-base-relay -f           # Follow in real-time
sudo journalctl -u sp-rtk-base-relay -n 50        # Last 50 lines
sudo journalctl -u sp-rtk-base-relay -p err       # Errors only
sudo journalctl -u sp-rtk-base-relay -o short-iso # With timestamps
```

### Configuration Validation

```bash
sp-rtk-base-relay --config /etc/sp-rtk-base-relay/config.yaml --validate
```

---

## Monitoring

### Prometheus Metrics

v2.0 provides **per-destination metrics** with `{destination="..."}` labels:

```bash
curl http://localhost:8080/metrics
```

Key metrics:
- `sp_rtk_base_relay_dest_connection_status{destination="..."}` — per-destination connection state
- `sp_rtk_base_relay_dest_bytes_sent_total{destination="..."}` — per-destination throughput
- `sp_rtk_base_relay_dest_errors_total{destination="..."}` — per-destination errors
- `sp_rtk_base_relay_input_connection_status` — GPS input connection state
- `sp_rtk_base_relay_input_seconds_since_last_data` — no-data watchdog

For complete metrics documentation, see [Metrics Guide](metrics-guide.md).

### Grafana Dashboard

Import `templates/grafana_dashboard.json` for a pre-built v2 dashboard with:
- `$destination` template variable for per-destination filtering
- Per-destination throughput, queue depth, drops, and error panels
- Input watchdog and service uptime panels

### Health Checks

```bash
sudo systemctl is-active sp-rtk-base-relay
curl http://localhost:8080/metrics | grep connection_status
```

---

## Troubleshooting

### Service Won't Start

```bash
sudo systemctl status sp-rtk-base-relay
sudo journalctl -u sp-rtk-base-relay -n 50
sp-rtk-base-relay --config /etc/sp-rtk-base-relay/config.yaml --validate
```

Common issues:
1. **Old v1.x config format** — migrate `server:` to `destinations:` list
2. **Permission errors** — fix directory ownership
3. **Port conflicts** — check if metrics port (8080) is in use
4. **Python version** — ensure Python 3.10+

### Connection Issues

```bash
# Test destination connectivity
telnet server.example.com 50010
telnet rtk2go.com 2101

# Check input source (for RTKBase)
sudo systemctl status str2str_tcp

# View connection logs
sudo journalctl -u sp-rtk-base-relay | grep -i "connection\|auth"
```

### Permission Errors

```bash
sudo chown -R sp-rtk-base-relay:sp-rtk-base-relay /var/lib/sp-rtk-base-relay
sudo chown -R sp-rtk-base-relay:sp-rtk-base-relay /var/log/sp-rtk-base-relay
sudo usermod -a -G dialout sp-rtk-base-relay    # For serial ports
sudo systemctl restart sp-rtk-base-relay
```

---

## Upgrading

### From v1.x to v2.0

1. **Backup your config**:
   ```bash
   sudo cp /etc/sp-rtk-base-relay/config.yaml /etc/sp-rtk-base-relay/config.yaml.v1.bak
   ```

2. **Update the package**:
   ```bash
   cd sp-rtk-base-relay && git pull && sudo ./tools/install.sh
   ```

3. **Migrate config**: Replace `server:` with `destinations:` list format. See [Configuration Reference](../configuration-reference.md#migration-from-v1x).

4. **Update Grafana dashboard**: Import `templates/grafana_dashboard.json` (v2 metrics are incompatible with v1 dashboard).

5. **Update Prometheus alerts**: All metric names have changed. See [Metrics Guide](metrics-guide.md#migration-from-v1x-metrics).

6. **Restart**:
   ```bash
   sudo systemctl restart sp-rtk-base-relay
   ```

### Within v2.x

```bash
cd sp-rtk-base-relay && git pull && sudo ./tools/install.sh
sudo systemctl restart sp-rtk-base-relay
```

---

## Uninstallation

```bash
sudo ./tools/uninstall.sh
```

Or manually:
```bash
sudo systemctl stop sp-rtk-base-relay
sudo systemctl disable sp-rtk-base-relay
sudo rm /etc/systemd/system/sp-rtk-base-relay.service
sudo systemctl daemon-reload
pip3 uninstall sp-rtk-base-relay
sudo userdel sp-rtk-base-relay
```

---

## RTKBase Integration

```yaml
input:
  source: "tcp"
  config:
    host: "localhost"
    port: 5015
    timeout: 5.0
```

Optional systemd dependency:
```ini
# Add to /etc/systemd/system/sp-rtk-base-relay.service [Unit] section
After=str2str_tcp.service
Wants=str2str_tcp.service
```

---

## Security

- Service runs as dedicated `sp-rtk-base-relay` user with minimal privileges
- Config file should be readable only by the service user:
  ```bash
  sudo chmod 640 /etc/sp-rtk-base-relay/config.yaml
  ```
- Use environment variables for sensitive credentials:
  ```bash
  export SP_DEST_SUREPATH_PASSWORD="secret"
  export SP_DEST_RTK2GO_PASSWORD="secret"
  ```
- Restrict metrics endpoint with firewall if needed:
  ```bash
  sudo ufw allow from 192.168.1.0/24 to any port 8080
  ```

---

## Additional Resources

- **[Configuration Reference](../configuration-reference.md)**: Complete config options
- **[Metrics Guide](metrics-guide.md)**: Prometheus metrics documentation
- **[Architecture Plan](v2-architecture-plan.md)**: Full v2 design with design review decisions
- **[Bluetooth Recovery](bluetooth-recovery.md)**: Self-healing Bluetooth GPS
- **[config.example.yaml](../config.example.yaml)**: Annotated example configuration
