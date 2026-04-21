#!/bin/bash
# Bluetooth GPS Recovery Script
# Resets hung rfcomm connections without requiring full system reboot
# Used by systemd services for automatic recovery

set -e

# Configuration
GPS_MAC="00:11:22:33:44:55"
GPS_NAME="RTK_GPS_BASE"
RFCOMM_CHANNEL=1
RFCOMM_DEVICE=0

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a /var/log/sp-rtk-base-relay/bluetooth-recovery.log
}

log "=== Bluetooth GPS Recovery Started ==="
log "Device: $GPS_NAME ($GPS_MAC)"
log "Target: /dev/rfcomm${RFCOMM_DEVICE}"

# Step 1: Release frozen rfcomm device
log "Step 1: Releasing /dev/rfcomm${RFCOMM_DEVICE}..."
rfcomm release ${RFCOMM_DEVICE} 2>/dev/null || true
sleep 1

# Step 2: Disconnect Bluetooth device
log "Step 2: Disconnecting Bluetooth device..."
echo "disconnect ${GPS_MAC}" | bluetoothctl 2>/dev/null || true
sleep 2

# Step 3: Kill any hung rfcomm processes (cleanup)
log "Step 3: Cleaning up rfcomm processes..."
pkill -9 -f "rfcomm.*${RFCOMM_DEVICE}" 2>/dev/null || true
sleep 1

# Step 4: Verify device is still paired and trusted
log "Step 4: Verifying device pairing..."
if ! echo "info ${GPS_MAC}" | bluetoothctl | grep -q "Paired: yes"; then
    log "WARNING: Device not paired, attempting to pair..."
    echo "pair ${GPS_MAC}" | bluetoothctl
    sleep 2
fi

if ! echo "info ${GPS_MAC}" | bluetoothctl | grep -q "Trusted: yes"; then
    log "Setting device as trusted..."
    echo "trust ${GPS_MAC}" | bluetoothctl
fi

# Step 5: Reconnect Bluetooth device
log "Step 5: Reconnecting Bluetooth device..."
echo "connect ${GPS_MAC}" | bluetoothctl
sleep 3

# Step 6: Re-bind rfcomm device
log "Step 6: Re-binding rfcomm device..."
rfcomm bind ${RFCOMM_DEVICE} ${GPS_MAC} ${RFCOMM_CHANNEL}
sleep 1

# Step 7: Set permissions
if [ -e "/dev/rfcomm${RFCOMM_DEVICE}" ]; then
    log "Step 7: Setting permissions..."
    chmod 666 "/dev/rfcomm${RFCOMM_DEVICE}"
    
    # Verify device is actually readable
    if timeout 2 head -c 1 /dev/rfcomm${RFCOMM_DEVICE} >/dev/null 2>&1; then
        log "=== Bluetooth GPS Recovery SUCCESSFUL ==="
        log "Device /dev/rfcomm${RFCOMM_DEVICE} is readable"
        exit 0
    else
        log "WARNING: Device created but not readable, may need more time"
        exit 0
    fi
else
    log "ERROR: Failed to create /dev/rfcomm${RFCOMM_DEVICE}"
    log "=== Bluetooth GPS Recovery FAILED ==="
    exit 1
fi
