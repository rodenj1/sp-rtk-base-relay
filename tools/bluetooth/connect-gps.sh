#!/bin/bash
# Bluetooth GPS Connection Script for RTK_GPS_BASE
# This script connects to the Bluetooth GPS device and creates a virtual serial port

set -e

# Configuration
GPS_MAC="00:11:22:33:44:55"
GPS_NAME="RTK_GPS_BASE"
RFCOMM_CHANNEL=1
RFCOMM_DEVICE=0  # Creates /dev/rfcomm0

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Bluetooth GPS Connection Script ===${NC}"
echo "Device: $GPS_NAME"
echo "MAC Address: $GPS_MAC"
echo "Target: /dev/rfcomm${RFCOMM_DEVICE}"
echo ""

# Check if bluetooth service is running
if ! systemctl is-active --quiet bluetooth; then
    echo -e "${RED}Error: Bluetooth service is not running${NC}"
    echo "Start it with: sudo systemctl start bluetooth"
    exit 1
fi

# Check if device is paired
echo -e "${YELLOW}Checking if device is paired...${NC}"
if ! bluetoothctl info "$GPS_MAC" | grep -q "Paired: yes"; then
    echo -e "${RED}Error: Device $GPS_MAC is not paired${NC}"
    echo "Pair it first with: bluetoothctl pair $GPS_MAC"
    exit 1
fi

# Check if device is trusted
if ! bluetoothctl info "$GPS_MAC" | grep -q "Trusted: yes"; then
    echo -e "${YELLOW}Warning: Device is not trusted. Trusting now...${NC}"
    bluetoothctl trust "$GPS_MAC"
fi

# Check if rfcomm device already exists
if [ -e "/dev/rfcomm${RFCOMM_DEVICE}" ]; then
    echo -e "${YELLOW}Warning: /dev/rfcomm${RFCOMM_DEVICE} already exists${NC}"
    echo "Releasing existing connection..."
    sudo rfcomm release "${RFCOMM_DEVICE}" 2>/dev/null || true
    sleep 1
fi

# Connect to the device via bluetoothctl
echo -e "${YELLOW}Connecting to Bluetooth device...${NC}"
bluetoothctl connect "$GPS_MAC"
sleep 2

# Bind to rfcomm device
echo -e "${YELLOW}Binding to /dev/rfcomm${RFCOMM_DEVICE}...${NC}"
sudo rfcomm bind "${RFCOMM_DEVICE}" "$GPS_MAC" "${RFCOMM_CHANNEL}"

# Verify the device was created
if [ -e "/dev/rfcomm${RFCOMM_DEVICE}" ]; then
    echo -e "${GREEN}Success! Serial port created: /dev/rfcomm${RFCOMM_DEVICE}${NC}"
    ls -l "/dev/rfcomm${RFCOMM_DEVICE}"

    # Set proper permissions
    sudo chmod 666 "/dev/rfcomm${RFCOMM_DEVICE}"

    echo ""
    echo -e "${GREEN}You can now use /dev/rfcomm${RFCOMM_DEVICE} with sp-rtk-base-relay${NC}"
else
    echo -e "${RED}Error: Failed to create /dev/rfcomm${RFCOMM_DEVICE}${NC}"
    exit 1
fi
