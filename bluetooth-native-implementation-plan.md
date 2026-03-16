# Native Bluetooth Input Source Implementation Plan

**Date:** February 3, 2026  
**Author:** Cline  
**Status:** Planning Complete - Ready for Implementation

---

## Executive Summary

Replace the current two-service Bluetooth architecture (bluetooth-gps.service + sp-base-relay.service) with a single-service, pure Python solution using BlueZ D-Bus API. This will eliminate external dependencies on rfcomm and shell scripts while providing automated device pairing and connection management.

**Approach:** Option 2 - Python BlueZ D-Bus API with native socket data transfer  
**Outcome:** Add `bluetooth` as a third input source type alongside existing `tcp` and `serial`  
**Estimated Effort:** 24-33 hours across 8 phases

---

## Problem Statement

### Current Issues
1. **Two-Service Complexity:** Requires bluetooth-gps.service AND sp-base-relay.service
2. **External Scripts:** Relies on shell scripts for Bluetooth management
3. **Deprecated Commands:** Uses rfcomm which is deprecated by BlueZ
4. **Manual Setup:** Requires bluetoothctl commands for pairing/trusting
5. **Virtual Device:** Creates /dev/rfcomm0 with permission management issues

### Goals
- ✅ Single systemd service (sp-base-relay.service only)
- ✅ Eliminate rfcomm dependency
- ✅ Automated device pairing and connection
- ✅ Pure Python implementation
- ✅ Consistent with existing tcp/serial input sources
- ✅ Works on Raspberry Pi and standard Linux

---

## Architecture

### Current Architecture (To Replace)
```
┌─────────────────────────────────────┐
│   bluetooth-gps.service             │
│   - Shell scripts                   │
│   - bluetoothctl commands           │
│   - rfcomm bind/release             │
└──────────────┬──────────────────────┘
               ↓
        /dev/rfcomm0
               ↓
┌──────────────────────────────────────┐
│   sp-base-relay.service              │
│   - PySerial reads /dev/rfcomm0      │
└──────────────┬───────────────────────┘
               ↓
         RTCM Server
```

### Target Architecture
```
┌─────────────────────────────────────────────────┐
│   sp-base-relay.service (Python ONLY)           │
│                                                  │
│   ┌──────────────────────────────────────────┐  │
│   │  BluetoothManager (D-Bus API)            │  │
│   │  - Device discovery by name/MAC          │  │
│   │  - Automatic pairing (with PIN)          │  │
│   │  - Automatic trusting                    │  │
│   │  - Automatic connection                  │  │
│   │  - RFCOMM channel discovery              │  │
│   └───────────────┬──────────────────────────┘  │
│                   ↓                              │
│   ┌──────────────────────────────────────────┐  │
│   │  BluetoothInputSource                    │  │
│   │  - socket.AF_BLUETOOTH RFCOMM socket     │  │
│   │  - Direct data reading (no /dev/rfcomm)  │  │
│   │  - Same interface as tcp/serial          │  │
│   └───────────────┬──────────────────────────┘  │
│                   ↓                              │
│   ┌──────────────────────────────────────────┐  │
│   │  DataPipelineCoordinator                 │  │
│   │  (existing, no changes needed)           │  │
│   └───────────────┬──────────────────────────┘  │
└───────────────────┼──────────────────────────────┘
                    ↓
              RTCM Server
```

### Three Input Sources
After implementation, users can choose:
1. **TCP Input** - Network-based RTCM (RTKBase, remote servers)
2. **Serial Input** - Physical serial ports (USB-to-serial, UART)
3. **Bluetooth Input** - Wireless GPS devices via Bluetooth SPP

---

## Component Design

### 1. BluetoothManager (`bluetooth_manager.py`)
**Purpose:** D-Bus API wrapper for Bluetooth operations

**Key Methods:**
```python
def find_device_by_name(device_name: str) -> str | None
def find_device_by_mac(mac_address: str) -> bool
def pair_device(mac_address: str, pin: str = "0000") -> bool
def trust_device(mac_address: str) -> bool
def connect_device(mac_address: str) -> bool
def disconnect_device(mac_address: str) -> bool
def discover_rfcomm_channel(mac_address: str) -> int | None
def ensure_device_ready(device_name: str, mac_address: str) -> tuple[str, int]
```

**Responsibilities:**
- Bluetooth adapter management (hci0)
- Device discovery (scan by name or MAC)
- Pairing with PIN support
- Trusting devices for auto-reconnect
- Connection/disconnection management
- RFCOMM channel discovery
- Error handling and state tracking

### 2. BluetoothInputSource (`bluetooth_input.py`)
**Purpose:** InputSource implementation for Bluetooth GPS devices

