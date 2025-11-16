# System Patterns

## Architecture Overview

SP-Base-Relay follows a modular, service-oriented architecture with clear separation of concerns:

```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│ Input Sources       │────│ sp-base-relay       │────│ Custom RTCM Server  │
│ - Serial UART       │    │ Python Package      │    │ Custom RTCM Server  │
│ - USB Serial        │    │                     │    └─────────────────────┘
│ - TCP (RTKBase)     │    │ ┌─────────────────┐ │              │
│ - TCP Direct        │    │ │ Input Manager   │ │              │
└─────────────────────┘    │ └─────────────────┘ │              │
                           │ ┌─────────────────┐ │              │
┌─────────────────────┐    │ │ Data Pipeline   │ │              │
│ Prometheus Metrics  │◄───│ └─────────────────┘ │              │
└─────────────────────┘    │ ┌─────────────────┐ │              │
                           │ │ RTCM Client     │ │──────────────┘
┌─────────────────────┐    │ └─────────────────┘ │
│ Configuration       │────│ ┌─────────────────┐ │
│ - config.yaml       │    │ │ Health Monitor  │ │
└─────────────────────┘    │ └─────────────────┘ │
                           └─────────────────────┘
```

## Key Design Patterns

### 1. Strategy Pattern - Input Sources
**Purpose**: Support multiple input connection types with unified interface
**Implementation**:
```python
class InputSource(ABC):
    @abstractmethod
    def connect(self) -> bool:
    @abstractmethod  
    def read_data(self) -> Optional[bytes]:
    @abstractmethod
    def disconnect(self) -> None:

class TCPInputSource(InputSource):
    # RTKBase integration via localhost:5015
    
class SerialInputSource(InputSource):  
    # Direct GNSS receiver connection
```

### 2. Observer Pattern - Health Monitoring
**Purpose**: Decouple metrics collection from core operations
**Implementation**:
- Core components emit events (connection established, data sent, errors)
- MetricsCollector observes and updates Prometheus metrics
- Health monitor tracks overall system state

### 3. Circuit Breaker Pattern - Connection Management
**Purpose**: Prevent cascading failures and implement intelligent retry
**Implementation**:
- Track connection failure rates
- Implement exponential backoff with maximum delay
- Gracefully degrade when RTCM server unavailable

### 4. Pipeline Pattern - Data Processing
**Purpose**: Clean data flow with minimal latency
**Implementation**:
```
Input Source → Data Buffer → RTCM Client → Server
     ↓              ↓            ↓
  Metrics    →  Metrics   →   Metrics
```

## Component Relationships

### Core Service Dependencies
```
SPBaseRelay (main)
├── ConfigManager (reads config.yaml)
├── InputManager (creates appropriate InputSource)
├── RTCMClient (handles server connection)
├── MetricsCollector (Prometheus metrics)  
└── HealthMonitor (tracks overall system health)
```

### Threading Model
- **Main Thread**: Service coordination, configuration management
- **Input Thread**: Continuous reading from input source
- **Output Thread**: RTCM server communication and heartbeat monitoring
- **Metrics Thread**: Prometheus HTTP server (if enabled)
- **Health Thread**: Periodic health checks and cleanup

### Error Propagation
- Input errors: Log and attempt reconnection, continue operation
- Output errors: Implement exponential backoff, buffer data briefly
- Configuration errors: Fail fast with clear error messages
- System errors: Graceful shutdown with resource cleanup

## Key Technical Decisions

### 1. No RTCM Validation
**Decision**: Pass-through mode with no message validation
**Rationale**: Minimize latency, trust input source quality
**Impact**: Reduces CPU overhead, maintains real-time performance

### 2. Separate Configuration File
**Decision**: Use config.yaml instead of RTKBase integration initially  
**Rationale**: Standalone operation requirement, future integration flexibility
**Impact**: Independent deployment, easier testing, later RTKBase integration

### 3. Prometheus Metrics
**Decision**: Use Prometheus client library for metrics export
**Rationale**: Industry standard, good monitoring ecosystem integration
**Impact**: Professional monitoring capabilities, ops team familiar tooling

### 4. Exponential Backoff Retry
**Decision**: Implement intelligent retry with exponential backoff
**Rationale**: Prevent server overload, handle transient network issues
**Impact**: Robust operation, reduced server load during outages

### 5. Threading Over Async
**Decision**: Use threading for concurrent operations
**Rationale**: Simpler debugging, better library compatibility
**Impact**: Straightforward implementation, familiar patterns for ops teams

## Critical Implementation Paths

### 1. Authentication Flow
```
Connect TCP → Send INIT command → Receive $HB$ → Start heartbeat monitoring
```

### 2. Data Relay Flow  
```
Read from input → Buffer data → Send to RTCM server → Update metrics
```

### 3. Error Recovery Flow
```
Detect failure → Log error → Close connections → Wait (exponential backoff) → Retry
```

### 4. Health Monitoring Flow
```
Check input status → Check output status → Update metrics → Log status
```

## Integration Points

### RTKBase Integration (Future)
- **Service Management**: Systemd service compatible with RTKBase patterns
- **Configuration**: Eventual integration with RTKBase settings.conf
- **Logging**: Compatible logging format and location
- **Dependencies**: BindsTo relationship with str2str_tcp.service

### Monitoring Integration
- **Prometheus**: Metrics endpoint at /metrics
- **Logging**: Structured JSON logging for log aggregation
- **Health Checks**: HTTP endpoint for container orchestration

### System Integration
- **Systemd**: Native service definition with proper dependencies
- **Packaging**: Standard Python packaging for pip/UV installation  
- **Configuration**: YAML with environment variable override support
