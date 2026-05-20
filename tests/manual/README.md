# Manual Testing for SP-Base-Relay

This directory contains manual test scripts for validating SP-Base-Relay with real hardware and production services.

## Overview

Manual tests are designed for scenarios where:
- Testing with production RTCM server is required
- Real hardware validation is needed
- Interactive testing and debugging is beneficial
- Automated tests cannot adequately validate behavior

## Test Scripts

### test_production_rtcm.py

End-to-end test script for validating complete data flow with the production RTCM server.

**Purpose**: Validate that sp-rtk-base-relay can successfully:
- Connect to TCP hardware source (192.168.0.242:3000)
- Authenticate with production RTCM server (rtcm.example.com:50010)
- Stream RTCM data continuously
- Monitor heartbeats and connection health
- Handle graceful shutdown

**Usage**:
```bash
# Run with default settings (60 seconds)
uv run python tests/manual/test_production_rtcm.py

# Run for longer duration (5 minutes)
uv run python tests/manual/test_production_rtcm.py --duration 300

# Use custom configuration file
uv run python tests/manual/test_production_rtcm.py --config my-config.yaml --duration 120

# Stop early with Ctrl+C for graceful shutdown
```

**Configuration Requirements**:

The script requires a valid configuration file (default: `config.example.yaml`) with:

1. **RTCM Server Configuration** (production credentials):
```yaml
server:
  host: "rtcm.example.com"
  port: 50010
  username: "your_mountpoint"  # Your production username
  password: "your_password"     # Your production password
  connection_timeout: 10
  read_timeout: 30
  heartbeat_timeout: 30
```

2. **TCP Input Configuration** (hardware source):
```yaml
input:
  source: "tcp"
  config:
    host: "192.168.0.242"  # Your TCP hardware IP
    port: 3000
    timeout: 5.0
    buffer_size: 4096
```

**Output Example**:
```
12:00:00 [INFO] __main__: Loading configuration from: config.example.yaml
12:00:00 [INFO] __main__: ============================================================
12:00:00 [INFO] __main__: PRODUCTION RTCM SERVER TEST
12:00:00 [INFO] __main__: ============================================================
12:00:00 [INFO] __main__: Test Duration: 60 seconds
12:00:00 [INFO] __main__: TCP Input: 192.168.0.242:3000
12:00:00 [INFO] __main__: RTCM Server: rtcm.example.com:50010
12:00:00 [INFO] __main__: RTCM Username: your_mountpoint
12:00:00 [INFO] __main__: ============================================================
12:00:00 [INFO] __main__: Connecting to TCP input source...
12:00:01 [INFO] tcp_input: Connecting to TCP source 192.168.0.242:3000
12:00:01 [INFO] __main__: ✓ TCP input connected successfully
12:00:01 [INFO] __main__:   Connection info: {'host': '192.168.0.242', 'port': 3000, ...}
12:00:01 [INFO] __main__: Connecting to production RTCM server...
12:00:01 [INFO] rtcm_client: Connecting to RTCM server rtcm.example.com:50010
12:00:02 [INFO] rtcm_client: Authenticating with username: your_mountpoint
12:00:02 [INFO] __main__: ✓ RTCM server connected successfully
12:00:02 [INFO] __main__: ✓ Authentication successful
12:00:02 [INFO] __main__: ============================================================
12:00:02 [INFO] __main__: Starting data relay...
12:00:02 [INFO] __main__: (Press Ctrl+C to stop early)
12:00:02 [INFO] __main__: ============================================================
12:00:07 [INFO] __main__: [5s] Transferred: 5.2 KB, Rate: 1.04 KB/s, Messages: 5, Heartbeats: 5
12:00:12 [INFO] __main__: [10s] Transferred: 10.8 KB, Rate: 1.08 KB/s, Messages: 10, Heartbeats: 10
...
12:01:02 [INFO] __main__: ============================================================
12:01:02 [INFO] __main__: Test duration completed
12:01:02 [INFO] __main__: ============================================================
12:01:02 [INFO] __main__: FINAL STATISTICS REPORT
12:01:02 [INFO] __main__: ============================================================
12:01:02 [INFO] __main__: Test Duration: 60.0s
12:01:02 [INFO] __main__: Bytes Transferred: 66,897 bytes (65.3 KB)
12:01:02 [INFO] __main__: Messages Sent: 60
12:01:02 [INFO] __main__: Average Throughput: 1.09 KB/s
12:01:02 [INFO] __main__: Heartbeats Received: 60
12:01:02 [INFO] __main__:
12:01:02 [INFO] __main__: Input Source Statistics:
12:01:02 [INFO] __main__:   Read Attempts: 65
12:01:02 [INFO] __main__:   Read Successes: 60
12:01:02 [INFO] __main__:   Read Errors: 0
12:01:02 [INFO] __main__:
12:01:02 [INFO] __main__: RTCM Server Statistics:
12:01:02 [INFO] __main__:   Send Attempts: 60
12:01:02 [INFO] __main__:   Send Successes: 60
12:01:02 [INFO] __main__:   Send Errors: 0
12:01:02 [INFO] __main__:   Success Rate: 100.0%
12:01:02 [INFO] __main__: ============================================================
12:01:02 [INFO] __main__: ============================================================
12:01:02 [INFO] __main__: ✓ TEST COMPLETED SUCCESSFULLY
12:01:02 [INFO] __main__: ============================================================
```