**Configuration:**
```python
@dataclass
class BluetoothConfig:
    device_name: str | None = None      # "RTK_GPS_BASE"
    mac_address: str | None = None      # "00:11:22:33:44:55"
    channel: int | None = None          # Auto-discover if None
    timeout: float = 5.0
    buffer_size: int = 4096
    auto_pair: bool = True
    auto_trust: bool = True
    pin: str = "0000"
```

**Key Methods (from InputSource base):**
```python
def connect() -> bool
def read_data(timeout: float | None = None) -> bytes | None
def disconnect() -> None
def get_connection_info() -> dict[str, Any]
```

**Responsibilities:**
- Use BluetoothManager for connection setup
- Open RFCOMM socket for data transfer
- Implement InputSource interface
- Statistics tracking
- Error handling and state management

### 3. Updated InputFactory
Registers "bluetooth" source type and creates BluetoothInputSource instances

### 4. Updated Config
Adds BluetoothConfig schema with validation

---

## Implementation Phases

### PHASE 1: Core D-Bus Manager (6-8 hours)

**Deliverables:**
- `src/sp_base_relay/core/bluetooth_manager.py`
- D-Bus wrapper for BlueZ operations
- Comprehensive error handling

**Tasks:**
1. Create BluetoothManager class (2 hours)
   - Initialize pydbus connection
   - Get Bluetooth adapter (hci0)
   - Basic error handling

2. Implement device discovery (1.5 hours)
   - `find_device_by_name()` - scan and match by name
   - `find_device_by_mac()` - verify device exists
   - Handle scan timeout and no devices found

3. Implement pairing/trusting (1.5 hours)
   - `pair_device()` - with PIN support
   - `trust_device()` - for auto-reconnect
   - Check if already paired/trusted
   - Handle pairing failures

4. Implement connection management (1 hour)
   - `connect_device()` - establish connection
   - `disconnect_device()` - clean disconnect
   - Check connection state

5. Implement RFCOMM channel discovery (1 hour)
   - `discover_rfcomm_channel()` - find SPP channel
   - Default to channel 1 for SPP
   - Optional: Query SDP for exact channel

6. Implement orchestration method (1 hour)
   - `ensure_device_ready()` - all-in-one setup
   - Returns (mac_address, channel) tuple
   - Complete error handling

**Testing Strategy:**
- Mock pydbus with unittest.mock
- Test each method independently
- Test complete workflow via ensure_device_ready()
- Edge cases: device not found, pairing fails, etc.

---

### PHASE 2: Bluetooth Input Source (4-5 hours)

**Deliverables:**
- `src/sp_base_relay/core/input_sources/bluetooth_input.py`
- BluetoothConfig dataclass
- BluetoothInputSource class

**Tasks:**
1. Create BluetoothConfig dataclass (30 min)
2. Implement BluetoothInputSource.__init__() (30 min)
   - Initialize base class
   - Create BluetoothManager instance
   - Validate config

3. Implement connect() method (1.5 hours)
   - Use BluetoothManager.ensure_device_ready()
   - Create AF_BLUETOOTH socket
   - Connect to (mac_address, channel)
   - Update connection stats
   - Comprehensive error handling

4. Implement read_data() method (1 hour)
   - socket.recv() with buffer_size
   - Handle timeout gracefully
   - Update read stats
   - Error handling

5. Implement disconnect() method (30 min)
   - Close socket
   - Update connection stats
   - Clean state reset

6. Implement get_connection_info() method (30 min)

**Testing Strategy:**
- Mock BluetoothManager
- Mock socket.socket (AF_BLUETOOTH)
- Test connect success/failure paths
- Test read_data with various scenarios
- Integration test with mock data flow

---

### PHASE 3: Configuration & Integration (3-4 hours)

**Deliverables:**
- Updated `config.py` with bluetooth schema
- Updated `input_factory.py` with bluetooth registration
- Example configuration files

**Tasks:**
1. Add BluetoothConfig to config.py (1 hour)
   - Import BluetoothConfig
   - Add to InputConfig union
   - Validation rules
   - Environment variable overrides

2. Update InputSourceFactory (1 hour)
   - Register "bluetooth" source type
   - Create instance with config
   - Error handling for missing dependencies

3. Create example configurations (1 hour)
   - `config.bluetooth-auto.yaml` - auto-discovery
   - `config.bluetooth-manual.yaml` - manual MAC
   - Update config.example.yaml

4. Update configuration validation (1 hour)
   - Validate MAC address format
   - Validate PIN format
   - Add helpful error messages

---

### PHASE 4: Dependencies & Setup (1-2 hours)

**Deliverables:**
- Updated `pyproject.toml`
- Installation documentation
- Dependency verification tests

**Tasks:**
1. Update pyproject.toml (30 min)
   ```toml
   dependencies = [
       "pydbus>=0.6.0",
       "PyGObject>=3.42.0",
   ]
   ```

2. Create dependency check (30 min)
   - Try/except imports
   - Helpful error messages
   - Graceful degradation

