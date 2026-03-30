# Technical Context

## Technology Stack

### Core Technologies
- **Python 3.10+**: Modern Python with full type hint support
- **UV Package Manager**: Fast Python package and project manager
- **PyTest**: Testing framework for comprehensive test coverage (>90% target)
- **Type Hints**: Full static typing for better code quality and IDE support
- **PEP8 Standards**: Strict adherence to Python style guidelines

### Key Dependencies
- **PySerial**: Serial port communication for GNSS receiver connections
- **PyYAML**: YAML configuration file parsing
- **Prometheus Client**: Metrics collection and export
- **dbus-fast**: Modern D-Bus library with type hints for Bluetooth integration (Cython-optimized)
- **Socket (stdlib)**: TCP communication with RTCM server and Bluetooth sockets
- **Threading (stdlib)**: Concurrent operations management
- **Asyncio (stdlib)**: Async/await support for D-Bus operations
- **Logging (stdlib)**: Structured logging with rotation support

### Development Tools
- **Pylance**: Python language server for VS Code
- **Pyright**: Static type checker
- **Black**: Code formatter (if needed for PEP8 compliance)
- **Pytest-cov**: Test coverage reporting
- **Pre-commit hooks**: Code quality enforcement

## Development Setup

### Package Management with UV
```bash
# Project initialization
uv init sp-base-relay
cd sp-base-relay

# Dependency management
uv add pyserial pyyaml prometheus-client
uv add --dev pytest pytest-cov black pylint mypy

# Virtual environment activation
source .venv/bin/activate

# Running tests
uv run pytest --cov=src/sp_base_relay --cov-report=html
```

### Project Structure (v2.0)
```
sp-base-relay/
├── pyproject.toml           # UV/Python project configuration
├── uv.lock                  # Dependency lock file
├── README.md                # Project documentation
├── config.example.yaml      # Example configuration (v2 format)
├── docs/
│   ├── v2.1-architecture-plan.md # v2.1 embeddable relay engine plan
│   ├── ublox_gps_webui_planning.md # GPS Web UI integration plan
│   ├── v2-architecture-plan.md  # Full v2.0 architecture document
│   ├── bluetooth-gps-setup.md
│   ├── bluetooth-recovery.md
│   ├── deployment-guide.md
│   └── metrics-guide.md
├── src/
│   └── sp_base_relay/
│       ├── __init__.py
│       ├── main.py          # CLI entry point (v2 with BroadcastHub)
│       ├── config.py        # Config management (v2 destinations: list)
│       ├── logger.py        # Logging setup
│       ├── exceptions.py    # Custom exceptions (+NtripError, DestinationError)
│       ├── metrics.py       # Prometheus metrics (v2 per-destination labels)
│       ├── rtcm_decoder.py  # RTCM frame parsing
│       └── core/
│           ├── __init__.py
│           ├── broadcast_hub.py      # NEW v2 — fan-out to destinations
│           ├── message_filter.py     # NEW v2 — RTCM message filtering
│           ├── rtcm_client.py        # Sure-Path TCP client (unchanged)
│           ├── connection_states.py  # Connection state machine
│           ├── data_pipeline.py      # DEPRECATED (replaced by broadcast_hub)
│           ├── bluetooth_manager.py  # Bluetooth SPP management
│           ├── input_sources/        # Input source strategy pattern
│           │   ├── base_input.py
│           │   ├── serial_input.py
│           │   ├── tcp_input.py
│           │   ├── bluetooth_input.py
│           │   └── input_factory.py
│           └── destinations/         # NEW v2 — destination strategy pattern
│               ├── __init__.py
│               ├── base_destination.py       # ABC for all destinations
│               ├── destination_factory.py    # Factory from config
│               ├── surepath_destination.py   # Wraps RTCMClient
│               ├── ntrip_destination.py      # NTRIP v1/v2 server
│               └── tcp_server_destination.py # Local TCP server
├── tests/
│   ├── unit/                # Unit tests (556+ tests)
│   ├── integration/         # Integration tests
│   ├── manual/              # Manual/hardware tests
│   └── fixtures/            # Test data and mocks
└── tools/
    ├── install.sh / uninstall.sh
    ├── bluetooth/           # Bluetooth helper scripts
    └── systemd/             # Service definitions
```

## v2.0 New Protocols & Technologies (March 2026)

### NTRIP Protocol
SP-Base-Relay v2.0 implements the **NTRIP Server** role (pushes RTCM data to a caster):
- **NTRIP v1.0**: `SOURCE <password>\r\n` → `ICY 200 OK` → raw RTCM stream
- **NTRIP v2.0**: `POST /<mount> HTTP/1.1` + Basic Auth → `HTTP 200` → chunked RTCM stream
- Target casters: RTK2go, Onocoy, rtkdirect
- No additional dependencies needed — built on stdlib `socket` and `base64`

