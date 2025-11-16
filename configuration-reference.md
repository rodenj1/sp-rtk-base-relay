# Configuration Reference

## Overview

SP-Base-Relay uses YAML-based configuration with validation, environment variable overrides, and clear error reporting. This document provides complete configuration reference and examples.

## Configuration File Structure

### Default Configuration Locations
1. **Command line specified**: `--config /path/to/config.yaml`
2. **Environment variable**: `SP_BASE_RELAY_CONFIG=/path/to/config.yaml`
3. **User directory**: `~/.config/sp-base-relay/config.yaml`
4. **System directory**: `/etc/sp-base-relay/config.yaml`

### Example Configuration File
```yaml
# SP-Base-Relay Configuration
# This file configures the RTCM relay service for custom GPS correction servers

# RTCM Server Configuration
server:
  host: "rtcm.example.com"      # RTCM server hostname or IP address
  port: 50010                   # RTCM server port
  username: "your_username"     # Authentication username
  password: "your_password"     # Authentication password
  
# Input Source Configuration  
input:
  type: "tcp"                   # Options: tcp, serial, usb_serial
  
  # TCP Input (RTKBase integration)
  tcp:
    host: "127.0.0.1"           # RTKBase str2str_tcp host
    port: 5015                  # RTKBase str2str_tcp port
    timeout: 5.0                # Connection timeout (seconds)
    
  # Serial Input (Direct GNSS receiver connection)
  serial:
    port: "/dev/ttyUSB0"        # Serial port device
    baudrate: 115200            # Baud rate (9600, 19200, 38400, 57600, 115200)
    bytesize: 8                 # Data bits (5, 6, 7, 8)
    parity: "N"                 # Parity (N=None, E=Even, O=Odd, M=Mark, S=Space)
    stopbits: 1                 # Stop bits (1, 1.5, 2)
    timeout: 1.0                # Read timeout (seconds)
    rtscts: false               # Hardware flow control
    xonxoff: false              # Software flow control

# Connection Monitoring Configuration
monitoring:
  heartbeat_timeout: 30         # Heartbeat timeout (seconds)
  reconnect_delay_base: 1       # Initial reconnection delay (seconds)
  reconnect_max_delay: 60       # Maximum reconnection delay (seconds)
  max_reconnect_attempts: 0     # Maximum attempts (0 = unlimited)
  connection_check_interval: 5  # Connection health check interval (seconds)
  
# Metrics Configuration
metrics:
  enabled: true                 # Enable Prometheus metrics export
  host: "0.0.0.0"              # Metrics server bind address
  port: 8080                   # Metrics server port
  path: "/metrics"             # Metrics endpoint path
  
# Logging Configuration
logging:
  level: "INFO"                 # Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
  format: "json"                # Log format (json, text)
  file: "/var/log/sp-base-relay.log"  # Log file path (null for console only)
  max_size_mb: 50              # Maximum log file size (MB)
  backup_count: 3              # Number of backup files to keep
  
# Service Configuration
service:
  daemon: false                # Run as daemon
  pid_file: "/var/run/sp-base-relay.pid"  # PID file location
  user: "sp-base-relay"        # Service user (for systemd)
  group: "sp-base-relay"       # Service group (for systemd)
```

## Configuration Sections

### Server Configuration
Controls connection to the custom RTCM server.

```yaml
server:
  host: "rtcm.example.com" # Required: RTCM server hostname or IP
  port: 50010              # Required: RTCM server port
  username: "your_username" # Required: Authentication username
  password: "your_password" # Required: Authentication password
```

**Environment Variable Overrides:**
- `SP_RTCM_HOST`: Override server host
- `SP_RTCM_PORT`: Override server port  
- `SP_RTCM_USERNAME`: Override username
- `SP_RTCM_PASSWORD`: Override password

### Input Source Configuration
Configures how RTCM data is read from the base station.

#### TCP Input (RTKBase Integration)
```yaml
input:
  type: "tcp"
  tcp:
    host: "127.0.0.1"      # RTKBase str2str_tcp host
    port: 5015             # RTKBase str2str_tcp port
    timeout: 5.0           # Connection timeout
    buffer_size: 4096      # Read buffer size
```

#### Serial Input (Direct Connection)
```yaml
input:
  type: "serial"  
  serial:
    port: "/dev/ttyUSB0"   # Serial device path
    baudrate: 115200       # Communication speed
    bytesize: 8            # Data bits per character
    parity: "N"            # Parity checking
    stopbits: 1            # Stop bits
    timeout: 1.0           # Read timeout
    rtscts: false          # Hardware flow control
    xonxoff: false         # Software flow control
```