3. Document system dependencies (30 min)
   ```bash
   sudo apt-get install python3-gi python3-gi-cairo gir1.2-gtk-3.0
   ```

4. Test installation process (30 min)

---

### PHASE 5: Unit Testing (4-5 hours)

**Deliverables:**
- `tests/unit/test_bluetooth_manager.py`
- `tests/unit/test_bluetooth_input.py`
- `tests/fixtures/mock_bluetooth.py`
- >90% coverage for new code

**Tasks:**
1. Create mock Bluetooth fixtures (1 hour)
   - Mock pydbus.SystemBus
   - Mock D-Bus adapter and device objects
   - Mock socket.AF_BLUETOOTH
   - Configurable success/failure scenarios

2. Write BluetoothManager tests (2 hours)
   - Test device discovery
   - Test pairing/trusting
   - Test connection
   - Test RFCOMM channel discovery
   - Test ensure_device_ready() workflow
   - Edge cases and error handling

3. Write BluetoothInputSource tests (2 hours)
   - Test initialization
   - Test connect() with auto_pair=True/False
   - Test read_data() success/timeout/error
   - Test disconnect() cleanup
   - Test statistics tracking

**Coverage Target:** >90% for new code

---

### PHASE 6: Hardware Testing (2-3 hours)

**Deliverables:**
- Verified functionality with RTK_GPS_BASE GPS
- Performance benchmarks
- Edge case validation

**Tasks:**
1. Initial connection test (30 min)
   - Auto-discovery by device name
   - Pairing and trusting
   - RFCOMM socket connection
   - Basic data reading

2. Data flow validation (30 min)
   - Verify RTCM data flowing
   - Check frame buffer extraction
   - Validate metrics updates

3. Reconnection testing (1 hour)
   - Power cycle GPS
   - Move out of range
   - Test automatic reconnection

4. Performance testing (30 min)
   - Monitor CPU/memory usage
   - Compare latency vs rfcomm
   - Verify no data loss

5. Edge case testing (30 min)
   - Wrong PIN
   - Device not found
   - Multiple reconnection attempts

---

### PHASE 7: Cleanup & Migration (2-3 hours)

**Deliverables:**
- Removed bluetooth-gps.service
- Removed shell scripts
- Migration guide
- Updated documentation

**Tasks:**
1. Remove old Bluetooth infrastructure (30 min)
   - Delete `tools/systemd/bluetooth-gps.service`
   - Delete `tools/bluetooth/connect-gps.sh`
   - Update installation scripts

2. Update sp-base-relay.service (30 min)
   - Remove bluetooth-gps dependencies
   - Keep system bluetooth.service dependency

3. Create migration guide (1 hour)
   - `docs/bluetooth-migration-guide.md`
   - Old vs new architecture
   - Step-by-step migration
   - Configuration changes
   - Troubleshooting

4. Update documentation (1 hour)
   - Update README.md
   - Update `docs/bluetooth-gps-setup.md`
   - Update configuration-reference.md

---

### PHASE 8: Documentation & Polish (2-3 hours)

**Deliverables:**
- Complete code documentation
- Updated README
- User guide
- API documentation

**Tasks:**
1. Code documentation (1 hour)
   - Comprehensive docstrings
   - Inline comments
   - Type hints verification
   - PEP8 compliance

2. User documentation (1 hour)
   - Update README with bluetooth example
   - Bluetooth setup quickstart
   - Configuration examples
   - Troubleshooting guide

3. API documentation (30 min)
   - Document BluetoothConfig parameters
   - Document BluetoothManager API
   - Document error types

4. Final polish (30 min)
   - Run pylance/pyright checks
   - Run full test suite
   - Verify test coverage

---

## Timeline

| Phase | Description | Duration | Dependencies |
|-------|-------------|----------|--------------|
| 1 | Core D-Bus Manager | 6-8 hours | None |
| 2 | Bluetooth Input Source | 4-5 hours | Phase 1 |
| 3 | Configuration & Integration | 3-4 hours | Phase 2 |
| 4 | Dependencies & Setup | 1-2 hours | Phase 3 |
| 5 | Unit Testing | 4-5 hours | Phases 1-3 |
| 6 | Hardware Testing | 2-3 hours | Phases 1-4 |
| 7 | Cleanup & Migration | 2-3 hours | Phase 6 |
| 8 | Documentation & Polish | 2-3 hours | All phases |

**Total: 24-33 hours**

**Recommended Schedule:**
- **Week 1:** Phases 1-3 (Implementation)
- **Week 2:** Phases 4-6 (Testing)
- **Week 3:** Phases 7-8 (Cleanup & Documentation)

---

## Key Milestones

### Milestone 1: D-Bus Manager Working
- ✅ BluetoothManager can discover, pair, connect
- ✅ Unit tests passing
- ✅ Mock testing infrastructure in place

