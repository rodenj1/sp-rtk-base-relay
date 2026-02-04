"""Bluetooth device manager using BlueZ D-Bus API.

This module provides a Python wrapper around the BlueZ D-Bus API for managing
Bluetooth device discovery, pairing, trusting, and connection operations.
"""

import logging
import time
from typing import Any

try:
    import pydbus
    _pydbus_available = True
except ImportError:
    _pydbus_available = False
    pydbus = None

logger = logging.getLogger(__name__)


class BluetoothError(Exception):
    """Bluetooth-specific errors."""
    pass


class BluetoothManager:
    """Manages Bluetooth device operations via BlueZ D-Bus API.
    
    This class provides methods for device discovery, pairing, trusting,
    and connection management using the BlueZ Bluetooth stack through D-Bus.
    
    Attributes:
        bus: D-Bus system bus connection
        adapter: Bluetooth adapter (usually hci0)
        adapter_path: D-Bus object path for the adapter
    """
    
    def __init__(self, adapter_name: str = "hci0"):
        """Initialize Bluetooth manager.
        
        Args:
            adapter_name: Name of Bluetooth adapter (default: "hci0")
            
        Raises:
            BluetoothError: If pydbus is not available or adapter not found
        """
        if not _pydbus_available or pydbus is None:
            raise BluetoothError(
                "pydbus library not available. Install with: uv add pydbus"
            )
        
        self.adapter_path = f"/org/bluez/{adapter_name}"
        
        try:
            self.bus = pydbus.SystemBus()
            self.adapter = self.bus.get("org.bluez", self.adapter_path)
            logger.info(f"Initialized Bluetooth manager with adapter {adapter_name}")
        except Exception as e:
            raise BluetoothError(f"Failed to initialize Bluetooth adapter: {e}")
    
    def find_device_by_name(
        self, 
        device_name: str, 
        scan_timeout: int = 10
    ) -> str | None:
        """Scan for device by name and return MAC address.
        
        Args:
            device_name: Bluetooth device name to search for
            scan_timeout: How long to scan in seconds (default: 10)
            
        Returns:
            MAC address if found, None otherwise
            
        Raises:
            BluetoothError: If scanning fails
        """
        try:
            logger.info(f"Scanning for device: {device_name}")
            
            # Start discovery
            self.adapter.StartDiscovery()
            
            # Wait for scan
            time.sleep(scan_timeout)
            
            # Get object manager to enumerate all Bluetooth objects
            manager = self.bus.get("org.bluez", "/")
            objects = manager.GetManagedObjects()
            
            # Search through discovered devices
            for path, interfaces in objects.items():
                if "org.bluez.Device1" in interfaces:
                    device = interfaces["org.bluez.Device1"]
                    if device.get("Name") == device_name:
                        mac_address = device.get("Address")
                        logger.info(f"Found {device_name} at {mac_address}")
                        self.adapter.StopDiscovery()
                        return mac_address
            
            self.adapter.StopDiscovery()
            logger.warning(f"Device {device_name} not found")
            return None
            
        except Exception as e:
            try:
                self.adapter.StopDiscovery()
            except:
                pass
            raise BluetoothError(f"Device discovery failed: {e}")
    
    def find_device_by_mac(self, mac_address: str) -> bool:
        """Check if device with MAC address exists/is known.
        
        Args:
            mac_address: Device MAC address (e.g., "00:11:22:33:44:55")
            
        Returns:
            True if device exists, False otherwise
        """
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"
        
        try:
            device = self.bus.get("org.bluez", device_path)
            return True
        except Exception:
            return False
    
    def pair_device(self, mac_address: str, pin: str = "0000") -> bool:
        """Pair with a Bluetooth device.
        
        Args:
            mac_address: Device MAC address
            pin: PIN code for pairing (default: "0000")
            
        Returns:
            True if paired successfully
            
        Raises:
            BluetoothError: If pairing fails
        """
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"
        
        try:
            device = self.bus.get("org.bluez", device_path)
            
            # Check if already paired
            if device.Paired:
                logger.info(f"Device {mac_address} already paired")
                return True
            
            logger.info(f"Pairing with {mac_address}...")
            device.Pair()
            logger.info(f"Successfully paired with {mac_address}")
            return True
            
        except Exception as e:
            raise BluetoothError(f"Pairing failed: {e}")
    
    def trust_device(self, mac_address: str) -> bool:
        """Trust a device so it can auto-reconnect.
        
        Args:
            mac_address: Device MAC address
            
        Returns:
            True if trusted successfully
            
        Raises:
            BluetoothError: If trust operation fails
        """
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"
        
        try:
            device = self.bus.get("org.bluez", device_path)
            device.Trusted = True
            logger.info(f"Device {mac_address} is now trusted")
            return True
        except Exception as e:
            raise BluetoothError(f"Trust failed: {e}")
    
    def connect_device(
        self, 
        mac_address: str,
        max_retries: int = 3,
        retry_delay: float = 2.0
    ) -> bool:
        """Connect to a paired Bluetooth device with retries.
        
        Args:
            mac_address: Device MAC address
            max_retries: Maximum connection attempts (default: 3)
            retry_delay: Seconds to wait between retries (default: 2.0)
            
        Returns:
            True if connected successfully
            
        Raises:
            BluetoothError: If all connection attempts fail
        """
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"
        
        try:
            device = self.bus.get("org.bluez", device_path)
            
            # Check if already connected
            if device.Connected:
                logger.info(f"Device {mac_address} already connected")
                return True
            
            # Try connecting with retries
            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info(f"Connecting to {mac_address} (attempt {attempt}/{max_retries})...")
                    device.Connect()
                    logger.info(f"Successfully connected to {mac_address}")
                    return True
                except Exception as e:
                    last_error = e
                    error_str = str(e)
                    
                    # Check for "Operation currently not available" error
                    if "NotAvailable" in error_str or "not available" in error_str.lower():
                        if attempt < max_retries:
                            logger.warning(
                                f"Device not ready (attempt {attempt}/{max_retries}), "
                                f"waiting {retry_delay}s before retry..."
                            )
                            time.sleep(retry_delay)
                            continue
                    
                    # For other errors, don't retry
                    raise BluetoothError(f"Connection failed: {e}")
            
            # All retries exhausted
            raise BluetoothError(f"Connection failed after {max_retries} attempts: {last_error}")
            
        except BluetoothError:
            raise
        except Exception as e:
            raise BluetoothError(f"Connection failed: {e}")
    
    def disconnect_device(self, mac_address: str) -> bool:
        """Disconnect from a Bluetooth device.
        
        Args:
            mac_address: Device MAC address
            
        Returns:
            True if disconnected successfully
            
        Raises:
            BluetoothError: If disconnection fails
        """
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"
        
        try:
            device = self.bus.get("org.bluez", device_path)
            device.Disconnect()
            logger.info(f"Disconnected from {mac_address}")
            return True
        except Exception as e:
            raise BluetoothError(f"Disconnection failed: {e}")
    
    def discover_rfcomm_channel(self, mac_address: str) -> int | None:
        """Discover the RFCOMM channel for Serial Port Profile (SPP).
        
        For most GPS devices using SPP, the channel is 1. This method
        provides a way to discover it, but defaults to 1 if not found.
        
        Args:
            mac_address: Device MAC address
            
        Returns:
            RFCOMM channel number (usually 1 for SPP)
        """
        # UUID for Serial Port Profile
        SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"
        
        # For now, return channel 1 (standard for SPP)
        # TODO: Could be enhanced to query SDP for exact channel
        logger.info(f"Using RFCOMM channel 1 for SPP on {mac_address}")
        return 1
    
    def ensure_device_ready(
        self,
        device_name: str | None = None,
        mac_address: str | None = None
    ) -> tuple[str, int]:
        """Ensure device is discovered, paired, trusted, connected, and return connection info.
        
        This is a convenience method that orchestrates the full device setup workflow.
        
        Args:
            device_name: Name to search for (e.g., "RTK_GPS_BASE")
            mac_address: Or provide MAC directly if already known
            
        Returns:
            Tuple of (mac_address, rfcomm_channel)
            
        Raises:
            BluetoothError: If any step fails
        """
        # Discover device if only name provided
        if mac_address is None and device_name:
            mac_address = self.find_device_by_name(device_name)
            if not mac_address:
                raise BluetoothError(f"Device {device_name} not found")
        
        if not mac_address:
            raise BluetoothError("Must provide either device_name or mac_address")
        
        # Ensure paired
        if not self.pair_device(mac_address):
            raise BluetoothError(f"Failed to pair with {mac_address}")
        
        # Ensure trusted
        if not self.trust_device(mac_address):
            raise BluetoothError(f"Failed to trust {mac_address}")
        
        # NOTE: We do NOT call connect_device() for SPP (Serial Port Profile) devices!
        # SPP devices (like GPS receivers) reject D-Bus Connect() calls with NotAvailable error.
        # This is normal/expected behavior - the RFCOMM socket connection itself establishes
        # the Bluetooth connection. This matches how the old rfcomm tool worked.
        logger.info(f"Device {mac_address} is paired and trusted, ready for RFCOMM socket connection")
        
        # Get RFCOMM channel
        channel = self.discover_rfcomm_channel(mac_address)
        if not channel:
            raise BluetoothError(f"Failed to discover RFCOMM channel for {mac_address}")
        
        logger.info(f"Device {mac_address} ready on channel {channel}")
        return mac_address, channel
