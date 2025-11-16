# Integration Tests for SP-Base-Relay

This directory contains integration tests that verify the complete system functionality with real hardware and network connections. These tests are designed to be run manually when hardware is available.

## Overview

The integration test suite validates:
- **TCP Input Hardware Tests**: Connection and data reading from real TCP hardware (192.168.0.242:3000)
- **End-to-End Integration Tests**: Complete pipeline from TCP input through to mock RTCM server

## Test Structure

```
tests/integration/
├── __init__.py                      # Package initialization
├── conftest.py                      # Shared pytest fixtures and configuration
├── test_tcp_input_hardware.py       # TCP hardware connection tests
├── test_end_to_end_integration.py   # Full pipeline integration tests
└── README.md                        # This file
```

## Prerequisites

### Hardware Requirements

1. **TCP Serial Connection**
   - IP Address: 192.168.0.242
   - Port: 3000
   - Must be streaming RTCM data continuously
   - Network accessible from test machine

2. **Network Connectivity**
   - Test machine must be able to reach 192.168.0.242
   - No firewall blocking port 3000
   - Stable network connection for long-running tests

### Software Requirements

- Python 3.10 or greater
- UV package manager (installed)
- All project dependencies installed (`uv sync`)
- TCP hardware online and streaming data

## Running Tests

### Quick Start

```bash
# Check if hardware is available first
ping 192.168.0.242

# Run all integration tests (will skip if hardware unavailable)
uv run pytest tests/integration/ -v

# Run with detailed output
uv run pytest tests/integration/ -v -s
```

### Running Specific Test Suites

```bash
# Run only TCP input hardware tests
uv run pytest tests/integration/test_tcp_input_hardware.py -v

# Run only end-to-end tests
uv run pytest tests/integration/test_end_to_end_integration.py -v
```

### Running Specific Tests

```bash
# Run a specific test class
uv run pytest tests/integration/test_tcp_input_hardware.py::TestTCPConnectionEstablishment -v

# Run a single test
uv run pytest tests/integration/test_tcp_input_hardware.py::TestTCPConnectionEstablishment::test_connection_establishment -v

# Run end-to-end flow test
uv run pytest tests/integration/test_end_to_end_integration.py::TestBasicPipelineFlow::test_tcp_to_rtcm_flow -v
```

### Test Markers

Tests are organized with pytest markers:

```bash
# Run only hardware tests
uv run pytest tests/integration/ -m hardware -v

# Run only manual tests
uv run pytest tests/integration/ -m manual -v

# Exclude slow tests
uv run pytest tests/integration/ -m "not slow" -v

# Run only slow tests
uv run pytest tests/integration/ -m slow -v
```

## Test Categories

### 1. TCP Input Hardware Tests (`test_tcp_input_hardware.py`)

Tests TCP input source with real hardware at 192.168.0.242:3000.

**Test Classes:**
- `TestTCPConnectionEstablishment`: Connection setup and health checks
- `TestTCPDataReading`: Data reading and format validation  
- `TestTCPConnectionResilience`: Reconnection and error handling
- `TestTCPPerformance`: Throughput and stability testing (slow)
- `TestTCPStatistics`: Statistics and monitoring validation

**Key Tests:**
- `test_connection_establishment`: Basic connection verification
- `test_continuous_data_reading`: RTCM data streaming
- `test_connection_stability`: 30-second stability test
- `test_data_throughput`: 10-second throughput measurement

### 2. End-to-End Integration Tests (`test_end_to_end_integration.py`)

Tests complete pipeline: TCP input → Data Pipeline → Mock RTCM Server

**Test Classes:**
- `TestBasicPipelineFlow`: Basic data flow verification
- `TestConnectionManagement`: Connection/reconnection scenarios
- `TestMultiThreadedOperation`: Concurrent operations and threading
- `TestErrorScenarios`: Error handling and edge cases
- `TestLongRunning`: Extended operation tests (slow, 60 seconds)

**Key Tests:**
- `test_tcp_to_rtcm_flow`: Complete end-to-end data flow
- `test_multiple_data_transmissions`: Multiple transmission cycles
- `test_heartbeat_monitoring_during_data_flow`: Heartbeat validation
- `test_extended_operation`: 60-second stability test

## Test Configuration

### Hardware Configuration

Hardware connection details are defined in `conftest.py`:

```python
HARDWARE_TCP_HOST = "192.168.0.242"
HARDWARE_TCP_PORT = 3000
HARDWARE_TIMEOUT = 5.0  # Seconds
```

To test with different hardware, modify these constants in `conftest.py`.

### Mock RTCM Server Configuration

Mock server settings in `conftest.py`:

```python
MOCK_RTCM_PORT = 50011  # Different from production
MOCK_RTCM_HOST = "127.0.0.1"
```

## Understanding Test Results

### Successful Run Example

```
tests/integration/test_tcp_input_hardware.py::TestTCPConnectionEstablishment::test_connection_establishment PASSED
tests/integration/test_tcp_input_hardware.py::TestTCPDataReading::test_continuous_data_reading PASSED
...
========================= 15 passed in 45.23s ==========================
```

### Skipped Tests (Hardware Unavailable)

```
tests/integration/test_tcp_input_hardware.py::test_connection_establishment SKIPPED (Hardware not available)
========================= 15 skipped in 0.50s ==========================
```

Tests are automatically skipped if hardware at 192.168.0.242:3000 is not reachable.

### Test Output Interpretation

**Connection Tests:**
- Check connection state, statistics, and connection info
- Verify socket details and health status
- Validate timeout handling

**Data Reading Tests:**
- Measure bytes read and message counts
- Check for RTCM3 format (0xD3 preamble)
- Validate continuous streaming

