# Bluetooth GPS Setup Guide for SP-Base-Relay

This guide provides complete instructions for setting up sp-rtk-base-relay with a Bluetooth RTK GPS device on Raspberry Pi.

## Overview

This setup connects your RTK GPS base station (RTK_GPS_BASE) via Bluetooth to your Raspberry Pi, creates a virtual serial port, and relays RTCM correction data to the custom RTCM server.

### Architecture

```
RTK_GPS_BASE (Bluetooth GPS)
    ↓ Bluetooth SPP
Raspberry Pi (bluetoothd)
    ↓ rfcomm
/dev/rfcomm0 (virtual serial port)
    ↓ PySerial
sp-rtk-base-relay (SerialInputSource)
    ↓ TCP/IP
RTCM Server (rtcm.example.com:50010)
```

## Prerequisites

### Hardware Requirements
- Raspberry Pi (any model with Bluetooth)
- RTK GPS base station with Bluetooth SPP support
- Power supply for both devices
- Stable internet connection

### Software Requirements
- Raspberry Pi OS (or compatible Linux distribution)
- Python 3.10 or higher
- bluez 5.x (Bluetooth stack)
- systemd

### Device Information
**Your RTK GPS Configuration:**
- Device Name: `RTK_GPS_BASE`
- MAC Address: `00:11:22:33:44:55`
- Serial Protocol: Bluetooth SPP (Serial Port Profile)
- Data Format: RTCM corrections
- Serial Port: `/dev/rfcomm0` (created automatically)

## Installation Steps

### Step 1: Verify Bluetooth is Working

```bash
# Check Bluetooth service status
sudo systemctl status bluetooth

# Should show: Active (running)
# If not active:
sudo systemctl start bluetooth
sudo systemctl enable bluetooth

# Verify bluez version (should be 5.x)
bluetoothctl --version
```

### Step 2: Pair and Trust the GPS Device