**Success Criteria**:

The test is considered successful when:
- ✅ Both connections establish successfully
- ✅ Authentication completes
- ✅ At least some data is transferred
- ✅ No connection errors occur
- ✅ Success rate > 95%
- ✅ Clean disconnection on exit

**Failure Scenarios**:

1. **TCP Hardware Unreachable**:
```
[ERROR] Failed to connect to TCP input source
[ERROR] TCP connection timeout after 5.0s to 192.168.0.242:3000
```
*Solution*: Verify hardware is powered on and network accessible

2. **RTCM Authentication Failed**:
```
[ERROR] Failed to connect to RTCM server
[ERROR] Authentication failed: Invalid credentials
```
*Solution*: Verify username/password in configuration

3. **Connection Lost During Test**:
```
[ERROR] TCP input disconnected!
⚠ TEST COMPLETED WITH ISSUES
```
*Solution*: Check network stability, hardware status

4. **No Data Available**:
```
[WARNING] ⚠ TEST COMPLETED WITH ISSUES
Success Rate: 0.0%
```
*Solution*: Verify GNSS receiver has satellite fix and is generating data

## Prerequisites

### 1. Hardware Requirements

- **TCP Hardware Source**: 192.168.0.242:3000 (or configure your own)
- **Network Access**: Ability to reach both hardware and RTCM server
- **GNSS Data**: Hardware must be streaming RTCM data

### 2. Production RTCM Server Access

- **Valid Credentials**: Working username and password
- **Network Access**: Firewall must allow connection to rtcm.example.com:50010
- **Production Data**: Understand that real correction data will be sent

### 3. Software Requirements

```bash
# Install project dependencies
uv sync --all-extras

# Verify Python version
python --version  # Should be 3.10 or greater
```

## Pre-Test Checklist

Before running production tests:

- [ ] **Verify Hardware**: `ping 192.168.0.242` succeeds
- [ ] **Test TCP Port**: `telnet 192.168.0.242 3000` connects
- [ ] **Verify RTCM Server**: `telnet rtcm.example.com 50010` connects
- [ ] **Check Credentials**: Ensure username/password are correct
- [ ] **Review Config**: Configuration file has correct settings
- [ ] **Network Stable**: Verify stable network connection
- [ ] **GNSS Fix**: Hardware has satellite fix and is generating data

## Running Production Tests

### Step-by-Step Process

1. **Verify Prerequisites**:
```bash
# Check hardware
ping 192.168.0.242

# Check RTCM server (should connect then close)
telnet rtcm.example.com 50010

# Verify configuration
cat config.example.yaml
```

2. **Run Short Test First** (60 seconds):
```bash
uv run python tests/manual/test_production_rtcm.py
```

3. **Review Results**:
- Check for successful connection
- Verify data is flowing
- Confirm heartbeats are received
- Review any errors

4. **Run Longer Test** (if initial test succeeds):
```bash
# 5 minute test
uv run python tests/manual/test_production_rtcm.py --duration 300

# 30 minute stability test
uv run python tests/manual/test_production_rtcm.py --duration 1800
```

### Interpreting Results

