# SP-Base-Relay Project Brief

## Project Overview
SP-Base-Relay is a Python package that serves as a bridge between RTK GPS base stations and custom RTCM correction servers. It reads RTCM correction messages from various input sources and forwards them to a specific RTCM server using a custom TCP authentication protocol.

## Core Requirements
- **Input Sources**: Support multiple connection methods to RTK GPS base stations
  - Serial UART connection (`/dev/ttyUSB0`, `/dev/ttyS*`)
  - USB Serial connection (USB-to-serial adapters)
  - TCP Serial connection (network-connected base stations, RTKBase integration)
- **Output Destination**: Custom RTCM TCP server
- **Protocol**: Custom authentication with `INIT:username:password*` followed by `$HB$` heartbeat monitoring
- **Data Processing**: Pass-through mode with no RTCM message validation (minimum latency)
- **Error Management**: Robust connection retry with exponential backoff
- **Monitoring**: Prometheus metrics for operational visibility

## Project Goals
1. **Primary Goal**: Create a Python equivalent to RTKLIB's `str2str` tool specifically for the custom RTCM server protocol
2. **Integration Goal**: Design for eventual integration with the Stefal/rtkbase project as a service
3. **Operational Goal**: Provide reliable, low-latency RTCM message relay with comprehensive monitoring
4. **Development Goal**: Maintain >90% unit test coverage following Python 3.10+ standards

## Success Criteria
- Successful authentication and data streaming to custom RTCM server
- Automatic reconnection on connection loss with <1 minute recovery time
- Support for all specified input source types
- Prometheus metrics export for monitoring integration
- Standalone operation with future RTKBase integration capability
- Professional packaging for PyPI distribution

## Target Users
- RTK GPS base station operators requiring connection to the specific RTCM server
- RTKBase users needing custom RTCM server integration
- GNSS professionals requiring reliable correction data relay services

## Technical Constraints
- Must use Python 3.10+ with type hints and PEP8 standards
- Must use UV package management framework
- Must achieve >90% unit test code coverage using Pytest
- Must resolve all pylance and pyright linting issues
- Must operate as standalone package initially (RTKBase integration is future phase)