**Common Serial Configurations:**
```yaml
# High-speed u-blox receivers
serial:
  port: "/dev/ttyUSB0"
  baudrate: 115200
  
# Standard GNSS receivers  
serial:
  port: "/dev/ttyUSB0"
  baudrate: 38400
  
# Legacy receivers
serial:
  port: "/dev/ttyS0"
  baudrate: 9600
```

### Monitoring Configuration
Controls connection health monitoring and retry behavior.

```yaml
monitoring:
  heartbeat_timeout: 30         # Server heartbeat timeout
  reconnect_delay_base: 1       # Initial retry delay  
  reconnect_max_delay: 60       # Maximum retry delay
  max_reconnect_attempts: 0     # Retry limit (0 = unlimited)
  connection_check_interval: 5  # Health check frequency
```

**Retry Behavior:**
- **Exponential Backoff**: Delays follow sequence 1s, 2s, 4s, 8s, 16s, 32s, 60s (max)
- **Unlimited Retries**: Set `max_reconnect_attempts: 0` for continuous retry
- **Limited Retries**: Set positive value to limit retry attempts

### Metrics Configuration
Configures Prometheus metrics export.

```yaml
metrics:
  enabled: true            # Enable/disable metrics export
  host: "0.0.0.0"         # Bind address (0.0.0.0 = all interfaces)
  port: 8080              # HTTP server port
  path: "/metrics"        # Metrics endpoint URL path
```

**Access Examples:**
- Local: `http://localhost:8080/metrics`
- Remote: `http://your-server-ip:8080/metrics`

### Logging Configuration  
Controls application logging behavior.

```yaml
logging:
  level: "INFO"                    # Minimum log level
  format: "json"                   # Output format
  file: "/var/log/sp-base-relay.log"  # Log file path
  max_size_mb: 50                  # File size limit
  backup_count: 3                  # Backup file count
```

**Log Levels:**
- `DEBUG`: Detailed debugging information
- `INFO`: General operational information  
- `WARNING`: Warning messages and recoverable errors
- `ERROR`: Error conditions that don't stop operation
- `CRITICAL`: Critical errors that may stop operation

**Log Formats:**
- `json`: Structured JSON logs (recommended for log aggregation)
- `text`: Human-readable text format

## Environment Variable Overrides

All configuration values can be overridden using environment variables with the `SP_` prefix:

```bash
# Server configuration
export SP_RTCM_HOST="192.168.1.100" 
export SP_RTCM_PORT="50010"
export SP_RTCM_USERNAME="myuser"
export SP_RTCM_PASSWORD="mypass"

# Input configuration  
export SP_INPUT_TYPE="serial"
export SP_SERIAL_PORT="/dev/ttyUSB1"
export SP_SERIAL_BAUDRATE="38400"

# Monitoring configuration
export SP_HEARTBEAT_TIMEOUT="45"
export SP_RECONNECT_MAX_DELAY="120"

# Metrics configuration
export SP_METRICS_ENABLED="true"
export SP_METRICS_PORT="9090"

# Logging configuration
export SP_LOG_LEVEL="DEBUG"
export SP_LOG_FORMAT="json"
```

## Configuration Validation

### Required Fields
These fields must be present and valid:
- `server.host`: Valid hostname or IP address
- `server.port`: Valid port number (1-65535)
- `server.username`: Non-empty string
- `server.password`: Non-empty string
- `input.type`: One of: tcp, serial, usb_serial

### Validation Rules
```python
class ConfigSchema:
    """Configuration validation schema"""
    
    VALID_INPUT_TYPES = {"tcp", "serial", "usb_serial"}
    VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    VALID_LOG_FORMATS = {"json", "text"}
    VALID_PARITY = {"N", "E", "O", "M", "S"}
    VALID_BYTESIZE = {5, 6, 7, 8}
    VALID_STOPBITS = {1, 1.5, 2}
    
    def validate_server_config(self, config: dict) -> None:
        """Validate server configuration"""
        if not config.get("host"):
            raise ValueError("server.host is required")
        
        port = config.get("port", 50010)
        if not isinstance(port, int) or not (1 <= port <= 65535):
            raise ValueError("server.port must be 1-65535")
            
        if not config.get("username"):
            raise ValueError("server.username is required")
            
        if not config.get("password"):
            raise ValueError("server.password is required")
    
    def validate_input_config(self, config: dict) -> None:
        """Validate input configuration"""
        input_type = config.get("type", "tcp")
        if input_type not in self.VALID_INPUT_TYPES:
            raise ValueError(f"input.type must be one of: {self.VALID_INPUT_TYPES}")
        
        if input_type == "tcp":
            tcp_config = config.get("tcp", {})
            if not tcp_config.get("host"):
                raise ValueError("input.tcp.host is required")
                
        elif input_type in ("serial", "usb_serial"):
            serial_config = config.get("serial", {})
            if not serial_config.get("port"):
                raise ValueError("input.serial.port is required")
```

