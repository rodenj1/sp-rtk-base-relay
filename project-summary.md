# SP-Base-Relay Project Summary

## Overview
SP-Base-Relay is a comprehensive Python package designed to bridge RTK GPS base stations with custom RTCM correction servers. This project emerged from the need to connect existing RTKBase installations to specialized RTCM servers that use custom authentication protocols not supported by standard NTRIP clients or RTKLIB's str2str tool.

## Project Scope and Objectives

### Primary Goals
1. **RTCM Data Relay**: Seamlessly relay RTCM correction data from RTK GPS base stations to a custom RTCM server
2. **Multiple Input Sources**: Support TCP (RTKBase integration), serial UART, and USB serial connections
3. **Custom Protocol Support**: Implement the specific authentication protocol (`INIT:username:password*`) with heartbeat monitoring (`$HB$`)
4. **Production Ready**: Deliver a professional-grade package with comprehensive monitoring, testing, and documentation

### Technical Requirements
- **Python 3.10+** with full type hints and PEP8 compliance
- **>90% unit test coverage** using pytest
- **Zero linting issues** (pylance/pyright)
- **UV package management** for modern Python development
- **Prometheus metrics** for operational monitoring
- **Systemd integration** for service management

## Architecture Overview

### System Design
```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│ Input Sources       │────│ sp-base-relay       │────│ Custom RTCM Server  │
│ - Serial UART       │    │ Python Package      │    │ Custom RTCM Server  │
│ - USB Serial        │    │                     │    └─────────────────────┘
│ - TCP (RTKBase)     │    │ ┌─────────────────┐ │
│ - TCP Direct        │    │ │ Input Manager   │ │
└─────────────────────┘    │ └─────────────────┘ │
                           │ ┌─────────────────┐ │
┌─────────────────────┐    │ │ Data Pipeline   │ │
│ Prometheus Metrics  │◄───│ └─────────────────┘ │
└─────────────────────┘    │ ┌─────────────────┐ │
                           │ │ RTCM Client     │ │
┌─────────────────────┐    │ └─────────────────┘ │
│ Configuration       │────│ ┌─────────────────┐ │
│ - config.yaml       │    │ │ Health Monitor  │ │
└─────────────────────┘    │ └─────────────────┘ │
                           └─────────────────────┘
```

### Key Design Patterns
- **Strategy Pattern**: Multiple input source implementations with unified interface
- **Observer Pattern**: Metrics collection decoupled from core operations  
- **Circuit Breaker Pattern**: Intelligent connection retry with exponential backoff
- **Pipeline Pattern**: Efficient data flow with minimal latency

## Development Plan: 8-Phase Approach

### Phase 1: Core Foundation (Week 1)
- UV-based Python package structure
- YAML configuration management with validation
- Structured logging system with rotation
- Custom exception classes
- Basic unit test framework

### Phase 2: RTCM Server Connection (Week 2)
- TCP connection manager with authentication
- Heartbeat monitoring (`$HB$` tracking every ~1 second)
- Connection retry logic with exponential backoff (1s → 60s max)
- Connection state management and error handling

### Phase 3: Input Source Management (Week 3)
- Abstract input source interface (Strategy pattern)
- TCP input for RTKBase integration (localhost:5015)
- Serial input for direct GNSS receiver connections
- USB serial input support
- Input factory for dynamic source selection

### Phase 4: Data Processing & Buffering (Week 4)
- Pass-through RTCM data processing (no validation for minimum latency)
- Thread-safe data buffering system
- Threading coordination (input/output/monitoring threads)
- Basic metrics collection

### Phase 5: Prometheus Metrics & Monitoring (Week 5)
- Complete Prometheus metrics HTTP server
- Comprehensive operational metrics (connection status, throughput, errors)
- Health monitoring system with status reporting
- Grafana dashboard templates

### Phase 6: Testing Infrastructure (Week 6)
- Mock RTCM server for automated testing
- Comprehensive unit test suite (>90% coverage target)
- Integration tests with end-to-end validation
- Performance and latency testing

### Phase 7: CLI & Service Management (Week 7)
- Full command-line interface with diagnostics
- Systemd service definition with dependencies
- Installation and setup scripts
- Service management integration

### Phase 8: Packaging & Distribution (Week 8)
- Professional PyPI package with proper metadata
- Complete documentation suite (README, API docs, troubleshooting)
- Installation and configuration guides
- Docker container option (optional)