> **Usually unnecessary.** The relay pairs and trusts the device for you on first
> start, using the PIN from your configuration — `ensure_device_ready()` handles
> discovery, pairing and trusting. Do this step manually only if automatic pairing
> fails.
>
> **On v3.1.0 and earlier, do it manually — automatic pairing does not work at all**
> ([issue #39](https://github.com/rodenj1/sp-rtk-base-relay/issues/39)). On those
> versions `force_repair()` does not work either: it reports success without
> re-pairing, so do **not** reach for it to recover. If the PIN changed after the
> device was already bonded, run `bluetoothctl remove <mac>` and then pair manually
> as below. Manual pairing works with the relay still running — `bluetoothctl`
> registers its own agent, and BlueZ routes the PIN request to whichever agent
> initiated the pairing.
>
> **From the next release onwards**, a PIN that changed after bonding is handled by
> `BluetoothManager.force_repair()`, which discards the stale bond and re-pairs with
> the new PIN — an existing bond makes the new PIN irrelevant otherwise.

**Option A: Using the interactive pairing script**

```bash
# From the sp-rtk-base-relay directory
sudo bluetoothctl

# In bluetoothctl prompt:
[bluetooth]# scan on
# Wait until you see: Device 00:11:22:33:44:55 RTK_GPS_BASE
[bluetooth]# scan off
[bluetooth]# pair 00:11:22:33:44:55
# Enter PIN if prompted (common: 0000 or 1234)
[bluetooth]# trust 00:11:22:33:44:55
[bluetooth]# exit
```

**Verify pairing:**

```bash
bluetoothctl info 00:11:22:33:44:55
```

You should see:
```
Paired: yes
Trusted: yes
```

### Step 3: Install Bluetooth GPS Scripts

```bash
# Make scripts executable
chmod +x tools/bluetooth/*.sh

# Test connection manually (optional)
sudo tools/bluetooth/connect-gps.sh
```

This should create `/dev/rfcomm0` and display success message.

### Step 4: Install Bluetooth GPS Service

```bash
# Copy systemd service file
sudo cp tools/systemd/bluetooth-gps.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable bluetooth-gps

# Start the service
sudo systemctl start bluetooth-gps

# Check status
sudo systemctl status bluetooth-gps
```

**Verify serial port exists:**

```bash
ls -l /dev/rfcomm0
# Should show: crw-rw-rw- 1 root root ...
```

### Step 5: Test GPS Data Flow

```bash
# Run connection test
sudo tools/bluetooth/test-connection.sh
```

This comprehensive test verifies:
1. ✓ Bluetooth service is running
2. ✓ GPS device is paired and trusted
3. ✓ GPS device is connected
4. ✓ Serial port exists
5. ✓ Serial port has correct permissions
6. ✓ RTCM data is flowing

### Step 6: Configure SP-Base-Relay

**Option A: Use the provided Bluetooth configuration**

```bash
# Copy Bluetooth GPS configuration
sudo cp config.bluetooth-gps.yaml /etc/sp-rtk-base-relay/config.yaml
```

**Option B: Update your existing configuration**

Edit `/etc/sp-rtk-base-relay/config.yaml`:

```yaml
input:
  source: serial  # Changed from 'tcp'
  config:
    port: /dev/rfcomm0
    baud_rate: 115200
    timeout: 5.0
    data_bits: 8
    stop_bits: 1
    parity: none
    buffer_size: 4096

# Keep your existing server configuration
server:
  host: rtcm.example.com
  port: 50010
  username: your_mountpoint
  password: your_password
  # ... rest of config
```

### Step 7: Update SP-Base-Relay Service

```bash
# Update systemd service with Bluetooth dependency
sudo cp tools/systemd/sp-rtk-base-relay.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable sp-rtk-base-relay

# Start service
sudo systemctl start sp-rtk-base-relay

# Check status
sudo systemctl status sp-rtk-base-relay
```

### Step 8: Verify Complete System

```bash
# Check all services
sudo tools/bluetooth/status.sh

# Monitor RTCM data flow
sudo tools/bluetooth/monitor-data.sh

# View sp-rtk-base-relay logs
sudo journalctl -u sp-rtk-base-relay -f
```

## Service Management

### Starting Services

```bash
# Start Bluetooth GPS bridge
sudo systemctl start bluetooth-gps

# Start SP-Base-Relay
sudo systemctl start sp-rtk-base-relay

# Or restart both
sudo systemctl restart bluetooth-gps sp-rtk-base-relay
```

### Stopping Services

```bash
# Stop SP-Base-Relay first
sudo systemctl stop sp-rtk-base-relay

# Then stop Bluetooth GPS bridge
sudo systemctl stop bluetooth-gps
```

### Checking Status

```bash
# Quick status check
sudo tools/bluetooth/status.sh

# Detailed service status
sudo systemctl status bluetooth-gps
sudo systemctl status sp-rtk-base-relay

# View logs
sudo journalctl -u bluetooth-gps -f
sudo journalctl -u sp-rtk-base-relay -f
```

### Auto-Start on Boot

```bash
# Enable both services
sudo systemctl enable bluetooth-gps
sudo systemctl enable sp-rtk-base-relay

# Verify enabled
systemctl is-enabled bluetooth-gps
systemctl is-enabled sp-rtk-base-relay
```

## Monitoring and Diagnostics

### Real-Time Data Monitoring

```bash
# Monitor RTCM data flow (bytes/sec)
sudo tools/bluetooth/monitor-data.sh
```

### Connection Testing

```bash
# Comprehensive connection test
sudo tools/bluetooth/test-connection.sh
```

### Service Status

```bash
# Check all services at once
sudo tools/bluetooth/status.sh
```

### Log Files

```bash
# Bluetooth GPS service logs
sudo journalctl -u bluetooth-gps --since today

# SP-Base-Relay logs
sudo journalctl -u sp-rtk-base-relay --since today

# Show only errors
sudo journalctl -u sp-rtk-base-relay -p err --since today

# Follow logs in real-time
sudo journalctl -u bluetooth-gps -u sp-rtk-base-relay -f
```

## Troubleshooting

### GPS Won't Connect

**Problem:** `bluetoothctl connect` fails

**Solutions:**
```bash
# 1. Check GPS is powered on and in pairing mode

# 2. Re-pair the device
bluetoothctl remove 00:11:22:33:44:55
bluetoothctl pair 00:11:22:33:44:55
bluetoothctl trust 00:11:22:33:44:55

# 3. Restart Bluetooth service
sudo systemctl restart bluetooth

# 4. Check Bluetooth adapter
hciconfig hci0 up
```

### Serial Port Not Created

**Problem:** `/dev/rfcomm0` doesn't exist

**Solutions:**
```bash
# 1. Check bluetooth-gps service
sudo systemctl status bluetooth-gps

# 2. Check service logs
sudo journalctl -u bluetooth-gps -n 50

# 3. Try manual connection
sudo tools/bluetooth/connect-gps.sh

# 4. Verify device is connected
bluetoothctl info 00:11:22:33:44:55 | grep Connected
# Should show: Connected: yes
```

### No Data Flowing

**Problem:** Serial port exists but no data received

**Solutions:**
```bash
# 1. Test data flow
sudo tools/bluetooth/test-connection.sh

# 2. Check if GPS is outputting data
sudo cat /dev/rfcomm0 | xxd | head -n 20

# 3. Verify GPS configuration
# - Ensure GPS is configured for RTCM output
# - Check baud rate (usually 115200)

# 4. Check permissions
ls -l /dev/rfcomm0
sudo chmod 666 /dev/rfcomm0
```

### SP-Base-Relay Can't Read Serial Port

**Problem:** Permission denied errors

**Solutions:**
```bash
# 1. Add user to dialout group
sudo usermod -a -G dialout sp-rtk-base-relay

# 2. Set correct permissions
sudo chmod 666 /dev/rfcomm0

# 3. Check SELinux/AppArmor (if applicable)
# May need to adjust security policies

# 4. Restart service
sudo systemctl restart sp-rtk-base-relay
```

### Bluetooth Connection Keeps Dropping

**Problem:** Connection unstable, frequent disconnects

**Solutions:**
```bash
# 1. Check Bluetooth signal strength
# - Move GPS closer to Raspberry Pi
# - Remove obstacles between devices

# 2. Check power supply
# - Ensure GPS has adequate power
# - Check for power saving modes

# 3. Increase Bluetooth timeout
# Edit /etc/bluetooth/main.conf:
# PageTimeout = 8192
# ConnectionLatency = 0

sudo systemctl restart bluetooth

# 4. Monitor connection quality
hcitool con
hcitool rssi 00:11:22:33:44:55
```

### Service Won't Start After Reboot

**Problem:** Services don't start automatically

**Solutions:**
```bash
# 1. Check service dependencies
sudo systemctl list-dependencies bluetooth-gps
sudo systemctl list-dependencies sp-rtk-base-relay

# 2. Ensure services are enabled
sudo systemctl enable bluetooth
sudo systemctl enable bluetooth-gps
sudo systemctl enable sp-rtk-base-relay

# 3. Check start order
# bluetooth-gps should start after bluetooth
# sp-rtk-base-relay should start after bluetooth-gps

# 4. Check for failed services
systemctl --failed
```

## Performance Tuning

### Optimize for Low Latency

For time-critical RTCM corrections, optimize your configuration:

```yaml
# config.yaml
input:
  config:
    buffer_size: 2048  # Smaller buffer for lower latency

logging:
  level: WARNING  # Reduce logging overhead

metrics:
  enabled: false  # Disable if not needed
```

### Optimize for Reliability

For maximum connection reliability:

```yaml
# config.yaml
pipeline:
  restart:
    max_attempts: 60  # More retry attempts
    max_delay: 120    # Longer max delay
```

### Monitor Resource Usage

```bash
# Check CPU and memory usage
top -p $(pgrep -f sp-rtk-base-relay)

# Check Bluetooth adapter status
hciconfig hci0

# Monitor data rates
sudo tools/bluetooth/monitor-data.sh
```

## Advanced Configuration

### Custom RFCOMM Channel

If your GPS uses a different RFCOMM channel:

```bash
# Edit bluetooth-gps.service
sudo nano /etc/systemd/system/bluetooth-gps.service

# Change RFCOMM_CHANNEL value
Environment="RFCOMM_CHANNEL=2"  # Or appropriate channel

sudo systemctl daemon-reload
sudo systemctl restart bluetooth-gps
```

### Multiple GPS Devices

To connect multiple Bluetooth GPS devices:

1. Create separate service files (bluetooth-gps2.service, etc.)
2. Use different RFCOMM_DEVICE numbers (0, 1, 2...)
3. Update sp-rtk-base-relay configuration to use appropriate port

### Integration with RTKBase

If using alongside RTKBase:

```yaml
# Use RTKBase TCP output as alternative/fallback
input:
  source: serial  # Primary: Bluetooth GPS
  fallback:
    source: tcp
    host: localhost
    port: 5015
```

## Security Considerations

### Bluetooth Security

1. **Use PIN/Passkey:** Always require pairing authentication
2. **Trust Only Known Devices:** Don't auto-trust unknown devices
3. **Disable Discovery:** Turn off when not pairing
4. **Update Firmware:** Keep GPS firmware updated

### File Permissions

```bash
# Restrict config file access
sudo chmod 600 /etc/sp-rtk-base-relay/config.yaml
sudo chown sp-rtk-base-relay:sp-rtk-base-relay /etc/sp-rtk-base-relay/config.yaml
```

### Network Security

```bash
# Restrict metrics endpoint if enabled
# Use firewall rules to limit access
sudo ufw allow from 192.168.1.0/24 to any port 8080
```

## Maintenance

### Regular Checks

```bash
# Weekly: Check service status
sudo tools/bluetooth/status.sh

# Monthly: Check logs for errors
sudo journalctl -u bluetooth-gps -u sp-rtk-base-relay --since "1 month ago" -p err

# Quarterly: Update system packages
sudo apt update && sudo apt upgrade
```

### Backup Configuration

```bash
# Backup important files
sudo tar czf sp-rtk-base-relay-backup.tar.gz \
  /etc/sp-rtk-base-relay/config.yaml \
  /etc/systemd/system/bluetooth-gps.service \
  /etc/systemd/system/sp-rtk-base-relay.service
```

## Support and Resources

### Documentation
- [SP-Base-Relay README](../README.md)
- [Configuration Reference](../configuration-reference.md)
- [Deployment Guide](deployment-guide.md)
- [Metrics Guide](metrics-guide.md)

### Testing Scripts
- `tools/bluetooth/connect-gps.sh` - Manual connection
- `tools/bluetooth/test-connection.sh` - Comprehensive test
- `tools/bluetooth/status.sh` - Service status
- `tools/bluetooth/monitor-data.sh` - Data flow monitoring

### Getting Help

For issues or questions:
1. Check the troubleshooting section above
2. Review logs: `sudo journalctl -u sp-rtk-base-relay -n 100`
3. Run diagnostics: `sudo tools/bluetooth/test-connection.sh`
4. Open an issue on GitHub with log output

## Quick Reference

### Common Commands

```bash
# Start everything
sudo systemctl start bluetooth-gps sp-rtk-base-relay

# Stop everything
sudo systemctl stop sp-rtk-base-relay bluetooth-gps

# Restart everything
sudo systemctl restart bluetooth-gps sp-rtk-base-relay

# Check status
sudo tools/bluetooth/status.sh

# Test connection
sudo tools/bluetooth/test-connection.sh

# Monitor data
sudo tools/bluetooth/monitor-data.sh

# View logs
sudo journalctl -u bluetooth-gps -u sp-rtk-base-relay -f
```

### File Locations

- Configuration: `/etc/sp-rtk-base-relay/config.yaml`
- Service files: `/etc/systemd/system/*.service`
- Logs: `journalctl` or `/var/log/sp-rtk-base-relay/`
- Serial port: `/dev/rfcomm0`
- Scripts: `tools/bluetooth/*.sh`
