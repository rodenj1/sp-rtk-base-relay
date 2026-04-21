#!/bin/bash
# SP-Base-Relay Installation Script
# This script installs sp-rtk-base-relay as a systemd service

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
INSTALL_DIR="/usr/local/bin"
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

check_dependencies() {
    print_info "Checking dependencies..."
    
    # Check for Python 3.10+
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is not installed"
        exit 1
    fi
    
    PYTHON_VERSION=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    
    if [[ $PYTHON_MAJOR -lt 3 ]] || [[ $PYTHON_MAJOR -eq 3 && $PYTHON_MINOR -lt 10 ]]; then
        print_error "Python 3.10 or higher is required (found: $PYTHON_VERSION)"
        exit 1
    fi
    
    print_info "Python version: $PYTHON_VERSION ✓"
    
    # Check for systemd
    if ! command -v systemctl &> /dev/null; then
        print_error "systemd is not available"
        exit 1
    fi
    
    print_info "systemd is available ✓"
}

create_user() {
    print_info "Creating system user and group..."
    
    if id "$SERVICE_USER" &>/dev/null; then
        print_warning "User $SERVICE_USER already exists"
    else
        useradd --system --no-create-home --shell /bin/false "$SERVICE_USER"
        print_info "Created user: $SERVICE_USER"
    fi
    
    if getent group "$SERVICE_GROUP" &>/dev/null; then
        print_warning "Group $SERVICE_GROUP already exists"
    else
        groupadd --system "$SERVICE_GROUP"
        print_info "Created group: $SERVICE_GROUP"
    fi
}

create_directories() {
    print_info "Creating directories..."
    
    # Configuration directory
    mkdir -p "$CONFIG_DIR"
    chown root:root "$CONFIG_DIR"
    chmod 755 "$CONFIG_DIR"
    print_info "Created: $CONFIG_DIR"
    
    # Data directory
    mkdir -p "$DATA_DIR"
    chown "$SERVICE_USER:$SERVICE_GROUP" "$DATA_DIR"
    chmod 755 "$DATA_DIR"
    print_info "Created: $DATA_DIR"
    
    # Log directory
    mkdir -p "$LOG_DIR"
    chown "$SERVICE_USER:$SERVICE_GROUP" "$LOG_DIR"
    chmod 755 "$LOG_DIR"
    print_info "Created: $LOG_DIR"
}

install_package() {
    print_info "Installing sp-rtk-base-relay package..."
    
    # Check if package is installed
    if python3 -c "import sp_rtk_base_relay" 2>/dev/null; then
        print_warning "sp-rtk-base-relay package already installed"
        read -p "Do you want to upgrade? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Skipping package installation"
            return
        fi
    fi
    
    # Install or upgrade package
    if command -v uv &> /dev/null; then
        print_info "Installing with uv..."
        uv pip install --system sp-rtk-base-relay
    elif command -v pip3 &> /dev/null; then
        print_info "Installing with pip..."
        pip3 install sp-rtk-base-relay
    else
        print_error "Neither uv nor pip3 found"
        exit 1
    fi
    
    print_info "Package installed successfully"
}

setup_configuration() {
    print_info "Setting up configuration..."
    
    CONFIG_FILE="$CONFIG_DIR/config.yaml"
    
    if [[ -f "$CONFIG_FILE" ]]; then
        print_warning "Configuration file already exists: $CONFIG_FILE"
        read -p "Do you want to overwrite it? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            print_info "Keeping existing configuration"
            return
        fi
        
        # Backup existing config
        BACKUP_FILE="$CONFIG_FILE.backup.$(date +%Y%m%d_%H%M%S)"
        cp "$CONFIG_FILE" "$BACKUP_FILE"
        print_info "Backed up existing config to: $BACKUP_FILE"
    fi
    
    # Generate default configuration
    sp-rtk-base-relay --generate-config > "$CONFIG_FILE"
    chown root:root "$CONFIG_FILE"
    chmod 644 "$CONFIG_FILE"
    
    print_info "Created default configuration: $CONFIG_FILE"
    print_warning "IMPORTANT: Please edit $CONFIG_FILE with your settings before starting the service"
}

install_service() {
    print_info "Installing systemd service..."
    
    # Find the service file
    SERVICE_FILE=""
    if [[ -f "tools/systemd/$SERVICE_NAME.service" ]]; then
        SERVICE_FILE="tools/systemd/$SERVICE_NAME.service"
    elif [[ -f "systemd/$SERVICE_NAME.service" ]]; then
        SERVICE_FILE="systemd/$SERVICE_NAME.service"
    elif [[ -f "$SERVICE_NAME.service" ]]; then
        SERVICE_FILE="$SERVICE_NAME.service"
    else
        print_error "Service file not found. Please run this script from the project directory."
        exit 1
    fi
    
    # Copy service file
    cp "$SERVICE_FILE" "$SYSTEMD_DIR/$SERVICE_NAME.service"
    chmod 644 "$SYSTEMD_DIR/$SERVICE_NAME.service"
    
    # Reload systemd
    systemctl daemon-reload
    
    print_info "Systemd service installed"
}

enable_service() {
    print_info "Enabling service..."
    
    systemctl enable "$SERVICE_NAME.service"
    print_info "Service enabled (will start on boot)"
}

print_summary() {
    echo ""
    echo "======================================"
    print_info "Installation completed successfully!"
    echo "======================================"
    echo ""
    echo "Next steps:"
    echo "1. Edit the configuration file:"
    echo "   sudo nano $CONFIG_DIR/config.yaml"
    echo ""
    echo "2. Configure your RTCM server credentials and input source"
    echo ""
    echo "3. Start the service:"
    echo "   sudo systemctl start $SERVICE_NAME"
    echo ""
    echo "4. Check service status:"
    echo "   sudo systemctl status $SERVICE_NAME"
    echo ""
    echo "5. View logs:"
    echo "   sudo journalctl -u $SERVICE_NAME -f"
    echo ""
    echo "6. Enable auto-start on boot (if not already enabled):"
    echo "   sudo systemctl enable $SERVICE_NAME"
    echo ""
}

# Main installation process
main() {
    echo "======================================"
    echo "SP-Base-Relay Installation Script"
    echo "======================================"
    echo ""
    
    check_root
    check_dependencies
    create_user
    create_directories
    install_package
    setup_configuration
    install_service
    enable_service
    print_summary
}

# Run main function
main
