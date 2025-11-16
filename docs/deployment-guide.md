# SP-Base-Relay Deployment Guide

This guide provides comprehensive instructions for deploying sp-base-relay as a systemd service on Linux systems.

## Prerequisites

### System Requirements
- **Operating System**: Linux with systemd (Ubuntu 20.04+, Debian 11+, RHEL 8+, etc.)
- **Python**: Version 3.10 or higher
- **Architecture**: x86_64, ARM64, or ARM (Raspberry Pi compatible)
- **Network**: TCP connectivity to RTCM server

### Software Requirements
- Python 3.10+
- systemd
- pip3 or uv (Python package manager)
- sudo/root access for installation

### Hardware Requirements
- **CPU**: Minimal (< 5% on modern systems)
- **Memory**: ~50MB RAM
- **Storage**: ~100MB for installation
- **Network**: Stable internet connection for RTCM server communication

For serial/USB connections:
- USB-to-serial adapter (optional, for direct GNSS receiver connections)
- Serial port access permissions

## Installation Methods

### Method 1: Automated Installation (Recommended)

The automated installation script handles all setup steps including user creation, directory setup, and service installation.

**Step 1: Download or clone the repository**
```bash
# Clone from GitHub
git clone https://github.com/rodenj1/sp-base-relay.git
cd sp-base-relay

# Or download and extract the release
wget https://github.com/rodenj1/sp-base-relay/archive/refs/tags/v1.0.0.tar.gz
tar -xzf v1.0.0.tar.gz
cd sp-base-relay-1.0.0
```

**Step 2: Run the installation script**
```bash
sudo ./tools/install.sh
```

The installation script will:
1. ✅ Check system dependencies
2. ✅ Create system user and group (`sp-base-relay`)
3. ✅ Create required directories
4. ✅ Install the Python package
5. ✅ Generate default configuration
6. ✅ Install systemd service
7. ✅ Enable service for auto-start

**Step 3: Configure the service**
```bash
sudo nano /etc/sp-base-relay/config.yaml
```

Edit the configuration with your specific settings (see Configuration section below).

**Step 4: Start the service**
```bash
sudo systemctl start sp-base-relay
```

**Step 5: Verify operation**
```bash
# Check service status
sudo systemctl status sp-base-relay

# View logs
sudo journalctl -u sp-base-relay -f
```

### Method 2: Manual Installation

If you prefer manual installation or need custom setup:

**Step 1: Install the package**
```bash
# Using pip
pip3 install sp-base-relay

# Using uv
uv pip install --system sp-base-relay
```

**Step 2: Create system user**
```bash
sudo useradd --system --no-create-home --shell /bin/false sp-base-relay
```

**Step 3: Create directories**
```bash
# Configuration directory
sudo mkdir -p /etc/sp-base-relay
sudo chmod 755 /etc/sp-base-relay

# Data directory
sudo mkdir -p /var/lib/sp-base-relay
sudo chown sp-base-relay:sp-base-relay /var/lib/sp-base-relay

# Log directory
sudo mkdir -p /var/log/sp-base-relay
sudo chown sp-base-relay:sp-base-relay /var/log/sp-base-relay
```

**Step 4: Generate and customize configuration**
```bash
sudo sp-base-relay --generate-config > /etc/sp-base-relay/config.yaml
sudo nano /etc/sp-base-relay/config.yaml
```

**Step 5: Install systemd service**
```bash
# Copy service file
sudo cp tools/systemd/sp-base-relay.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable and start service
sudo systemctl enable sp-base-relay
sudo systemctl start sp-base-relay
```

## Configuration

### Basic Configuration

The configuration file is located at `/etc/sp-base-relay/config.yaml`. Here's a minimal configuration:

```yaml
# RTCM Server Configuration
server:
  host: "rtcm.example.com"
  port: 50010
  username: "YOUR_USERNAME"
  password: "YOUR_PASSWORD"

# Input Source Configuration
input:
  source: "tcp"  # Options: tcp, serial, usb_serial
  tcp:
    host: "localhost"
    port: 5015
    timeout: 30

# Logging Configuration
logging:
  level: "INFO"
  format: "json"
  
# Metrics Configuration (optional)
metrics:
  enabled: true
  host: "0.0.0.0"
  port: 8080
```

### Input Source Options

