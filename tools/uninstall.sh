#!/bin/bash
# SP-Base-Relay Uninstallation Script
# This script removes sp-rtk-base-relay systemd service and optionally the package

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SERVICE_NAME="sp-rtk-base-relay"
SERVICE_USER="sp-rtk-base-relay"
SERVICE_GROUP="sp-rtk-base-relay"
CONFIG_DIR="/etc/sp-rtk-base-relay"
DATA_DIR="/var/lib/sp-rtk-base-relay"
LOG_DIR="/var/log/sp-rtk-base-relay"
SYSTEMD_DIR="/etc/systemd/system"

# Functions
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        print_error "This script must be run as root"
        echo "Please run: sudo $0"
        exit 1
    fi
}

stop_service() {
    print_info "Stopping service..."
    
    if systemctl is-active --quiet "$SERVICE_NAME.service"; then
        systemctl stop "$SERVICE_NAME.service"
        print_info "Service stopped"
    else
        print_warning "Service is not running"
    fi
}

disable_service() {
    print_info "Disabling service..."
    
    if systemctl is-enabled --quiet "$SERVICE_NAME.service" 2>/dev/null; then
        systemctl disable "$SERVICE_NAME.service"
        print_info "Service disabled"
    else
        print_warning "Service is not enabled"
    fi
}

remove_service() {
    print_info "Removing systemd service..."
    
    SERVICE_FILE="$SYSTEMD_DIR/$SERVICE_NAME.service"
    if [[ -f "$SERVICE_FILE" ]]; then
        rm "$SERVICE_FILE"
        systemctl daemon-reload
        print_info "Systemd service removed"
    else
        print_warning "Service file not found: $SERVICE_FILE"
    fi
}

remove_package() {
    print_info "Checking for installed package..."
    
    if ! python3 -c "import sp_rtk_base_relay" 2>/dev/null; then
        print_warning "Package not installed"
        return
    fi
    
    echo ""
    read -p "Do you want to uninstall the sp-rtk-base-relay package? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Keeping package installed"
        return
    fi
    
    if command -v uv &> /dev/null; then
        print_info "Uninstalling with uv..."
        uv pip uninstall --system sp-rtk-base-relay
    elif command -v pip3 &> /dev/null; then
        print_info "Uninstalling with pip..."
        pip3 uninstall -y sp-rtk-base-relay
    else
        print_warning "Neither uv nor pip3 found, skipping package removal"
        return
    fi
    
    print_info "Package uninstalled"
}

remove_user() {
    print_info "Checking for system user and group..."
    
    echo ""
    read -p "Do you want to remove the system user and group? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Keeping user and group"
        return
    fi
    
    if id "$SERVICE_USER" &>/dev/null; then
        userdel "$SERVICE_USER"
        print_info "Removed user: $SERVICE_USER"
    else
        print_warning "User not found: $SERVICE_USER"
    fi
    
    if getent group "$SERVICE_GROUP" &>/dev/null; then
        groupdel "$SERVICE_GROUP"
        print_info "Removed group: $SERVICE_GROUP"
    else
        print_warning "Group not found: $SERVICE_GROUP"
    fi
}

remove_directories() {
    print_info "Checking for data directories..."
    
    echo ""
    echo "The following directories may contain data and logs:"
    echo "  - Configuration: $CONFIG_DIR"
    echo "  - Data: $DATA_DIR"
    echo "  - Logs: $LOG_DIR"
    echo ""
    read -p "Do you want to remove these directories? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Keeping data directories"
        print_warning "You may want to manually remove these directories later"
        return
    fi
    
    # Remove configuration directory
    if [[ -d "$CONFIG_DIR" ]]; then
        rm -rf "$CONFIG_DIR"
        print_info "Removed: $CONFIG_DIR"
    fi
    
    # Remove data directory
    if [[ -d "$DATA_DIR" ]]; then
        rm -rf "$DATA_DIR"
        print_info "Removed: $DATA_DIR"
    fi
    
    # Remove log directory
    if [[ -d "$LOG_DIR" ]]; then
        rm -rf "$LOG_DIR"
        print_info "Removed: $LOG_DIR"
    fi
}

print_summary() {
    echo ""
    echo "======================================"
    print_info "Uninstallation completed!"
    echo "======================================"
    echo ""
    
    # Check what's remaining
    REMAINING=()
    
    if python3 -c "import sp_rtk_base_relay" 2>/dev/null; then
        REMAINING+=("Package is still installed")
    fi
    
    if id "$SERVICE_USER" &>/dev/null; then
        REMAINING+=("User '$SERVICE_USER' still exists")
    fi
    
    if [[ -d "$CONFIG_DIR" ]]; then
        REMAINING+=("Configuration directory: $CONFIG_DIR")
    fi
    
    if [[ -d "$DATA_DIR" ]]; then
        REMAINING+=("Data directory: $DATA_DIR")
    fi
    
    if [[ -d "$LOG_DIR" ]]; then
        REMAINING+=("Log directory: $LOG_DIR")
    fi
    
    if [[ ${#REMAINING[@]} -gt 0 ]]; then
        echo "The following items were not removed:"
        for item in "${REMAINING[@]}"; do
            echo "  - $item"
        done
        echo ""
        echo "You can remove these manually if desired."
    else
        echo "All components have been removed."
    fi
    echo ""
}

# Main uninstallation process
main() {
    echo "======================================"
    echo "SP-Base-Relay Uninstallation Script"
    echo "======================================"
    echo ""
    
    check_root
    
    # Confirm uninstallation
    echo "This will remove the sp-rtk-base-relay systemd service."
    echo "You will be prompted for optional removals (package, user, data)."
    echo ""
    read -p "Do you want to continue? [y/N] " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        print_info "Uninstallation cancelled"
        exit 0
    fi
    
    stop_service
    disable_service
    remove_service
    remove_package
    remove_user
    remove_directories
    print_summary
}

# Run main function
main
