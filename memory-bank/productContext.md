# Product Context

## Why SP-Base-Relay Exists

SP-Base-Relay solves a specific integration problem in the RTK GPS ecosystem where existing tools like RTKLIB's `str2str` cannot handle custom authentication protocols required by specialized RTCM correction services.

## Problems It Solves

### 1. Custom Protocol Support
- **Problem**: Standard NTRIP clients and `str2str` don't support custom authentication protocols
- **Solution**: Native support for the specific `INIT:username:password*` authentication sequence
- **Impact**: Enables RTK base stations to connect to previously incompatible correction services

### 2. RTKBase Integration Gap
- **Problem**: RTKBase users need custom RTCM server connectivity but no existing service supports it
- **Solution**: Drop-in service that integrates with RTKBase's multi-service architecture
- **Impact**: Extends RTKBase's capability without modifying core system

### 3. Reliability and Monitoring
- **Problem**: Network-based correction services need robust connection management
- **Solution**: Advanced retry logic, heartbeat monitoring, and Prometheus metrics
- **Impact**: Production-ready reliability with operational visibility

### 4. Multiple Input Source Support
- **Problem**: Different deployment scenarios require different connection methods
- **Solution**: Unified interface supporting serial, USB, and TCP inputs
- **Impact**: Single tool handles diverse hardware configurations

## User Experience Goals

### For RTK Base Station Operators
- **Seamless Integration**: Works alongside existing RTKBase services
- **Reliable Operation**: Automatic recovery from network issues
- **Easy Configuration**: YAML-based configuration with clear documentation
- **Monitoring Visibility**: Prometheus metrics for integration with monitoring stacks

### For GNSS Professionals
- **Low Latency**: Minimal processing delay for time-critical corrections
- **High Reliability**: Robust error handling and automatic reconnection
- **Professional Quality**: Complete logging, metrics, and diagnostic capabilities
- **Flexible Deployment**: Supports various hardware and network configurations

### For System Administrators  
- **Standard Service Management**: Systemd integration for familiar operations
- **Comprehensive Logging**: Structured logging for troubleshooting
- **Health Monitoring**: Clear indicators of service health and performance
- **Easy Installation**: Standard Python packaging with automated setup scripts

## How It Should Work

### Core Workflow
1. **Startup**: Read configuration, initialize connections, start monitoring
2. **Data Flow**: Continuously relay RTCM data from input source to RTCM server
3. **Error Recovery**: Detect connection issues, implement exponential backoff retry
4. **Health Reporting**: Export metrics for monitoring system integration
5. **Graceful Shutdown**: Clean disconnection and resource cleanup

### Integration with RTKBase
- **Service Discovery**: Appears in RTKBase service management alongside other `str2str` services
- **Configuration**: Managed through RTKBase settings (future integration)
- **Monitoring**: Health status visible in RTKBase diagnostic interface
- **Resource Sharing**: Uses RTKBase's TCP stream output as input source

### Operational Characteristics
- **Always Available**: Designed for 24/7 operation with automatic recovery
- **Resource Efficient**: Minimal CPU and memory footprint
- **Network Resilient**: Handles network interruptions gracefully
- **Observable**: Rich metrics and logging for operational insight
