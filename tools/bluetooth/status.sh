#!/bin/bash
# Check status of all Bluetooth GPS and sp-base-relay services

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Service Status Check ===${NC}"
echo ""

# Check Bluetooth service
echo -e "${YELLOW}Bluetooth Service:${NC}"
systemctl status bluetooth --no-pager -l | head -n 10
echo ""

# Check Bluetooth GPS bridge
echo -e "${YELLOW}Bluetooth GPS Bridge Service:${NC}"
if systemctl list-unit-files | grep -q "bluetooth-gps.service"; then
    systemctl status bluetooth-gps --no-pager -l | head -n 10
else
    echo -e "${RED}Not installed${NC}"
    echo "Install with: sudo cp tools/systemd/bluetooth-gps.service /etc/systemd/system/"
fi
echo ""

# Check sp-base-relay service
echo -e "${YELLOW}SP-Base-Relay Service:${NC}"
if systemctl list-unit-files | grep -q "sp-base-relay.service"; then
    systemctl status sp-base-relay --no-pager -l | head -n 10
else
    echo -e "${RED}Not installed${NC}"
    echo "Install with: sudo cp tools/systemd/sp-base-relay.service /etc/systemd/system/"
fi
echo ""

# Check Bluetooth device
echo -e "${YELLOW}GPS Device (RTK_GPS_BASE):${NC}"
bluetoothctl info 00:11:22:33:44:55 2>/dev/null || echo -e "${RED}Device not found${NC}"
echo ""

# Check serial port
echo -e "${YELLOW}Serial Port (/dev/rfcomm0):${NC}"
if [ -e /dev/rfcomm0 ]; then
    ls -l /dev/rfcomm0
    echo -e "${GREEN}✓ Serial port exists${NC}"
else
    echo -e "${RED}✗ Serial port not found${NC}"
fi
echo ""

# Quick summary
echo -e "${BLUE}=== Quick Summary ===${NC}"
echo -n "Bluetooth: "
systemctl is-active --quiet bluetooth && echo -e "${GREEN}Active${NC}" || echo -e "${RED}Inactive${NC}"

echo -n "Bluetooth-GPS: "
systemctl is-active --quiet bluetooth-gps 2>/dev/null && echo -e "${GREEN}Active${NC}" || echo -e "${RED}Inactive${NC}"

echo -n "SP-Base-Relay: "
systemctl is-active --quiet sp-base-relay 2>/dev/null && echo -e "${GREEN}Active${NC}" || echo -e "${RED}Inactive${NC}"

echo -n "Serial Port: "
[ -e /dev/rfcomm0 ] && echo -e "${GREEN}Present${NC}" || echo -e "${RED}Missing${NC}"