### Milestone 2: Bluetooth Input Source Complete
- ✅ BluetoothInputSource implements InputSource
- ✅ Can read data via RFCOMM socket
- ✅ Unit tests passing
- ✅ Configuration system updated

### Milestone 3: Integration Complete
- ✅ Factory creates bluetooth sources
- ✅ Full data pipeline working
- ✅ All existing tests passing
- ✅ Configuration validated

### Milestone 4: Hardware Validated
- ✅ Working with RTK_GPS_BASE GPS
- ✅ Automatic pairing/connection verified
- ✅ Data flowing to RTCM server
- ✅ Performance acceptable

### Milestone 5: Production Ready
- ✅ Old bluetooth-gps.service removed
- ✅ Single-service architecture working
- ✅ Documentation complete
- ✅ >90% test coverage maintained

---

## Configuration Examples

### Auto-Discovery by Device Name
```yaml
input:
  source: bluetooth
  config:
    device_name: "RTK_GPS_BASE"
    auto_pair: true
    auto_trust: true
    pin: "0000"
    timeout: 5.0
    buffer_size: 4096
```

### Manual Connection (Pre-Paired Device)
```yaml
input:
  source: bluetooth
  config:
    mac_address: "00:11:22:33:44:55"
    channel: 1
    auto_pair: false
    timeout: 5.0
```

### RTKBase TCP (Existing)
```yaml
input:
  source: tcp
  config:
    host: localhost
    port: 5015
```

### Wired Serial (Existing)
```yaml
input:
  source: serial
  config:
    port: /dev/ttyUSB0
    baudrate: 115200
```

---

## Risks & Mitigation

### Risk 1: D-Bus API Complexity
**Risk:** D-Bus API might be complex  
**Mitigation:** Start simple, iterate  
**Fallback:** Option 1 (native socket only)

### Risk 2: Pairing Issues
**Risk:** Auto-pairing might fail  
**Mitigation:** Support manual pairing mode  
**Fallback:** Document bluetoothctl pairing

### Risk 3: Dependency Installation
**Risk:** PyGObject install might fail  
**Mitigation:** Comprehensive docs  
**Fallback:** Make bluetooth optional

### Risk 4: Hardware Compatibility
**Risk:** Might not work with all GPS  
**Mitigation:** Test with RTK_GPS_BASE  
**Fallback:** Keep serial source available

### Risk 5: Test Coverage
**Risk:** Mocking D-Bus challenging  
**Mitigation:** Use unittest.mock extensively  
**Fallback:** Accept lower D-Bus coverage

---

## Success Criteria

### Code Complete
- [ ] BluetoothManager implemented
- [ ] BluetoothInputSource implemented
- [ ] InputFactory updated
- [ ] Configuration supports bluetooth
- [ ] All code has type hints and docstrings
- [ ] Zero pylance/pyright errors

### Testing Complete
- [ ] Unit tests >90% coverage
- [ ] All existing tests passing
- [ ] Overall project coverage >89%
- [ ] Hardware tested with real GPS

### Documentation Complete
- [ ] Code docstrings complete
- [ ] README updated
- [ ] Configuration reference updated
- [ ] Migration guide created
- [ ] Troubleshooting section added

### Cleanup Complete
- [ ] bluetooth-gps.service removed
- [ ] Shell scripts removed
- [ ] Configuration files updated
- [ ] Installation scripts updated

### Production Ready
- [ ] Works on Raspberry Pi
- [ ] Works on standard Linux
- [ ] Dependencies documented
- [ ] Performance acceptable
- [ ] Single systemd service
- [ ] Zero breaking changes

---

## References

### D-Bus & BlueZ
- [BlueZ D-Bus API](https://git.kernel.org/pub/scm/bluetooth/bluez.git/tree/doc)
- [pydbus Documentation](https://github.com/LEW21/pydbus)
- [PyGObject Documentation](https://pygobject.readthedocs.io/)

### Python Bluetooth
- [Python AF_BLUETOOTH](https://docs.python.org/3/library/socket.html#socket.AF_BLUETOOTH)
- [ukBaz Bluetooth Notes](https://ukbaz.github.io/howto/bluetooth_overview.html)

### Current Implementation
- `src/sp_base_relay/core/input_sources/tcp_input.py`
- `src/sp_base_relay/core/input_sources/serial_input.py`
- `docs/bluetooth-gps-setup.md`

---

## Next Steps

1. **Review and approve this plan**
2. **Begin Phase 1:** Create bluetooth_manager.py
3. **Iterate through phases** testing each thoroughly
4. **Hardware validation** with RTK_GPS_BASE
5. **Deploy and migrate** from old architecture

---

**Plan Status:** ✅ Complete - Ready for Implementation  
**Next Action:** Begin Phase 1 implementation