**Healthy Output Indicators**:
- ✅ "✓ TCP input connected successfully"
- ✅ "✓ RTCM server connected successfully"
- ✅ "✓ Authentication successful"
- ✅ Regular progress updates every 5 seconds
- ✅ Increasing bytes transferred
- ✅ Heartbeat count matches elapsed time (±1)
- ✅ "✓ TEST COMPLETED SUCCESSFULLY"

**Warning Signs**:
- ⚠ "No data available from TCP input" (repeated)
- ⚠ Read success rate < 80%
- ⚠ Send success rate < 95%
- ⚠ Connection errors during test
- ⚠ "⚠ TEST COMPLETED WITH ISSUES"

## Troubleshooting

### TCP Hardware Connection Issues

**Problem**: Cannot connect to TCP hardware
```bash
# Verify hardware is reachable
ping 192.168.0.242

# Check if port is open
nc -zv 192.168.0.242 3000

# Try manual connection
telnet 192.168.0.242 3000
```

### RTCM Server Connection Issues

**Problem**: Cannot connect to RTCM server
```bash
# Verify server is reachable
ping rtcm.example.com

# Check if port is open
nc -zv 91.186.9.186 50010

# Test with telnet
telnet rtcm.example.com 50010
```

### Authentication Issues

**Problem**: Authentication fails

1. Verify credentials in config file
2. Check for typos in username/password
3. Confirm credentials are still valid
4. Review RTCM server logs (if accessible)

### No Data Flow

**Problem**: Connected but no data transferring

1. **Check GNSS Receiver**:
   - Verify satellite fix
   - Check antenna connection
   - Review receiver logs

2. **Check TCP Hardware**:
   - Verify str2str_tcp service is running
   - Check hardware is receiving GNSS data
   - Review hardware logs

3. **Network Issues**:
   - Check for packet loss
   - Verify network bandwidth
   - Test with shorter timeout

## Safety Considerations

### Production Server Impact

⚠️ **Important**: This test sends real RTCM data to the production server

- Real correction data will be transmitted
- Server will track your connection
- Data usage will be logged
- Multiple simultaneous connections may not be allowed

### Best Practices

1. **Start with short duration** (60 seconds)
2. **Monitor actively** during test execution
3. **Stop immediately** if issues detected (Ctrl+C)
4. **Review logs** after each test
5. **Coordinate with team** before extended tests
6. **Document results** for future reference

## Advanced Usage

### Custom Configuration

Create a custom config file for testing:

```yaml
# test-config.yaml
server:
  host: "rtcm.example.com"
  port: 50010
  username: "TEST_USER"
  password: "test_pass"

input:
  source: "tcp"
  config:
    host: "192.168.0.242"
    port: 3000
    timeout: 10.0  # Longer timeout for testing
    buffer_size: 8192
```

Then run with custom config:
```bash
uv run python tests/manual/test_production_rtcm.py --config test-config.yaml
```

### Environment Variable Overrides

Override settings without changing config file:

```bash
# Override RTCM credentials
export SP_RTCM_USERNAME="your_mountpoint"
export SP_RTCM_PASSWORD="your_password"

# Override input source
export SP_INPUT_TCP_HOST="192.168.0.242"
export SP_INPUT_TCP_PORT="3000"

# Run test
uv run python tests/manual/test_production_rtcm.py
```

### Debugging Mode

The script automatically runs with DEBUG logging enabled. To see even more detail:

```bash
# Run with Python debug mode
python -v tests/manual/test_production_rtcm.py

# Redirect output to file for analysis
uv run python tests/manual/test_production_rtcm.py 2>&1 | tee test-output.log
```

## Related Documentation

- **Integration Tests**: `../integration/README.md` - Automated integration tests
- **Project Brief**: `../../memory-bank/projectbrief.md` - Project overview
- **RTCM Protocol**: `../../rtcm-server-integration.md` - RTCM server details
- **Configuration**: `../../configuration-reference.md` - Config file reference

## Future Enhancements

Planned improvements for manual testing:

- [ ] Real-time throughput graphing
- [ ] Detailed latency measurements
- [ ] Network quality metrics
- [ ] Automatic test report generation
- [ ] Performance benchmarking
- [ ] Comparison with previous test runs
- [ ] Alert thresholds for monitoring

## Support

For issues with manual testing:

1. Review this README
2. Check project documentation in `memory-bank/`
3. Review test output logs
4. Verify prerequisites are met
5. Test with shorter duration first
