# SP-Base-Relay Project Brief

## Project Overview
SP-Base-Relay is a Python package that serves as a multi-destination broadcast relay between RTK GPS base stations and RTCM correction services. It reads RTCM correction messages from various input sources and simultaneously forwards them to multiple destinations including custom RTCM servers (Sure-Path), NTRIP casters (RTK2go, Onocoy, rtkdirect), and local TCP clients.

## Core Requirements

### Input Sources (v1.x — Complete)
- Serial UART connection (`/dev/ttyUSB0`, `/dev/ttyS*`)
- USB Serial connection (USB-to-serial adapters)
- TCP Serial connection (network-connected base stations, RTKBase integration)
- Bluetooth SPP connection (via dbus-fast)

### Output Destinations (v2.0 — In Development)
- **Sure-Path Server**: Custom `INIT:username:password*` auth + `$HB$` heartbeat (v1.x, working)
- **NTRIP Casters**: NTRIP v1.0 (SOURCE) and v2.0 (HTTP POST) server protocol (v2.0, planned)
- **Local TCP Server**: Multi-client broadcast for LAN clients (v2.0, low priority)

### Cross-Cutting
- **Data Processing**: Pass-through mode with optional per-destination RTCM message filtering
- **Error Management**: Per-destination exponential backoff retry with fault isolation
- **Monitoring**: Per-destination Prometheus metrics with `{destination="name"}` labels

## Project Goals
1. **Primary Goal (v1.x ✅)**: Create a Python equivalent to RTKLIB's `str2str` tool for the custom RTCM server protocol
2. **Primary Goal (v2.0)**: Expand to multi-destination broadcast supporting NTRIP casters and local TCP
3. **Integration Goal**: Design for eventual integration with the Stefal/rtkbase project as a service
4. **Operational Goal**: Provide reliable, low-latency RTCM message relay with per-destination monitoring
5. **Development Goal**: Maintain >90% unit test coverage following Python 3.10+ standards

## Success Criteria

### v1.x (All Met ✅)
- Successful authentication and data streaming to custom RTCM server
- Automatic reconnection on connection loss with <1 minute recovery time
- Support for all specified input source types (serial, TCP, Bluetooth)
- Prometheus metrics export for monitoring integration
- 556 unit tests, ~90% coverage, production-running

### v2.0 (Target)
- Simultaneous publishing to 4+ destinations (Sure-Path + 3 NTRIP casters)
- Per-destination RTCM message filtering (pass_all/allowlist/blocklist)
- Independent fault isolation — one destination failure doesn't affect others
- Per-destination Prometheus metrics and Grafana dashboard
- NTRIP v1.0 and v2.0 protocol compliance tested against RTK2go

## Target Users
- RTK GPS base station operators requiring connection to multiple correction services
- RTKBase users needing custom RTCM server and NTRIP caster integration
- GNSS professionals requiring reliable multi-destination correction data relay
- Community contributors to RTK2go, Onocoy, rtkdirect networks

## Technical Constraints
- Must use Python 3.10+ with type hints and PEP8 standards
- Must use UV package management framework
- Must achieve >90% unit test code coverage using Pytest
- Must resolve all pylance and pyright linting issues
- Must operate as standalone package initially (RTKBase integration is future phase)
- v2.0 is a breaking change from v1.x (config format, metrics names)
