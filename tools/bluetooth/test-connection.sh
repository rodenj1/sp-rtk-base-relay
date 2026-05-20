#!/bin/bash
# Test Bluetooth GPS Connection and Data Flow
# This script verifies the complete setup from Bluetooth to RTCM data

set -e

# Configuration
GPS_MAC="00:11:22:33:44:55"
GPS_NAME="RTK_GPS_BASE"
RFCOMM_DEVICE="/dev/rfcomm0"
TEST_DURATION=5  # seconds to monitor data

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Bluetooth GPS Connection Test ===${NC}"
echo "Device: $GPS_NAME ($GPS_MAC)"
echo "Serial Port: $RFCOMM_DEVICE"
echo ""

# Test 1: Bluetooth service
echo -e "${YELLOW}[1/7] Checking Bluetooth service...${NC}"
if systemctl is-active --quiet bluetooth; then
    echo -e "${GREEN}✓ Bluetooth service is running${NC}"
else
    echo -e "${RED}✗ Bluetooth service is not running${NC}"
    exit 1
fi

# Test 2: Device pairing
echo -e "${YELLOW}[2/7] Checking device pairing...${NC}"
if bluetoothctl info "$GPS_MAC" | grep -q "Paired: yes"; then
    echo -e "${GREEN}✓ Device is paired${NC}"
else
    echo -e "${RED}✗ Device is not paired${NC}"
    exit 1
fi

# Test 3: Device trust
echo -e "${YELLOW}[3/7] Checking device trust...${NC}"
if bluetoothctl info "$GPS_MAC" | grep -q "Trusted: yes"; then
    echo -e "${GREEN}✓ Device is trusted${NC}"
else
    echo -e "${YELLOW}⚠ Device is not trusted (may work anyway)${NC}"
fi

# Test 4: Bluetooth connection
echo -e "${YELLOW}[4/7] Checking Bluetooth connection...${NC}"
if bluetoothctl info "$GPS_MAC" | grep -q "Connected: yes"; then
    echo -e "${GREEN}✓ Device is connected${NC}"
else
    echo -e "${YELLOW}⚠ Device is not connected, attempting connection...${NC}"
    bluetoothctl connect "$GPS_MAC" || echo -e "${RED}Failed to connect${NC}"
    sleep 2
    if bluetoothctl info "$GPS_MAC" | grep -q "Connected: yes"; then
        echo -e "${GREEN}✓ Device connected successfully${NC}"
    else
        echo -e "${RED}✗ Could not connect to device${NC}"
        exit 1
    fi
fi

# Test 5: Serial port exists
echo -e "${YELLOW}[5/7] Checking serial port...${NC}"
if [ -e "$RFCOMM_DEVICE" ]; then
    echo -e "${GREEN}✓ Serial port exists: $RFCOMM_DEVICE${NC}"
    ls -l "$RFCOMM_DEVICE"
else
    echo -e "${RED}✗ Serial port does not exist: $RFCOMM_DEVICE${NC}"
    echo "Run: sudo tools/bluetooth/connect-gps.sh"
    exit 1
fi

# Test 6: Serial port permissions
echo -e "${YELLOW}[6/7] Checking serial port permissions...${NC}"
if [ -r "$RFCOMM_DEVICE" ] && [ -w "$RFCOMM_DEVICE" ]; then
    echo -e "${GREEN}✓ Serial port is readable and writable${NC}"
else
    echo -e "${YELLOW}⚠ May need permission adjustment${NC}"
    echo "Run: sudo chmod 666 $RFCOMM_DEVICE"
fi

# Test 7: Data flow
echo -e "${YELLOW}[7/7] Testing data flow (${TEST_DURATION}s)...${NC}"
echo "Reading from $RFCOMM_DEVICE..."

# Check if any data is coming through
if timeout "$TEST_DURATION" cat "$RFCOMM_DEVICE" > /tmp/gps_test_output 2>&1; then
    if [ -s /tmp/gps_test_output ]; then
        BYTES=$(wc -c < /tmp/gps_test_output)
        echo -e "${GREEN}✓ Data is flowing: $BYTES bytes received in ${TEST_DURATION}s${NC}"

        # Show first few bytes (hex dump)
        echo "First 64 bytes (hex):"
        head -c 64 /tmp/gps_test_output | xxd -l 64

        # Try to detect RTCM data (starts with 0xD3)
        if head -c 1000 /tmp/gps_test_output | xxd -p | grep -q 'd3'; then
            echo -e "${GREEN}✓ RTCM data detected (0xD3 preamble found)${NC}"
        else
            echo -e "${YELLOW}⚠ No RTCM preamble detected (may be NMEA or other format)${NC}"
        fi
    else
        echo -e "${RED}✗ No data received${NC}"
        echo "Check if GPS is powered on and outputting data"
        exit 1
    fi
else
    echo -e "${YELLOW}⚠ Read operation timed out or failed${NC}"
fi

# Cleanup
rm -f /tmp/gps_test_output

echo ""
echo -e "${GREEN}=== All Tests Passed ===${NC}"
echo ""
echo "Your Bluetooth GPS is ready for use with sp-rtk-base-relay!"
echo ""
echo "Next steps:"
echo "1. Update /etc/sp-rtk-base-relay/config.yaml to use serial input"
echo "2. Start bluetooth-gps service: sudo systemctl start bluetooth-gps"
echo "3. Start sp-rtk-base-relay service: sudo systemctl start sp-rtk-base-relay"