### Configuration v2 Format
- Breaking change: `server:` → `destinations:` list
- Each destination has: name, type (surepath/ntrip/tcp_server), enabled, filter, config
- Filter modes: pass_all / allowlist / blocklist (on RTCM message type IDs)
- Old format detection with clear migration error message

### Per-Destination Metrics
- All metric names changed (breaking from v1)
- Prometheus labels: `{destination="surepath"}`, `{destination="rtk2go"}`, etc.
- New Grafana dashboard template required

## Technical Constraints

### Performance Requirements
- **Latency**: Minimize processing delay for time-critical RTCM corrections
- **Memory**: Efficient memory usage for embedded/edge deployments
- **CPU**: Low CPU overhead to avoid interfering with GNSS processing
- **Network**: Resilient to network interruptions and latency variations

### Reliability Constraints
- **Uptime**: Designed for 24/7 operation with automatic recovery
- **Error Handling**: Graceful degradation without service interruption
- **Resource Cleanup**: Proper cleanup to prevent resource leaks
- **Connection Management**: Robust TCP connection handling

### Compatibility Constraints
- **Python Version**: Must support Python 3.10+ (no older versions)
- **Linux Focus**: Primary target is Linux (Raspberry Pi, Ubuntu, etc.)
- **Serial Hardware**: Support common USB-to-serial chipsets
- **RTKBase Integration**: Future compatibility with RTKBase service patterns

### Code Quality Constraints
- **Type Coverage**: 100% type hint coverage required
- **Test Coverage**: >90% unit test code coverage mandatory
- **Linting**: Zero pylance/pyright issues required
- **Documentation**: Comprehensive docstrings and README

## Dependencies Detail

### Production Dependencies
```toml
[project.dependencies]
python = ">=3.10"
pyserial = ">=3.5"
pyyaml = ">=6.0"
prometheus-client = ">=0.17.0"
dbus-fast = ">=2.0.0"  # Modern D-Bus library with type hints (added Feb 2026)
# Note: Removed pydbus (unmaintained) and pygobject (no longer needed)
```

**Bluetooth/D-Bus Migration (February 2026)**:
- Migrated from `pydbus` (unmaintained, no type hints) to `dbus-fast`
- `dbus-fast` provides full type hint support, resolving 50+ pylance errors
- Cython-optimized for better performance than pydbus
- Asyncio-based with sync wrapper pattern for API compatibility
- Actively maintained by Bluetooth-Devices organization

### Development Dependencies
```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-cov>=4.0.0",
    "pytest-asyncio>=0.21.0",
    "black>=23.0.0",
    "pylint>=2.17.0",
    "mypy>=1.5.0",
    "types-PyYAML",
    "pre-commit>=3.0.0"
]
```

### System Dependencies
- **Linux**: systemd for service management
- **Serial Hardware**: USB-to-serial drivers (typically included)
- **Network**: TCP/IP stack for server communication
- **Monitoring**: Prometheus for metrics collection (optional)

## Tool Usage Patterns

### Development Workflow
1. **Code Development**: VS Code with Pylance for type checking
2. **Testing**: Continuous testing with pytest and coverage reporting  
3. **Quality Checks**: Pre-commit hooks for formatting and linting
4. **Package Building**: UV for dependency management and building
5. **Documentation**: Markdown for all documentation

### Deployment Workflow
1. **Installation**: pip/uv install from PyPI or Git
2. **Configuration**: YAML file setup with example template
3. **Service Setup**: Systemd service installation and configuration
4. **Monitoring**: Prometheus metrics integration
5. **Maintenance**: Log rotation and health monitoring

### Testing Patterns
- **Unit Tests**: Individual component testing with mocks
- **Integration Tests**: End-to-end testing with mock RTCM server
- **Performance Tests**: Latency and throughput validation
- **Compatibility Tests**: Multiple Python versions and platforms

## Integration Considerations

### RTKBase Future Integration
- **Service Patterns**: Compatible with RTKBase's str2str service model
- **Configuration**: Potential integration with settings.conf format
- **Dependencies**: Service ordering and dependency management
- **User Management**: TBD - requires investigation of RTKBase user permissions

### Monitoring Integration
- **Prometheus**: Standard metrics export on configurable port
- **Grafana**: Dashboard templates for operational monitoring
- **Alerting**: Key metrics for alert rule configuration
- **Log Aggregation**: Structured JSON logging for ELK/Loki integration

### Container Support (Future)
- **Docker**: Containerized deployment option
- **Kubernetes**: Service definition and configuration
- **Resource Limits**: CPU and memory constraints
- **Health Checks**: HTTP endpoints for orchestration