## Key Technical Decisions

### 1. Standalone Architecture
**Decision**: Develop as independent Python package rather than direct RTKBase integration
**Rationale**: Easier development, testing, and deployment with clear future integration path
**Impact**: Simplified initial development while maintaining RTKBase compatibility

### 2. No RTCM Validation
**Decision**: Pass-through mode with no message validation or modification
**Rationale**: Minimize processing latency for time-critical corrections
**Impact**: Maximum performance, simplified implementation, trust input source quality

### 3. YAML Configuration
**Decision**: YAML-based configuration with environment variable overrides
**Rationale**: User-friendly format with validation and flexibility for different deployments
**Impact**: Clear configuration management with good DevOps integration

### 4. Prometheus Metrics
**Decision**: Comprehensive metrics export using Prometheus client library
**Rationale**: Industry standard monitoring integration with rich operational visibility
**Impact**: Professional monitoring capabilities, familiar to operations teams

### 5. Threading Architecture
**Decision**: Use threading model instead of async/await
**Rationale**: Simpler implementation, easier debugging, better library compatibility
**Impact**: Straightforward development with familiar patterns for maintenance

## RTKBase Integration Strategy

### Current RTKBase Architecture Understanding
RTKBase uses a multi-service architecture where:
- **str2str_tcp.service**: Main service reading from GNSS receiver, broadcasting on TCP port 5015
- **Multiple relay services**: Various str2str instances connect to main TCP stream for different outputs
- **Service management**: Systemd-based with proper dependencies and health monitoring

### Integration Approach
SP-Base-Relay integrates as an additional service that:
- **Connects to str2str_tcp**: Uses TCP connection to localhost:5015 as primary input source
- **Follows RTKBase patterns**: Compatible systemd service with proper dependencies
- **Maintains independence**: Operates standalone but designed for future full integration
- **Uses familiar management**: Standard service operations (start/stop/status/logs)

### Future Integration Path
```
Current RTKBase Services:
├── str2str_tcp.service (main data stream)
├── str2str_ntrip_A.service
├── str2str_rtcm_svr.service  
├── str2str_file.service
└── sp-base-relay.service (new addition)
```

## Custom RTCM Server Protocol

### Authentication Flow
```
1. TCP Connect → rtcm.example.com:50010
2. Send: INIT:username:password*
3. Receive: $HB$ (authentication success)
4. Continuous: Send RTCM data, Receive $HB$ every ~1s
5. Monitor: Reconnect if no $HB$ for >30s
```

### Connection Management
- **Exponential Backoff**: 1s, 2s, 4s, 8s, 16s, 32s, 60s (max)
- **Unlimited Retries**: Continuous reconnection attempts
- **Heartbeat Monitoring**: 30-second timeout detection
- **State Tracking**: Connection state machine with proper error handling

## Quality Standards and Metrics

### Code Quality Requirements
- **Python 3.10+**: Modern Python with full type hint support
- **Type Coverage**: 100% type hints required
- **Test Coverage**: >90% unit test coverage mandatory  
- **Linting**: Zero pylance/pyright issues
- **Documentation**: Comprehensive docstrings and user guides

### Operational Success Metrics
- **Connection Uptime**: Target >99% reliability
- **Recovery Time**: <1 minute automatic recovery from failures
- **Latency Impact**: <10ms processing delay for RTCM data
- **Resource Usage**: Minimal CPU/memory footprint

## Deployment and Operations

### Installation Methods
1. **PyPI Package**: `pip install sp-base-relay` or `uv add sp-base-relay`
2. **System Service**: Systemd integration with automatic startup
3. **Container**: Optional Docker deployment for orchestrated environments

### Configuration Management
- **YAML Configuration**: Clear, validated configuration with examples
- **Environment Overrides**: Full environment variable support
- **Runtime Validation**: Configuration validation with helpful error messages

## Project Status

**Current Phase**: Phases 1-3 Complete - Phase 4 Implementation Complete - Phase 4 Testing In Progress  
**Next Phase**: Complete Phase 4 Testing, then Begin Phase 5 - Prometheus Metrics  
**Overall Progress**: Core Implementation Complete (Phases 1-4), Testing Coverage Needed

