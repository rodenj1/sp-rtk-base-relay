# SP-Base-Relay

A Python service that bridges RTK GPS base stations with custom RTCM correction servers, designed for integration with RTKBase and standalone deployments.

[![Python Version](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code Coverage](https://img.shields.io/badge/coverage-89.81%25-brightgreen.svg)](htmlcov/index.html)

## Overview

SP-Base-Relay provides a robust, production-ready solution for relaying RTCM correction data from RTK GPS base stations to custom RTCM servers that use non-standard authentication protocols. It's designed as a Python equivalent to RTKLIB's `str2str` tool with support for custom server protocols.

### Key Features

- 🔌 **Multiple Input Sources**: TCP (RTKBase), Serial UART, USB Serial
- 🔐 **Custom Authentication**: Support for `INIT:username:password*` protocol with `$HB$` heartbeat monitoring
- 🔄 **Automatic Recovery**: Exponential backoff retry with intelligent connection management
- 📊 **Prometheus Metrics**: Comprehensive monitoring and observability
- ⚡ **Low Latency**: Pass-through mode with minimal processing overhead
- 🛡️ **Production Ready**: Systemd integration, comprehensive logging, and error handling
- 🧪 **Well Tested**: 89.81% code coverage with 388 passing tests

## Quick Start

### Installation

**Automated Installation (Recommended):**
```bash
git clone https://github.com/rodenj1/sp-base-relay.git
cd sp-base-relay
sudo ./tools/install.sh
```

**Manual Installation:**
```bash
pip install sp-base-relay
```

### Configuration

Generate a default configuration:
```bash
sp-base-relay --generate-config > config.yaml
```

Edit the configuration with your settings:
```yaml
server:
  host: "rtcm.example.com"
  port: 50010
  username: "YOUR_USERNAME"
  password: "YOUR_PASSWORD"

input:
  source: "tcp"  # or "serial", "usb_serial"
  tcp:
    host: "localhost"
    port: 5015
    timeout: 30

logging:
  level: "INFO"
  format: "json"

metrics:
  enabled: true
  host: "0.0.0.0"
  port: 8080
```

### Running the Service

**As a systemd service (after installation):**
```bash
# Edit configuration
sudo nano /etc/sp-base-relay/config.yaml

# Start service
sudo systemctl start sp-base-relay

# Check status
sudo systemctl status sp-base-relay

# View logs
sudo journalctl -u sp-base-relay -f
```

**As a foreground process:**
```bash
sp-base-relay --config config.yaml --foreground
```

**Validate configuration:**
```bash
sp-base-relay --config config.yaml --validate
```

## Use Cases

### RTKBase Integration
Connect your RTKBase installation to a custom RTCM correction server:
```yaml
input:
  source: "tcp"
  tcp:
    host: "localhost"
    port: 5015  # RTKBase str2str_tcp service
```

### Direct GNSS Connection
Connect directly to a GNSS receiver via serial:
```yaml
input:
  source: "serial"
  serial:
    port: "/dev/ttyUSB0"
    baudrate: 115200
```

### Network-Based Base Station
Connect to a network-accessible base station via TCP:
```yaml
input:
  source: "tcp"
  tcp:
    host: "192.168.1.100"
    port: 5015
```

## Architecture

```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│ Input Sources       │────│ sp-base-relay       │────│ Custom RTCM Server  │
│ - Serial UART       │    │ Python Package      │    │ rtcm.example.com    │
│ - USB Serial        │    │                     │    └─────────────────────┘
│ - TCP (RTKBase)     │    │ ┌─────────────────┐ │
└─────────────────────┘    │ │ Input Manager   │ │
                           │ └─────────────────┘ │
┌─────────────────────┐    │ ┌─────────────────┐ │
│ Prometheus Metrics  │◄───│ │ Data Pipeline   │ │
└─────────────────────┘    │ └─────────────────┘ │
                           │ ┌─────────────────┐ │
                           │ │ RTCM Client     │ │
                           │ └─────────────────┘ │
                           └─────────────────────┘
```

## Features in Detail

### Connection Management
- **Exponential Backoff**: Intelligent retry with 1s → 2s → 4s → 8s → 16s → 32s → 60s progression
- **Heartbeat Monitoring**: 30-second timeout detection with automatic reconnection
- **Connection States**: Robust state machine for connection lifecycle management

### Monitoring & Observability
- **Prometheus Metrics**: 17 comprehensive metrics covering connections, data flow, and health
- **Structured Logging**: JSON/text formats with log rotation
- **Grafana Dashboard**: Pre-built dashboard for visualization
- **Health Checks**: Built-in health monitoring and status reporting

### Performance
- **Pass-Through Mode**: No RTCM validation for minimal latency
- **Low CPU Usage**: < 5% CPU on modern systems
- **Memory Efficient**: ~50MB RAM footprint
- **Thread-Safe**: Proper concurrent operation without race conditions

## Documentation

- **[Deployment Guide](docs/deployment-guide.md)**: Complete installation and deployment instructions
- **[Configuration Reference](configuration-reference.md)**: Detailed configuration options
- **[Metrics Guide](docs/metrics-guide.md)**: Prometheus metrics documentation
- **[RTCM Protocol](RTCM_Connection_Protocol.md)**: Custom server protocol specification
- **[Development Plan](development-plan.md)**: Project development roadmap

## Requirements

- **Python**: 3.10 or higher
- **Operating System**: Linux with systemd (Ubuntu 20.04+, Debian 11+, RHEL 8+)
- **Network**: TCP connectivity to RTCM server
- **Optional**: Serial/USB hardware for direct GNSS connections

## Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/rodenj1/sp-base-relay.git
cd sp-base-relay

# Install with uv (recommended)
uv sync --all-extras

# Activate virtual environment
source .venv/bin/activate

# Run tests
uv run pytest --cov=src/sp_base_relay --cov-report=html
```

### Project Structure

```
sp-base-relay/
├── src/sp_base_relay/          # Main package
│   ├── main.py                 # CLI entry point
│   ├── config.py               # Configuration management
│   ├── logger.py               # Logging setup
│   ├── metrics.py              # Prometheus metrics
│   └── core/                   # Core components
│       ├── rtcm_client.py      # RTCM server connection
│       ├── data_pipeline.py    # Data relay coordination
│       └── input_sources/      # Input source implementations
├── tests/                      # Test suite (388 tests)
│   ├── unit/                   # Unit tests
│   ├── integration/            # Integration tests
│   └── fixtures/               # Test fixtures
├── tools/                      # Deployment tools
│   ├── install.sh              # Installation script
│   ├── uninstall.sh            # Uninstallation script
│   └── systemd/                # Systemd service definition
├── docs/                       # Documentation
└── templates/                  # Grafana dashboards
```

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/sp_base_relay --cov-report=html

# Run specific test file
uv run pytest tests/unit/test_rtcm_client.py

# Run tests matching pattern
uv run pytest -k "test_connection"
```

### Code Quality

```bash
# Type checking
uv run mypy src/sp_base_relay

# Linting
uv run pylint src/sp_base_relay

# Formatting (if needed)
uv run black src/sp_base_relay tests
```

## CLI Usage

```
sp-base-relay [OPTIONS]

Options:
  --version                    Show version and exit
  -c, --config PATH           Configuration file path [default: /etc/sp-base-relay/config.yaml]
  --validate                  Validate configuration and exit
  --generate-config           Generate example configuration and exit
  --foreground                Run in foreground (don't daemonize)
  --log-level LEVEL           Override log level [DEBUG|INFO|WARNING|ERROR|CRITICAL]

Examples:
  # Start with custom config
  sp-base-relay --config /path/to/config.yaml

  # Validate configuration
  sp-base-relay --config config.yaml --validate

  # Generate default config
  sp-base-relay --generate-config > config.yaml

  # Run in foreground with debug logging
  sp-base-relay --config config.yaml --foreground --log-level DEBUG
```

## Monitoring

### Prometheus Metrics Endpoint

```bash
# Access metrics (if enabled)
curl http://localhost:8080/metrics
```

### Key Metrics

- `rtcm_connection_status` - Connection state (1=connected, 0=disconnected)
- `rtcm_messages_sent_total` - Total RTCM messages sent
- `rtcm_bytes_sent_total` - Total bytes transmitted
- `rtcm_connection_attempts_total` - Connection attempts
- `rtcm_authentication_failures_total` - Authentication failures
- `rtcm_heartbeat_last_received` - Last heartbeat timestamp
- `pipeline_messages_processed_total` - Messages processed
- `pipeline_errors_total` - Pipeline errors by type

See [Metrics Guide](docs/metrics-guide.md) for complete documentation.

## Troubleshooting

### Service Won't Start

```bash
# Check service status
sudo systemctl status sp-base-relay

# View recent logs
sudo journalctl -u sp-base-relay -n 50

# Validate configuration
sp-base-relay --config /etc/sp-base-relay/config.yaml --validate
```

### Connection Issues

```bash
# Test RTCM server connectivity
telnet rtcm.example.com 50010

# Check input source (for RTKBase)
sudo systemctl status str2str_tcp

# View connection-related logs
sudo journalctl -u sp-base-relay | grep -i "connection\|auth"
```

### Permission Issues

```bash
# Fix directory permissions
sudo chown -R sp-base-relay:sp-base-relay /var/lib/sp-base-relay
sudo chown -R sp-base-relay:sp-base-relay /var/log/sp-base-relay

# Fix serial port permissions (if using serial)
sudo usermod -a -G dialout sp-base-relay
sudo systemctl restart sp-base-relay
```

For more troubleshooting help, see [Deployment Guide](docs/deployment-guide.md#troubleshooting).

## Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

### Development Standards
- Python 3.10+ with type hints
- PEP8 code style
- >90% test coverage
- Comprehensive documentation

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built as an alternative to RTKLIB's `str2str` for custom RTCM server protocols
- Designed for integration with the [RTKBase](https://github.com/Stefal/rtkbase) project
- Tested with real-world RTK GPS base station deployments

## Support

- **Issues**: [GitHub Issues](https://github.com/rodenj1/sp-base-relay/issues)
- **Documentation**: [docs/](docs/)
- **Examples**: [config.example.yaml](config.example.yaml)

## Project Status

**Current Version**: 1.0.0 (Phase 7 Complete)
- ✅ Core functionality (Phases 1-5)
- ✅ CLI and service management (Phase 7)
- ✅ 89.81% test coverage (388 tests)
- 🔨 PyPI packaging (Phase 8 - upcoming)

---

**Made with ❤️ for the RTK GPS community**