## Configuration Examples

### Minimal Configuration
```yaml
# Minimal working configuration
server:
  host: "rtcm.example.com"
  port: 50010
  username: "your_username"
  password: "your_password"
  
input:
  type: "tcp"
  tcp:
    host: "127.0.0.1"
    port: 5015
```

### Production Configuration
```yaml
# Production configuration with full monitoring
server:
  host: "91.186.9.136"
  port: 50010
  username: "PROD_USER"
  password: "secure_password"
  
input:
  type: "tcp"
  tcp:
    host: "127.0.0.1"
    port: 5015
    timeout: 10.0
    
monitoring:
  heartbeat_timeout: 30
  reconnect_delay_base: 2
  reconnect_max_delay: 300
  connection_check_interval: 10
  
metrics:
  enabled: true
  host: "0.0.0.0"
  port: 8080
  
logging:
  level: "INFO"
  format: "json"
  file: "/var/log/sp-base-relay.log"
  max_size_mb: 100
  backup_count: 7
```

### Serial Direct Connection
```yaml
# Direct serial connection to GNSS receiver
server:
  host: "91.186.9.136"
  port: 50010
  username: "SERIAL_USER"
  password: "serial_pass"
  
input:
  type: "serial"
  serial:
    port: "/dev/ttyUSB0"
    baudrate: 115200
    bytesize: 8
    parity: "N"
    stopbits: 1
    timeout: 2.0
    
logging:
  level: "DEBUG"  # More verbose for troubleshooting
  format: "text"
  file: "/tmp/sp-base-relay-debug.log"
```

### Container Configuration
```yaml
# Configuration optimized for container deployment
server:
  host: "rtcm-server.example.com"
  port: 50010
  username: "${RTCM_USERNAME}"
  password: "${RTCM_PASSWORD}"
  
input:
  type: "tcp"
  tcp:
    host: "rtkbase"  # Container hostname
    port: 5015
    
metrics:
  enabled: true
  host: "0.0.0.0"
  port: 8080
  
logging:
  level: "INFO"
  format: "json"
  file: null  # Console only for container logs
```

## Configuration Management

### Loading Priority
Configuration is loaded in this order (later sources override earlier):
1. Default values
2. Configuration file  
3. Environment variables
4. Command line arguments

### Configuration Validation
```python
def load_and_validate_config(config_path: str) -> dict:
    """Load and validate configuration file"""
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
        
        # Validate configuration
        validator = ConfigSchema()
        validator.validate_all(config)
        
        # Apply environment variable overrides
        config = apply_env_overrides(config)
        
        return config
        
    except FileNotFoundError:
        raise ConfigError(f"Configuration file not found: {config_path}")
    except yaml.YAMLError as e:
        raise ConfigError(f"Invalid YAML syntax: {e}")
    except ValueError as e:
        raise ConfigError(f"Configuration validation error: {e}")
```

### Runtime Configuration Changes
Currently, configuration changes require service restart. Future versions may support:
- Hot reload for non-critical settings (logging level, metrics)
- SIGHUP signal handling for configuration refresh
- Runtime API for configuration updates

## Troubleshooting Configuration Issues

### Common Configuration Errors
```bash
# Check configuration syntax
sp-base-relay --config config.yaml --validate-config

# Test configuration with dry run
sp-base-relay --config config.yaml --dry-run

# Show effective configuration (with overrides)
sp-base-relay --config config.yaml --show-config
```

### Configuration File Permissions
```bash
# Set secure permissions for configuration file
sudo chown sp-base-relay:sp-base-relay /etc/sp-base-relay/config.yaml
sudo chmod 640 /etc/sp-base-relay/config.yaml

# Verify permissions
ls -la /etc/sp-base-relay/config.yaml
```

### Environment Variable Debugging
```bash
# Show all SP_ environment variables
env | grep ^SP_

# Test environment variable override
SP_LOG_LEVEL=DEBUG sp-base-relay --config config.yaml --show-config
```

This configuration reference provides complete documentation for all configuration options, validation rules, and usage examples for SP-Base-Relay.