#### TCP Input (RTKBase Integration)
```yaml
input:
  source: "tcp"
  tcp:
    host: "localhost"
    port: 5015
    timeout: 30
```

#### Serial Input (Direct GNSS Connection)
```yaml
input:
  source: "serial"
  serial:
    port: "/dev/ttyUSB0"
    baudrate: 115200
    timeout: 1.0
    bytesize: 8
    parity: "N"
    stopbits: 1
```

#### USB Serial Input
```yaml
input:
  source: "usb_serial"
  serial:
    port: "/dev/ttyUSB0"
    baudrate: 115200
    timeout: 1.0
```

### Advanced Configuration

For complete configuration options, see `configuration-reference.md`.

## Service Management

### Basic Commands

```bash
# Start service
sudo systemctl start sp-base-relay

# Stop service
sudo systemctl stop sp-base-relay

# Restart service
sudo systemctl restart sp-base-relay

# Check status
sudo systemctl status sp-base-relay

# Enable auto-start on boot
sudo systemctl enable sp-base-relay

# Disable auto-start
sudo systemctl disable sp-base-relay
```

### Viewing Logs

```bash
# View recent logs
sudo journalctl -u sp-base-relay

# Follow logs in real-time
sudo journalctl -u sp-base-relay -f

# View logs since boot
sudo journalctl -u sp-base-relay -b

# View logs with timestamps
sudo journalctl -u sp-base-relay -o short-iso

# View only errors
sudo journalctl -u sp-base-relay -p err
```

### Configuration Validation

Before starting the service, validate your configuration:

```bash
sp-base-relay --config /etc/sp-base-relay/config.yaml --validate
```

## Monitoring

### Prometheus Metrics

If metrics are enabled, they are available at:
```
http://localhost:8080/metrics
```

Key metrics include:
- `rtcm_connection_status` - Connection state (1=connected, 0=disconnected)
- `rtcm_messages_sent_total` - Total messages sent
- `rtcm_bytes_sent_total` - Total bytes sent
- `rtcm_connection_attempts_total` - Connection attempts
- `rtcm_heartbeat_last_received` - Last heartbeat timestamp

For complete metrics documentation, see `docs/metrics-guide.md`.

### Health Checks

Check service health:
```bash
# Service status
sudo systemctl is-active sp-base-relay

# Detailed status
sudo systemctl status sp-base-relay

# Check if metrics endpoint is accessible (if enabled)
curl http://localhost:8080/metrics
```

### Grafana Dashboard

A pre-built Grafana dashboard is available in `templates/grafana_dashboard.json`. Import this dashboard to visualize:
- Connection status
- Data throughput
- Error rates
- Heartbeat freshness
- Service uptime

## Troubleshooting

### Service Won't Start

**Check systemd status:**
```bash
sudo systemctl status sp-base-relay
```

**Check logs for errors:**
```bash
sudo journalctl -u sp-base-relay -n 50
```

**Common issues:**
1. **Configuration errors**: Validate config with `--validate` flag
2. **Permission errors**: Ensure directories are owned by `sp-base-relay` user
3. **Port conflicts**: Check if metrics port (8080) is already in use
4. **Python version**: Ensure Python 3.10+ is installed

### Connection Issues

**RTCM Server Connection Failures:**
```bash
# Test network connectivity
ping rtcm.example.com

# Test port accessibility
telnet rtcm.example.com 50010

# Check logs for authentication errors
sudo journalctl -u sp-base-relay | grep -i auth
```

**Input Source Connection Failures:**
```bash
# For TCP input, verify RTKBase is running
sudo systemctl status str2str_tcp

# For serial input, check device permissions
ls -l /dev/ttyUSB0
sudo usermod -a -G dialout sp-base-relay

# Check logs for input errors
sudo journalctl -u sp-base-relay | grep -i input
```

### High CPU/Memory Usage

Monitor resource usage:
```bash
# Check process stats
ps aux | grep sp-base-relay

# Monitor in real-time
top -p $(pgrep -f sp-base-relay)

# Check for excessive logging
sudo journalctl -u sp-base-relay --since "1 hour ago" | wc -l
```

If experiencing high resource usage:
1. Reduce log level from DEBUG to INFO
2. Check for network issues causing excessive retries
3. Verify input source is not flooding with data

### Permission Errors