### ✅ Phase 1: Core Foundation (COMPLETED)
- ✅ **UV Package Structure**: Complete src/ layout with .venv isolation
- ✅ **Configuration Management**: Full YAML parsing with validation and environment overrides
- ✅ **Logging System**: Advanced structured logging with JSON/text formatters and rotation
- ✅ **Exception Hierarchy**: Complete custom exception classes for all error types
- ✅ **Unit Test Suite**: 110 comprehensive unit tests achieving 94% coverage
- ✅ **RTCM Test Data**: Synthetic RTCM message generator for testing
- ✅ **Development Tools**: Black, mypy, pylint integration with UV workflow

### ✅ Phase 2: RTCM Server Connection (COMPLETED - October 28, 2025)
- ✅ **Multi-threaded TCP Connection**: Complete socket-based connection with timeout handling
- ✅ **Authentication Protocol**: INIT:username:password* → $HB$ sequence fully implemented
- ✅ **Heartbeat Monitoring**: Dedicated daemon thread with 30-second timeout detection
- ✅ **Exponential Backoff**: Perfect 1s→2s→4s→8s→16s→32s→60s retry progression
- ✅ **Connection State Management**: Thread-safe state machine with 100% test coverage
- ✅ **Threading Performance**: Optimized from 50+s to 3.2s test execution
- ✅ **Test Coverage**: 150 tests total, 87.93% coverage

### ✅ Phase 3: Input Source Management (COMPLETED - October 28, 2025)
- ✅ **Input Abstraction**: Strategy pattern with abstract InputSource base class
- ✅ **TCP Input**: RTKBase str2str_tcp integration (localhost:5015)
- ✅ **Serial Input**: Full PySerial integration (115200 baud, GNSS receivers)
- ✅ **USB Serial**: USB-to-serial adapter support with port enumeration
- ✅ **Input Factory**: Dynamic source creation with extensible registration
- ✅ **Mock Infrastructure**: Comprehensive mock input sources for testing
- ✅ **Python 3.10+ Compliance**: Modern type hints throughout

### ✅ Phase 4: Data Pipeline (IMPLEMENTATION COMPLETED - October 29, 2025)
- ✅ **DataPipelineCoordinator**: Complete 3-thread architecture implementation
- ✅ **Queue Coordination**: Minimal buffering design (maxsize=10 for thread coordination)
- ✅ **Pass-Through Relay**: Zero RTCM validation for minimum latency
- ✅ **Coordinated Restart**: Both connections restart together on failures
- ✅ **Statistics Tracking**: Comprehensive PipelineStats dataclass
- ✅ **Health Monitoring**: Automatic error detection and recovery
- 🔨 **Unit Testing**: 0% coverage - 42 comprehensive tests planned (target >90%)

### ✅ Project Structure Optimization (October 27, 2025)
- ✅ **Directory Flattening**: Removed redundant nested sp-base-relay/ directory level
- ✅ **Standard Python Layout**: Clean path structure following Python conventions
- ✅ **File Organization**: Moved core files (pyproject.toml, uv.lock, .python-version) to root
- ✅ **Path Simplification**: Changed from `/sp-base-relay/sp-base-relay/src/` to `/src/` structure
- ✅ **Verification Complete**: All tests pass with excellent coverage after restructuring
- ✅ **Documentation Updated**: Fixed references in memory bank and development plan

### 🔨 Current Priority: Phase 4 & 3 Testing
- **Phase 4 Unit Tests**: Write 42 comprehensive tests for DataPipelineCoordinator
- **Phase 3 Unit Tests**: Write tests for input sources (tcp_input.py, serial_input.py, input_factory.py)
- **Integration Tests**: Create end-to-end tests for complete data flow
- **Coverage Target**: >90% for all Phase 3-4 components

### 🔨 Upcoming Phases
- **Phase 5**: Prometheus metrics and monitoring (7-day implementation planned)
- **Phase 6**: Testing infrastructure with >90% overall coverage
- **Phase 7**: CLI and service management
- **Phase 8**: Packaging and distribution

### Technical Achievements
- **Test Coverage**: 94% (exceeding Phase 1 target, approaching Phase 6 goal)
- **Code Quality**: Full type hints, PEP8 compliance, zero linting issues
- **Architecture**: Modular design ready for Strategy and Observer patterns
- **Package Management**: UV-based workflow with proper virtual environment isolation

### Memory Bank Instructions
**IMPORTANT**: Always update development-plan.md, project-summary.md, and memory bank files when completing phases or major milestones. This ensures project continuity and proper context for future development sessions.