**End-to-End Tests:**
- Verify mock server receives authentication
- Check data transmission success
- Monitor heartbeat messages (1 per second)
- Track server statistics

## Troubleshooting

### Hardware Not Available

**Symptoms:**
```
SKIPPED (Hardware not available at 192.168.0.242:3000)
```

**Solutions:**
1. Check hardware is powered on
2. Verify network connectivity: `ping 192.168.0.242`
3. Verify port accessibility: `telnet 192.168.0.242 3000` or `nc 192.168.0.242 3000`
4. Check firewall rules
5. Ensure TCP serial server is running and configured correctly

### Connection Timeout

**Symptoms:**
```
AssertionError: Failed to connect to TCP hardware
```

**Solutions:**
1. Increase timeout in `conftest.py`: `HARDWARE_TIMEOUT = 10.0`
2. Check network latency
3. Verify hardware is responsive
4. Review hardware logs for connection issues

### No Data Received

**Symptoms:**
```
AssertionError: Should have read at least some data chunks
```

**Solutions:**
1. Verify hardware is streaming RTCM data
2. Check GNSS receiver is getting satellite fix
3. Increase read timeout in tests
4. Verify data format from hardware

### Mock Server Connection Issues

**Symptoms:**
```
AssertionError: Failed to connect to mock RTCM server
```

**Solutions:**
1. Check port 50011 is not in use: `netstat -an | grep 50011`
2. Ensure no firewall blocking localhost connections
3. Review test logs for server startup errors

### Test Performance Issues

**Symptoms:**
- Tests take very long time
- Tests hang or timeout

**Solutions:**
1. Skip slow tests: `pytest tests/integration/ -m "not slow"`
2. Reduce test duration in test code
3. Check hardware response time
4. Verify network stability

## Best Practices

### Before Running Tests

1. **Verify Hardware**: Ensure TCP hardware is online and streaming
   ```bash
   ping 192.168.0.242
   telnet 192.168.0.242 3000
   ```

2. **Check System Resources**: Ensure adequate resources
   ```bash
   free -h  # Check available memory
   ```

3. **Review Recent Changes**: Know what you're testing

### During Test Execution

1. **Monitor Logs**: Watch test output for issues
2. **Check Hardware**: Verify hardware remains stable
3. **Network Stability**: Ensure stable network connection
4. **Resource Usage**: Monitor CPU/memory if needed

### After Tests Complete

1. **Review Results**: Check all test outcomes
2. **Analyze Failures**: Investigate any failures
3. **Check Statistics**: Review throughput and timing data
4. **Document Issues**: Note any hardware or network problems

## Test Development

### Adding New Tests

1. Add test to appropriate file (`test_tcp_input_hardware.py` or `test_end_to_end_integration.py`)
2. Use appropriate pytest markers (`@pytest.mark.hardware`, `@pytest.mark.manual`)
3. Add `skip_if_no_hardware` fixture parameter if hardware required
4. Include comprehensive docstring explaining test purpose
5. Add proper logging for debugging
6. Clean up resources in `finally` blocks

### Example Test Template

```python
@pytest.mark.hardware
@pytest.mark.manual
class TestNewFeature:
    """Test description."""
    
    def test_new_functionality(
        self,
        connected_tcp_input: TCPInputSource,
        skip_if_no_hardware: None
    ) -> None:
        """Test description.
        
        Verifies:
        - Point 1
        - Point 2
        """
        logger.info("Testing new functionality")
        
        try:
            # Test implementation
            result = connected_tcp_input.read_data(timeout=2.0)
            assert result is not None, "Should receive data"
            
            logger.info("Test successful")
            
        finally:
            # Cleanup if needed
            pass
```

### Available Fixtures

From `conftest.py`:

- `hardware_tcp_config`: TCP configuration for 192.168.0.242:3000
- `hardware_available`: Bool indicating if hardware is reachable
- `skip_if_no_hardware`: Auto-skip fixture
- `tcp_input_source`: TCP input source (not connected)
- `connected_tcp_input`: TCP input source (already connected)
- `mock_rtcm_server`: Running mock RTCM server
- `mock_rtcm_connection_info`: Connection details for mock server
- `sample_rtcm_data`: Sample RTCM message bytes
- `wait_for_condition`: Utility for waiting on conditions
- `measure_duration`: Utility for timing operations

## Integration Test Checklist

Before considering integration tests complete:

- [ ] All TCP connection tests pass
- [ ] Data reading tests validate RTCM format
- [ ] Reconnection tests handle failures gracefully
- [ ] End-to-end flow transmits data successfully
- [ ] Heartbeat monitoring works correctly
- [ ] Error scenarios handled properly
- [ ] Statistics track accurately
- [ ] Long-running tests complete without issues
- [ ] All cleanup happens correctly (no resource leaks)
- [ ] Tests are well documented

## Future Enhancements

Potential additions to integration tests:

1. **Real RTCM Server Testing**: Tests with production server (requires credentials)
2. **Performance Benchmarking**: Detailed latency and throughput analysis
3. **Stress Testing**: High-load scenarios and limit testing
4. **Network Failure Simulation**: Artificial network disruption testing
5. **Multiple Hardware Sources**: Testing with different TCP hardware
6. **Concurrent Connections**: Multiple simultaneous client testing

## Support

For issues with integration tests:

1. Check this README first
2. Review test code and docstrings
3. Check hardware and network connectivity
4. Review test logs with `-v -s` flags
5. Check project documentation in `memory-bank/`

## Related Documentation

- **Project Brief**: `memory-bank/projectbrief.md`
- **Technical Context**: `memory-bank/techContext.md`
- **Development Plan**: `development-plan.md`
- **RTCM Protocol**: `rtcm-server-integration.md`
- **Unit Tests**: `tests/unit/`