**Fix directory permissions:**
```bash
sudo chown -R sp-base-relay:sp-base-relay /var/lib/sp-base-relay
sudo chown -R sp-base-relay:sp-base-relay /var/log/sp-base-relay
sudo chmod 755 /var/lib/sp-base-relay
sudo chmod 755 /var/log/sp-base-relay
```

**Fix serial port permissions:**
```bash
sudo usermod -a -G dialout sp-base-relay
sudo systemctl restart sp-base-relay
```

## Upgrading

### Upgrade Package

```bash
# Using pip
pip3 install --upgrade sp-base-relay

# Using uv
uv pip install --system --upgrade sp-base-relay

# Restart service to use new version
sudo systemctl restart sp-base-relay
```

### Upgrade Configuration

When upgrading, check if new configuration options are available:
```bash
# Generate new default config
sp-base-relay --generate-config > /tmp/new-config.yaml

# Compare with existing config
diff /etc/sp-base-relay/config.yaml /tmp/new-config.yaml

# Merge new options as needed
sudo nano /etc/sp-base-relay/config.yaml
```

## Uninstallation

### Automated Uninstallation

```bash
sudo ./tools/uninstall.sh
```

This script will:
1. Stop and disable the service
2. Remove systemd service file
3. Optionally remove the package
4. Optionally remove user and group
5. Optionally remove data directories

### Manual Uninstallation

```bash
# Stop and disable service
sudo systemctl stop sp-base-relay
sudo systemctl disable sp-base-relay

# Remove service file
sudo rm /etc/systemd/system/sp-base-relay.service
sudo systemctl daemon-reload

# Uninstall package
pip3 uninstall sp-base-relay

# Remove user and group
sudo userdel sp-base-relay
sudo groupdel sp-base-relay

# Remove directories (optional - contains logs and config)
sudo rm -rf /etc/sp-base-relay
sudo rm -rf /var/lib/sp-base-relay
sudo rm -rf /var/log/sp-base-relay
```

## RTKBase Integration

### Integration with RTKBase

SP-Base-Relay is designed to work alongside RTKBase installations:

**1. Ensure RTKBase str2str_tcp service is running:**
```bash
sudo systemctl status str2str_tcp
```

**2. Configure sp-base-relay to use RTKBase TCP stream:**
```yaml
input:
  source: "tcp"
  tcp:
    host: "localhost"
    port: 5015  # RTKBase str2str_tcp port
    timeout: 30
```

**3. Optional: Add systemd dependency (if desired):**
Edit `/etc/systemd/system/sp-base-relay.service`:
```ini
[Unit]
After=str2str_tcp.service
Wants=str2str_tcp.service
```

Then reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart sp-base-relay
```

## Security Considerations

### File Permissions

The service runs as a dedicated `sp-base-relay` user with minimal privileges:
- Configuration files owned by root (read-only for service)
- Data directories owned by service user
- No shell access for service user

### Network Security

- RTCM server credentials stored in config file (protect access)
- Consider using firewall rules to restrict access
- Metrics endpoint (if enabled) accessible on configured host/port

### Best Practices

1. **Protect configuration file:**
   ```bash
   sudo chmod 644 /etc/sp-base-relay/config.yaml
   ```

2. **Rotate credentials periodically**

3. **Monitor service logs for unauthorized access attempts**

4. **Use firewall to restrict metrics endpoint if needed:**
   ```bash
   sudo ufw allow from 192.168.1.0/24 to any port 8080
   ```

## Performance Tuning

### Minimal Latency Configuration

For time-critical RTCM corrections:
```yaml
logging:
  level: "WARNING"  # Reduce logging overhead
  
metrics:
  enabled: false  # Disable metrics if not needed
```

### High Availability Configuration

For production deployments:
```yaml
server:
  connection_timeout: 10
  retry_initial_delay: 1
  retry_max_delay: 60
  
logging:
  level: "INFO"
  rotation:
    max_bytes: 10485760  # 10MB
    backup_count: 5
```

## Support

For issues, questions, or contributions:
- GitHub Issues: https://github.com/rodenj1/sp-base-relay/issues
- Documentation: https://github.com/rodenj1/sp-base-relay/tree/main/docs
- Example Configurations: `config.example.yaml`

## Additional Resources

- **Configuration Reference**: `docs/configuration-reference.md`
- **Metrics Guide**: `docs/metrics-guide.md`
- **RTCM Protocol**: `RTCM_Connection_Protocol.md`
- **Development Plan**: `development-plan.md`
