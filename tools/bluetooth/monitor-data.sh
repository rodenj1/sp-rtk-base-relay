#!/bin/bash
# Monitor RTCM data flow from Bluetooth GPS
# This script displays real-time data flow statistics

# Configuration
RFCOMM_DEVICE="/dev/rfcomm0"
UPDATE_INTERVAL=2  # seconds

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Bluetooth GPS Data Monitor ===${NC}"
echo "Device: $RFCOMM_DEVICE"
echo "Update interval: ${UPDATE_INTERVAL}s"
echo "Press Ctrl+C to stop"
echo ""

# Check if device exists
if [ ! -e "$RFCOMM_DEVICE" ]; then
    echo -e "${RED}Error: $RFCOMM_DEVICE does not exist${NC}"
    echo "Run: sudo tools/bluetooth/connect-gps.sh"
    exit 1
fi

# Check if readable
if [ ! -r "$RFCOMM_DEVICE" ]; then
    echo -e "${RED}Error: Cannot read from $RFCOMM_DEVICE${NC}"
    echo "Run: sudo chmod 666 $RFCOMM_DEVICE"
    exit 1
fi

# Initialize counters
TOTAL_BYTES=0
START_TIME=$(date +%s)

# Function to format bytes
format_bytes() {
    local bytes=$1
    if [ $bytes -lt 1024 ]; then
        echo "${bytes}B"
    elif [ $bytes -lt 1048576 ]; then
        echo "$(awk "BEGIN {printf \"%.2f\", $bytes/1024}")KB"
    else
        echo "$(awk "BEGIN {printf \"%.2f\", $bytes/1048576}")MB"
    fi
}

# Monitor loop
while true; do
    # Read data for UPDATE_INTERVAL seconds
    BYTES_READ=$(timeout $UPDATE_INTERVAL cat "$RFCOMM_DEVICE" | wc -c)
    
    if [ $BYTES_READ -gt 0 ]; then
        TOTAL_BYTES=$((TOTAL_BYTES + BYTES_READ))
        CURRENT_TIME=$(date +%s)
        ELAPSED=$((CURRENT_TIME - START_TIME))
        
        # Calculate rates
        RATE_BPS=$((BYTES_READ / UPDATE_INTERVAL))
        AVG_RATE=$((TOTAL_BYTES / ELAPSED))
        
        # Display statistics
        clear
        echo -e "${BLUE}=== Bluetooth GPS Data Monitor ===${NC}"
        echo "Device: $RFCOMM_DEVICE"
        echo "$(date '+%Y-%m-%d %H:%M:%S')"
        echo ""
        echo -e "${GREEN}Current Rate:${NC} $(format_bytes $RATE_BPS)/s"
        echo -e "${GREEN}Average Rate:${NC} $(format_bytes $AVG_RATE)/s"
        echo -e "${GREEN}Total Data:${NC} $(format_bytes $TOTAL_BYTES)"
        echo -e "${GREEN}Elapsed Time:${NC} ${ELAPSED}s"
        echo ""
        echo "Press Ctrl+C to stop"
    else
        echo -e "${YELLOW}No data received in last ${UPDATE_INTERVAL}s${NC}"
        sleep 1
    fi
done
