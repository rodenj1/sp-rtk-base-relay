"""Bluetooth device manager using BlueZ D-Bus API.

This module provides a Python wrapper around the BlueZ D-Bus API for managing
Bluetooth device discovery, pairing, trusting, and connection operations.

Uses dbus-fast for modern, type-safe D-Bus communication with full type hints.
A persistent background event loop thread maintains the D-Bus connection,
with sync wrappers dispatching coroutines via run_coroutine_threadsafe().
"""

import asyncio
import logging
import threading
import time
from typing import TYPE_CHECKING, Annotated, Any, cast

if TYPE_CHECKING:
    from dbus_fast import BusType, DBusError, Variant
    from dbus_fast.aio import MessageBus as AioMessageBus
    from dbus_fast.introspection import Node

try:
    from dbus_fast import BusType, DBusError, Variant
    from dbus_fast.aio import MessageBus as AioMessageBus
    from dbus_fast.annotations import DBusSignature
    from dbus_fast.introspection import Node
    from dbus_fast.service import ServiceInterface, dbus_method

    _dbus_fast_available = True

    # D-Bus signature type aliases for Agent1 method parameters/returns.
    # dbus-fast's @dbus_method() reads these Annotated signatures to build
    # the interface's D-Bus introspection XML.
    _DBusObjectPath = Annotated[str, DBusSignature("o")]
    _DBusStr = Annotated[str, DBusSignature("s")]
    _DBusUInt32 = Annotated[int, DBusSignature("u")]
    _DBusUInt16 = Annotated[int, DBusSignature("q")]

    class _PairingAgent(ServiceInterface):
        """``org.bluez.Agent1`` implementation for unattended pairing.

        Every device this project pairs with is a fixed, pre-configured
        device rather than a walk-up-and-pair UX, so the confirmation/
        authorization methods auto-accept unconditionally. ``RequestPinCode``
        answers with the PIN recorded for whichever pairing attempt is
        currently in flight against that device path (see
        ``BluetoothManager._pending_pins``); an unrecognized device path is
        rejected outright, never answered with a guess. The remaining
        PIN/passkey methods are implemented (BlueZ has no graceful fallback
        for a missing method — an unimplemented one is a silent dispatch
        failure) but reject every call: there is no source for a displayed
        PIN/passkey or a keyboard-entered passkey wired up.

        Method names match the ``org.bluez.Agent1`` D-Bus interface
        exactly (BlueZ dispatches by this literal name), so they can't
        be snake_case — each is annotated ``# noqa: N802``.
        """

        def __init__(self, pending_pins: dict[str, str]) -> None:
            super().__init__(_AGENT_INTERFACE)
            self._pending_pins = pending_pins

        @dbus_method()
        def Release(self) -> None:  # noqa: N802
            pass

        @dbus_method()
        def Cancel(self) -> None:  # noqa: N802
            pass

        @dbus_method()
        def RequestConfirmation(  # noqa: N802
            self, device: _DBusObjectPath, passkey: _DBusUInt32
        ) -> None:
            pass

        @dbus_method()
        def RequestAuthorization(self, device: _DBusObjectPath) -> None:  # noqa: N802
            pass

        @dbus_method()
        def AuthorizeService(  # noqa: N802
            self, device: _DBusObjectPath, uuid: _DBusStr
        ) -> None:
            pass

        @dbus_method()
        def RequestPinCode(self, device: _DBusObjectPath) -> _DBusStr:  # noqa: N802
            pin = self._pending_pins.get(device)
            if pin is None:
                if not self._pending_pins:
                    # No local Pair()/Connect() call is in flight anywhere
                    # on this manager, so this request could only have
                    # reached us as BlueZ's default agent answering for a
                    # pairing this process did not initiate -- see
                    # "Caller-less pairing" in CONTEXT.md. Distinct from a
                    # wrong PIN: named explicitly so an operator reading
                    # the logs doesn't mistake it for one.
                    raise DBusError(
                        "org.bluez.Error.Rejected",
                        f"Rejecting caller-less pairing on {device}: no "
                        "local pairing attempt is in flight, so this "
                        "request reached us as BlueZ's default agent for "
                        "a pairing this process did not initiate. No PIN "
                        "can be known for it by design -- this is not a "
                        "wrong-PIN failure. If this pairing was intended, "
                        "initiate it deliberately via pair_device() or "
                        "force_repair().",
                    )
                raise DBusError(
                    "org.bluez.Error.Rejected",
                    f"No PIN recorded for pending pairing attempt on {device}",
                )
            return pin

        @dbus_method()
        def DisplayPinCode(  # noqa: N802
            self, device: _DBusObjectPath, pincode: _DBusStr
        ) -> None:
            raise DBusError(
                "org.bluez.Error.Rejected", "PIN delivery is not yet supported"
            )

        @dbus_method()
        def RequestPasskey(self, device: _DBusObjectPath) -> _DBusUInt32:  # noqa: N802
            raise DBusError(
                "org.bluez.Error.Rejected", "Passkey delivery is not yet supported"
            )

        @dbus_method()
        def DisplayPasskey(  # noqa: N802
            self,
            device: _DBusObjectPath,
            passkey: _DBusUInt32,
            entered: _DBusUInt16,
        ) -> None:
            raise DBusError(
                "org.bluez.Error.Rejected", "Passkey delivery is not yet supported"
            )

except ImportError:
    _dbus_fast_available = False


logger = logging.getLogger(__name__)

# Default timeout for async operations dispatched to background loop
_DEFAULT_ASYNC_TIMEOUT = 60.0

# Best-effort timeout for the shutdown-time agent unregistration -- this
# must never meaningfully delay shutdown (see BluetoothManager.close()).
_AGENT_UNREGISTER_TIMEOUT = 5.0

# BlueZ's AgentManager1 always lives at this fixed path on the org.bluez
# service. The agent object path itself is freely definable; this repo's
# own namespace is used rather than reusing BlueZ's.
_AGENT_MANAGER_PATH = "/org/bluez"
_AGENT_INTERFACE = "org.bluez.Agent1"
_AGENT_OBJECT_PATH = "/org/sp_rtk_base_relay/agent"
_AGENT_CAPABILITY = "KeyboardOnly"


class BluetoothError(Exception):
    """Bluetooth-specific errors."""

    pass


class BluetoothManager:
    """Manages Bluetooth device operations via BlueZ D-Bus API.

    This class provides methods for device discovery, pairing, trusting,
    and connection management using the BlueZ Bluetooth stack through D-Bus.

    Uses a persistent background event loop thread to maintain the D-Bus
    connection. All async operations are dispatched to this single loop via
    asyncio.run_coroutine_threadsafe(), ensuring the MessageBus and its
    Futures always operate on the same event loop.

    Attributes:
        adapter_path: D-Bus object path for the adapter (e.g., "/org/bluez/hci0")
        _bus: Async D-Bus system bus connection
        _adapter: Bluetooth adapter proxy interface
        _introspection_cache: Cache of introspection XML by object path
        _loop: Persistent asyncio event loop running in background thread
        _thread: Background daemon thread running the event loop
    """

    def __init__(self, adapter_name: str = "hci0", claim_default_agent: bool = False):
        """Initialize Bluetooth manager.

        Creates a persistent background event loop thread, connects to the
        D-Bus system bus, and caches adapter introspection.

        Args:
            adapter_name: Name of Bluetooth adapter (default: "hci0")
            claim_default_agent: Whether to issue ``RequestDefaultAgent``
                after registering this manager's pairing agent, making it
                BlueZ's system-wide default -- the agent that answers a
                caller-less pairing (see CONTEXT.md). Defaults to
                ``False``: registering an agent already makes it the
                default when nobody else holds one (BlueZ >= 5.51), so
                the common single-manager case is unaffected; this flag
                only matters when more than one ``BluetoothManager``
                exists on the machine, and lets a manager that legitimately
                wants to keep answering caller-less pairings (this repo's
                own long-lived one) say so explicitly rather than seizing
                the default from whoever holds it -- another manager, a
                desktop pairing agent, an open ``bluetoothctl`` session.

                A manager cannot *decline* becoming the default: with an
                empty queue, registering makes you the default whether or
                not this flag is set. This flag makes the default
                *stable* -- first constructed wins, no churn -- not
                *chosen*; only ``claim_default_agent=True`` makes it
                chosen. ``connect_device()``'s ``pin`` argument is
                honoured only on a manager constructed with this flag set.

        Raises:
            BluetoothError: If dbus-fast is not available or adapter not found
        """
        if not _dbus_fast_available:
            raise BluetoothError(
                "dbus-fast library not available. Install with: uv add dbus-fast"
            )

        self.adapter_path = f"/org/bluez/{adapter_name}"
        self._claim_default_agent = claim_default_agent
        self._bus: AioMessageBus | None = None
        self._adapter: Any = None
        self._agent: Any = None
        # PIN recorded per device path for the duration of its pending
        # pairing attempt -- see _async_pair_device and _PairingAgent.
        self._pending_pins: dict[str, str] = {}

        # Hybrid introspection cache: pre-cache adapter/root, lazy-cache devices
        self._introspection_cache: dict[str, Node] = {}

        # Create persistent event loop in a background daemon thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="BluetoothDBusLoop"
        )
        self._thread.start()

        # Initialize bus on the persistent loop
        self._run_async(self._async_init())

    def _run_loop(self) -> None:
        """Run the event loop forever in the background thread."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_async(self, coro: Any, timeout: float = _DEFAULT_ASYNC_TIMEOUT) -> Any:
        """Dispatch a coroutine to the persistent background loop and block for result.

        Args:
            coro: Coroutine to execute on the background event loop
            timeout: Maximum seconds to wait for result (default: 60s)

        Returns:
            The coroutine's return value

        Raises:
            BluetoothError: If the coroutine raises or times out
        """
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except BluetoothError:
            raise
        except TimeoutError:
            future.cancel()
            raise BluetoothError(f"Async operation timed out after {timeout}s")
        except Exception as e:
            raise BluetoothError(f"Async operation failed: {e}")

    async def _async_init(self) -> None:
        """Initialize D-Bus connection and cache adapter introspection.

        Pre-caches introspection for adapter and root paths.
        """
        try:
            # Connect to system bus
            self._bus = await AioMessageBus(bus_type=BusType.SYSTEM).connect()  # type: ignore[misc]

            # Pre-cache adapter and root introspection (these never change)
            adapter_intro = await self._get_introspection(self.adapter_path)
            await self._get_introspection("/")  # Pre-cache root

            # Get adapter proxy interface
            adapter_proxy = self._bus.get_proxy_object(
                "org.bluez", self.adapter_path, adapter_intro
            )
            self._adapter = adapter_proxy.get_interface("org.bluez.Adapter1")  # type: ignore[arg-type]

            await self._async_register_agent()

            logger.info(
                f"Initialized Bluetooth manager with adapter {self.adapter_path}"
            )

        except DBusError as e:
            raise BluetoothError(f"D-Bus error initializing adapter: {e}")
        except BluetoothError:
            raise
        except Exception as e:
            raise BluetoothError(f"Failed to initialize Bluetooth adapter: {e}")

    async def _async_get_agent_manager(self) -> Any:
        """Get a proxy for BlueZ's ``org.bluez.AgentManager1`` interface.

        Raises:
            BluetoothError: If the bus is not initialized.
        """
        if self._bus is None:
            raise BluetoothError("Bus not initialized")

        agent_manager_intro = await self._get_introspection(_AGENT_MANAGER_PATH)
        agent_manager_proxy = self._bus.get_proxy_object(
            "org.bluez", _AGENT_MANAGER_PATH, agent_manager_intro
        )
        return agent_manager_proxy.get_interface("org.bluez.AgentManager1")

    async def _async_register_agent(self) -> None:
        """Register this manager's BlueZ pairing agent.

        Registration order matters: the local agent object must be
        exported on the bus before it's registered with BlueZ's agent
        manager, and ``RequestDefaultAgent`` (when issued at all) only
        after that -- otherwise an in-flight pairing event racing with
        startup could be dispatched to an object that doesn't exist yet.

        ``RequestDefaultAgent`` is issued only when this manager was
        constructed with ``claim_default_agent=True``. On the BlueZ floor
        this project supports (>= 5.51), ``RegisterAgent`` alone already
        makes the caller the default when the default-agent queue is
        empty -- the removed unconditional call never helped in that
        common case, its only effect was to displace whoever already held
        the default (see ``docs/adr/0002-*.md``).
        """
        if self._bus is None:
            raise BluetoothError("Bus not initialized")

        agent = _PairingAgent(self._pending_pins)
        self._bus.export(_AGENT_OBJECT_PATH, agent)
        self._agent = agent

        agent_manager = await self._async_get_agent_manager()
        await agent_manager.call_register_agent(_AGENT_OBJECT_PATH, _AGENT_CAPABILITY)

        if self._claim_default_agent:
            await agent_manager.call_request_default_agent(_AGENT_OBJECT_PATH)
            logger.info(
                "Registered pairing agent at %s and claimed it as BlueZ's "
                "default agent",
                _AGENT_OBJECT_PATH,
            )
        else:
            logger.info("Registered pairing agent at %s", _AGENT_OBJECT_PATH)

    async def _async_unregister_agent(self) -> None:
        """Unregister the pairing agent from BlueZ's agent manager.

        Not strictly required for correctness -- BlueZ tears an agent down
        automatically when its D-Bus connection closes -- but cleaner for
        default-agent handoff timing. Callers treat this as best-effort.
        """
        if self._bus is None or self._agent is None:
            return

        agent_manager = await self._async_get_agent_manager()
        await agent_manager.call_unregister_agent(_AGENT_OBJECT_PATH)

    def _invalidate_device_cache(self, device_path: str) -> None:
        """Remove a device path from the introspection cache.

        BlueZ may remove and re-create device D-Bus objects when a device
        disconnects and reconnects. Cached introspection XML from a previous
        session can become stale, causing ``InterfaceNotFoundError`` when
        the proxy tries to look up ``org.bluez.Device1``.

        This method evicts only device-specific paths (``/dev_`` prefix).
        Adapter and root paths are stable and kept cached.

        Args:
            device_path: D-Bus object path to invalidate (e.g.,
                ``/org/bluez/hci0/dev_00_11_22_33_44_55``).
        """
        if device_path in self._introspection_cache:
            logger.debug("Invalidating stale introspection cache for %s", device_path)
            del self._introspection_cache[device_path]

    async def _get_introspection(self, path: str) -> "Node":
        """Get introspection with caching (hybrid approach).

        Args:
            path: D-Bus object path

        Returns:
            Introspection Node object

        Raises:
            BluetoothError: If introspection fails
        """
        if path not in self._introspection_cache:
            try:
                if self._bus is None:
                    raise BluetoothError("Bus not initialized")
                introspection: Node = await self._bus.introspect("org.bluez", path)  # type: ignore[assignment]
                self._introspection_cache[path] = introspection
            except DBusError as e:
                raise BluetoothError(f"D-Bus error introspecting {path}: {e}")
            except BluetoothError:
                raise
            except Exception as e:
                raise BluetoothError(f"Failed to introspect {path}: {e}")

        return self._introspection_cache[path]

    def find_device_by_name(
        self, device_name: str, scan_timeout: int = 10
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
        return self._run_async(
            self._async_find_device_by_name(device_name, scan_timeout),
            timeout=max(scan_timeout + 30, _DEFAULT_ASYNC_TIMEOUT),
        )

    @staticmethod
    def _unwrap_variant(value: Any) -> Any:
        """Unwrap a dbus-fast Variant to its plain Python value.

        dbus-fast's GetManagedObjects returns property values wrapped in
        Variant objects. This helper extracts the raw value for comparison.

        Args:
            value: A dbus-fast Variant or plain Python value

        Returns:
            The unwrapped value
        """
        if hasattr(value, "value"):
            return value.value
        return value

    async def _async_find_device_in_known(self, device_name: str) -> str | None:
        """Search BlueZ's known/paired devices for a device by name.

        This checks devices already registered in BlueZ (paired, cached, etc.)
        WITHOUT running a Bluetooth scan. This is instant and works for
        already-paired devices that may not be actively advertising.

        Args:
            device_name: Bluetooth device name to search for

        Returns:
            MAC address if found among known devices, None otherwise
        """
        try:
            root_intro = await self._get_introspection("/")
            manager_proxy = self._bus.get_proxy_object("org.bluez", "/", root_intro)  # type: ignore[union-attr]
            manager = manager_proxy.get_interface("org.freedesktop.DBus.ObjectManager")

            raw_objects: Any = await manager.call_get_managed_objects()  # type: ignore[attr-defined]
            objects = cast(dict[str, dict[str, dict[str, Any]]], raw_objects)

            for _path, interfaces in objects.items():
                if "org.bluez.Device1" in interfaces:
                    device_props: dict[str, Any] = interfaces["org.bluez.Device1"]
                    name: str | None = self._unwrap_variant(device_props.get("Name"))
                    if name == device_name:
                        mac_address: str | None = self._unwrap_variant(
                            device_props.get("Address")
                        )
                        logger.info(
                            f"Found {device_name} at {mac_address} (known device)"
                        )
                        return str(mac_address) if mac_address else None
        except Exception as e:
            logger.debug(f"Error checking known devices: {e}")

        return None

    async def _async_find_device_by_name(
        self, device_name: str, scan_timeout: int
    ) -> str | None:
        """Async implementation of find_device_by_name.

        First checks BlueZ's known devices (instant), then falls back to
        a full Bluetooth scan if the device is not already known.
        """
        try:
            if self._adapter is None:
                raise BluetoothError("Adapter not initialized")

            # Step 1: Check known/paired devices first (no scan needed)
            logger.info(f"Checking known devices for: {device_name}")
            mac = await self._async_find_device_in_known(device_name)
            if mac:
                return mac

            # Step 2: Not found among known devices, do a full scan
            logger.info(
                f"Device not in known list, scanning for: {device_name} "
                f"(timeout={scan_timeout}s)"
            )

            await self._adapter.call_start_discovery()  # type: ignore[attr-defined]
            await asyncio.sleep(scan_timeout)

            # Check again after scan (new devices may have appeared)
            mac = await self._async_find_device_in_known(device_name)

            try:
                await self._adapter.call_stop_discovery()  # type: ignore[attr-defined]
            except Exception:
                pass

            if mac:
                return mac

            logger.warning(f"Device {device_name} not found after scan")
            return None

        except DBusError as e:
            try:
                if self._adapter is not None:
                    await self._adapter.call_stop_discovery()  # type: ignore[attr-defined]
            except Exception:
                pass
            raise BluetoothError(f"D-Bus error during discovery: {e}")
        except BluetoothError:
            raise
        except Exception as e:
            try:
                if self._adapter is not None:
                    await self._adapter.call_stop_discovery()  # type: ignore[attr-defined]
            except Exception:
                pass
            raise BluetoothError(f"Device discovery failed: {e}")

    def find_device_by_mac(self, mac_address: str) -> bool:
        """Check if device with MAC address exists/is known.

        Args:
            mac_address: Device MAC address (e.g., "00:11:22:33:44:55")

        Returns:
            True if device exists, False otherwise
        """
        return self._run_async(self._async_find_device_by_mac(mac_address))

    async def _async_find_device_by_mac(self, mac_address: str) -> bool:
        """Async implementation of find_device_by_mac."""
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

        try:
            if self._bus is None:
                return False
            await self._get_introspection(device_path)
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
        return self._run_async(self._async_pair_device(mac_address, pin))

    async def _async_pair_device(self, mac_address: str, pin: str) -> bool:
        """Async implementation of pair_device."""
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

        try:
            if self._bus is None:
                raise BluetoothError("Bus not initialized")

            # Invalidate stale cache — BlueZ may have removed/recreated
            # the device object since the last session
            self._invalidate_device_cache(device_path)

            # Get device introspection and proxy
            device_intro = await self._get_introspection(device_path)
            device_proxy = self._bus.get_proxy_object(
                "org.bluez", device_path, device_intro
            )
            device_iface = device_proxy.get_interface("org.bluez.Device1")
            device_props = device_proxy.get_interface("org.freedesktop.DBus.Properties")

            # Check if already paired
            paired: bool = self._unwrap_variant(
                await device_props.call_get("org.bluez.Device1", "Paired")  # type: ignore[attr-defined]
            )
            if paired:
                logger.info(f"Device {mac_address} already paired")
                return True

            logger.info(f"Pairing with {mac_address}...")
            # Record the PIN for this device path immediately before the
            # pairing call starts, so the registered agent's
            # RequestPinCode can answer BlueZ if it asks. Cleared once
            # this attempt finishes, whether it succeeds or fails --
            # PINs aren't retained any longer than necessary.
            self._pending_pins[device_path] = pin
            try:
                await device_iface.call_pair()  # type: ignore[attr-defined]
            finally:
                self._pending_pins.pop(device_path, None)
            logger.info(f"Successfully paired with {mac_address}")
            return True

        except DBusError as e:
            raise BluetoothError(f"D-Bus error during pairing: {e}")
        except BluetoothError:
            raise
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
        return self._run_async(self._async_trust_device(mac_address))

    async def _async_trust_device(self, mac_address: str) -> bool:
        """Async implementation of trust_device."""
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

        try:
            if self._bus is None:
                raise BluetoothError("Bus not initialized")

            # Invalidate stale cache — device object may have changed
            self._invalidate_device_cache(device_path)

            # Get device introspection and proxy
            device_intro = await self._get_introspection(device_path)
            device_proxy = self._bus.get_proxy_object(
                "org.bluez", device_path, device_intro
            )
            device_props = device_proxy.get_interface("org.freedesktop.DBus.Properties")

            # Set Trusted property using dbus-fast Variant.
            # dbus-fast dynamically attaches ``call_*`` methods to ProxyInterface
            # via __getattr__; both mypy and pyright flag this pattern.
            device_props_any: Any = device_props
            await device_props_any.call_set(
                "org.bluez.Device1", "Trusted", Variant("b", True)
            )
            logger.info(f"Device {mac_address} is now trusted")
            return True

        except DBusError as e:
            raise BluetoothError(f"D-Bus error setting trust: {e}")
        except BluetoothError:
            raise
        except Exception as e:
            raise BluetoothError(f"Trust failed: {e}")

    def connect_device(
        self,
        mac_address: str,
        max_retries: int = 3,
        retry_delay: float = 2.0,
        pin: str | None = None,
    ) -> bool:
        """Connect to a paired Bluetooth device with retries.

        Args:
            mac_address: Device MAC address
            max_retries: Maximum connection attempts (default: 3)
            retry_delay: Seconds to wait between retries (default: 2.0)
            pin: Ephemeral PIN to answer BlueZ with if ``Connect()``
                triggers security elevation on a device that isn't yet
                bonded -- BlueZ routes that PIN request to the default
                agent, since it wasn't raised by a local ``Pair()`` call
                (a "caller-less pairing"; see CONTEXT.md). Recorded only
                for the duration of this call and never retained. Honoured
                only when this manager was constructed with
                ``claim_default_agent=True`` -- a caller-less PIN request
                always goes to the *default* agent, so a PIN recorded on a
                manager that doesn't hold it can never be reached.

        Returns:
            True if connected successfully

        Raises:
            BluetoothError: If all connection attempts fail, or if ``pin``
                is supplied on a manager that cannot receive a caller-less
                PIN request.
        """
        if pin is not None and not self._claim_default_agent:
            raise BluetoothError(
                "connect_device() was given a pin, but this manager was "
                "not constructed with claim_default_agent=True. A "
                "caller-less PIN request is always routed to BlueZ's "
                "default agent, so a PIN recorded on a non-default "
                "manager could never be reached."
            )

        timeout = max(max_retries * (retry_delay + 10), _DEFAULT_ASYNC_TIMEOUT)
        return self._run_async(
            self._async_connect_device(mac_address, max_retries, retry_delay, pin),
            timeout=timeout,
        )

    async def _async_connect_device(
        self,
        mac_address: str,
        max_retries: int,
        retry_delay: float,
        pin: str | None = None,
    ) -> bool:
        """Async implementation of connect_device."""
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

        try:
            if self._bus is None:
                raise BluetoothError("Bus not initialized")

            # Get device introspection and proxy
            device_intro = await self._get_introspection(device_path)
            device_proxy = self._bus.get_proxy_object(
                "org.bluez", device_path, device_intro
            )
            device_iface = device_proxy.get_interface("org.bluez.Device1")
            device_props = device_proxy.get_interface("org.freedesktop.DBus.Properties")

            # Check if already connected.  dbus-fast dynamically attaches
            # ``call_*`` methods to ProxyInterface; cast to Any to satisfy
            # static type-checkers.
            device_props_any: Any = device_props
            connected: bool = self._unwrap_variant(
                await device_props_any.call_get("org.bluez.Device1", "Connected")
            )
            if connected:
                logger.info(f"Device {mac_address} already connected")
                return True

            # Record the PIN for this device path immediately before the
            # connect attempt(s) start, so the registered agent's
            # RequestPinCode can answer BlueZ if a caller-less request
            # arrives. Cleared once this call finishes, whether it
            # succeeds or fails -- same no-retention pattern as
            # _async_pair_device.
            if pin is not None:
                self._pending_pins[device_path] = pin
            try:
                # Try connecting with retries
                last_error: DBusError | None = None
                for attempt in range(1, max_retries + 1):
                    try:
                        logger.info(
                            f"Connecting to {mac_address} (attempt {attempt}/{max_retries})..."
                        )
                        await device_iface.call_connect()  # type: ignore[attr-defined]
                        logger.info(f"Successfully connected to {mac_address}")
                        return True
                    except DBusError as e:
                        last_error = e
                        error_str = str(e)

                        # Check for "Operation currently not available" error
                        if (
                            "NotAvailable" in error_str
                            or "not available" in error_str.lower()
                        ):
                            if attempt < max_retries:
                                logger.warning(
                                    f"Device not ready (attempt {attempt}/{max_retries}), "
                                    f"waiting {retry_delay}s before retry..."
                                )
                                await asyncio.sleep(retry_delay)
                                continue

                        # For other errors, don't retry
                        raise BluetoothError(f"D-Bus connection error: {e}")

                # All retries exhausted
                raise BluetoothError(
                    f"Connection failed after {max_retries} attempts: {last_error}"
                )
            finally:
                if pin is not None:
                    self._pending_pins.pop(device_path, None)

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
        return self._run_async(self._async_disconnect_device(mac_address))

    async def _async_disconnect_device(self, mac_address: str) -> bool:
        """Async implementation of disconnect_device."""
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

        try:
            if self._bus is None:
                raise BluetoothError("Bus not initialized")

            # Get device introspection and proxy
            device_intro = await self._get_introspection(device_path)
            device_proxy = self._bus.get_proxy_object(
                "org.bluez", device_path, device_intro
            )
            device_iface = device_proxy.get_interface("org.bluez.Device1")

            await device_iface.call_disconnect()  # type: ignore[attr-defined]
            logger.info(f"Disconnected from {mac_address}")
            return True

        except DBusError as e:
            raise BluetoothError(f"D-Bus error during disconnect: {e}")
        except BluetoothError:
            raise
        except Exception as e:
            raise BluetoothError(f"Disconnection failed: {e}")

    def discover_rfcomm_channel(self, mac_address: str) -> int:
        """Discover the RFCOMM channel for Serial Port Profile (SPP).

        For most GPS devices using SPP, the channel is 1. This method
        provides a way to discover it, but defaults to 1 if not found.

        Args:
            mac_address: Device MAC address

        Returns:
            RFCOMM channel number (usually 1 for SPP)
        """
        # For now, return channel 1 (standard for SPP)
        # UUID for Serial Port Profile: 00001101-0000-1000-8000-00805f9b34fb
        # TODO: Could be enhanced to query SDP for exact channel
        logger.info(f"Using RFCOMM channel 1 for SPP on {mac_address}")
        return 1

    async def _async_wait_for_device_interface(
        self, mac_address: str, scan_timeout: int
    ) -> None:
        """Wait for ``org.bluez.Device1`` to be populated on the device path.

        BlueZ has a two-phase rediscovery pattern that bit us with the
        v2.1.2 fixed 5 s recovery scan:

        - **Phase 1** (after a short scan): the D-Bus object at
          ``/org/bluez/hci0/dev_<MAC>`` exists with stub metadata,
          but the ``org.bluez.Device1`` interface is NOT yet attached.
          ``pair_device`` raises "interface not found on this object:
          org.bluez.Device1" against this stub.
        - **Phase 2** (after ~20-30 s of active discovery, OR a second
          scan, OR a successful RFCOMM connection): the
          ``Device1`` interface is fully attached with all properties
          and the device is pairable.

        Empirically on a ZED-F9P over RTK_BASE Bluetooth:
        connecting within ~5 s of disconnect skips this dance (the
        interface is still cached).  Beyond ~30 s, the interface is
        stripped and only an active scan repopulates it.

        This method polls at 2 s intervals: re-introspect the device
        path → check for ``Device1`` → if missing, ensure discovery
        is running → wait → retry.  Returns as soon as ``Device1``
        appears; raises after ``scan_timeout`` seconds without it.

        Args:
            mac_address: Device MAC (used to derive the D-Bus path).
            scan_timeout: Total seconds to wait for the interface.
                Returns immediately as soon as ``Device1`` appears.

        Raises:
            BluetoothError: If the interface doesn't appear within
                ``scan_timeout`` seconds.
        """
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"
        deadline = time.monotonic() + scan_timeout
        discovery_started = False
        last_error: str = "(no introspection attempt yet)"

        while time.monotonic() < deadline:
            try:
                # Always re-introspect — the cached node may predate
                # BlueZ's interface eviction and we'd loop forever
                # checking a stale Node.
                self._invalidate_device_cache(device_path)
                if self._bus is None:
                    raise BluetoothError("Bus not initialized")
                intro: Node = await self._bus.introspect(  # type: ignore[assignment]
                    "org.bluez", device_path
                )
                self._introspection_cache[device_path] = intro
                if any(i.name == "org.bluez.Device1" for i in intro.interfaces):
                    if discovery_started:
                        try:
                            await self._adapter.call_stop_discovery()  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    logger.info(
                        "Device %s is ready (org.bluez.Device1 interface "
                        "populated) — proceeding to pair/trust",
                        mac_address,
                    )
                    return
                last_error = "Device1 interface missing on path"
            except DBusError as exc:
                last_error = f"D-Bus introspect failed: {exc}"
            except BluetoothError as exc:
                last_error = f"BluetoothError: {exc}"
            except Exception as exc:
                last_error = f"unexpected error: {exc}"

            # Interface not yet present — kick off discovery (idempotent)
            # so BlueZ has a chance to populate it during our next sleep.
            if not discovery_started:
                try:
                    await self._adapter.call_start_discovery()  # type: ignore[attr-defined]
                    discovery_started = True
                    logger.info(
                        "Started BlueZ discovery to populate Device1 interface for %s",
                        mac_address,
                    )
                except DBusError as exc:
                    err_str = str(exc)
                    if "InProgress" in err_str:
                        discovery_started = True
                    else:
                        logger.debug("call_start_discovery error (continuing): %s", exc)

            await asyncio.sleep(2.0)

        # Timed out — make sure discovery is stopped before we raise.
        if discovery_started:
            try:
                await self._adapter.call_stop_discovery()  # type: ignore[attr-defined]
            except Exception:
                pass
        raise BluetoothError(
            f"Device {mac_address} did not become available after "
            f"{scan_timeout}s of BlueZ discovery (org.bluez.Device1 "
            f"interface never appeared on path {device_path}).  Last "
            f"check: {last_error}.  Try a longer scan_timeout, or "
            "verify the device is powered on and advertising."
        )

    def _recovery_scan(self, mac_address: str, scan_seconds: int = 5) -> None:
        """Run a short HCI scan to re-register a device with BlueZ.

        When BlueZ loses track of a device (e.g., after disconnect or power
        cycle), its D-Bus object may be removed. A brief discovery scan
        causes BlueZ to re-create the device object so subsequent pair/trust
        operations can succeed.

        Args:
            mac_address: Device MAC address (for logging).
            scan_seconds: Duration of the scan in seconds (default: 5).
        """
        logger.info(
            "Running recovery scan to re-register %s with BlueZ (%ds)…",
            mac_address,
            scan_seconds,
        )
        try:
            self._run_async(
                self._async_recovery_scan(scan_seconds),
                timeout=max(scan_seconds + 15, _DEFAULT_ASYNC_TIMEOUT),
            )
        except Exception as exc:
            logger.warning("Recovery scan failed (non-fatal): %s", exc)

    async def _async_recovery_scan(self, scan_seconds: int) -> None:
        """Async implementation of recovery_scan."""
        if self._adapter is None:
            return
        try:
            await self._adapter.call_start_discovery()  # type: ignore[attr-defined]
            await asyncio.sleep(scan_seconds)
        except Exception:
            pass
        try:
            await self._adapter.call_stop_discovery()  # type: ignore[attr-defined]
        except Exception:
            pass

    def ensure_device_ready(
        self,
        pin: str,
        device_name: str | None = None,
        mac_address: str | None = None,
        scan_timeout: int = 30,
    ) -> tuple[str, int]:
        """Ensure device is discovered, paired, trusted, and return connection info.

        This is a convenience method that orchestrates the full device setup
        workflow.  It guarantees BlueZ has the ``org.bluez.Device1``
        interface populated on the device path before attempting
        pair/trust — the v2.1.2 fixed 5 s recovery scan was empirically
        too short to wait through BlueZ's two-phase rediscovery on a
        stale device path.

        Args:
            pin: PIN to use if BlueZ requests one during pairing (legacy
                PIN pairing). Forwarded to the underlying pairing call;
                has no effect for Secure Simple Pairing / Just Works
                devices, which never request a PIN.
            device_name: Name to search for (e.g., "RTK_GPS_BASE")
            mac_address: Or provide MAC directly if already known
            scan_timeout: Maximum seconds to wait for BlueZ to populate
                the ``org.bluez.Device1`` interface.  Returns early
                as soon as the interface is present (zero overhead
                when the device is already known to BlueZ).  Defaults
                to 30 s, which empirically covers BlueZ's worst-case
                two-phase rediscovery window on a ZED-F9P.

        Returns:
            Tuple of (mac_address, rfcomm_channel)

        Raises:
            BluetoothError: If any step fails.
        """
        # Discover device if only name provided
        if mac_address is None and device_name:
            mac_address = self.find_device_by_name(device_name, scan_timeout)
            if not mac_address:
                raise BluetoothError(f"Device {device_name} not found")

        if not mac_address:
            raise BluetoothError("Must provide either device_name or mac_address")

        # Wait for org.bluez.Device1 interface to be populated.  This
        # replaces the v2.1.2 "try once, do a 5 s recovery scan, try
        # again" pattern that empirically failed on a ZED-F9P when
        # BlueZ had stripped the Device1 interface (>~30 s since last
        # connect).  The poll-until-present approach handles both the
        # already-known fast path (zero overhead) and the cold/stale
        # path (active discovery up to ``scan_timeout``).
        self._run_async(
            self._async_wait_for_device_interface(mac_address, scan_timeout),
            timeout=max(float(scan_timeout) + 15.0, _DEFAULT_ASYNC_TIMEOUT),
        )

        # Interface guaranteed present — pair + trust now.
        self._pair_and_trust(mac_address, pin)

        # NOTE: We do NOT call connect_device() for SPP (Serial Port Profile) devices!
        # SPP devices (like GPS receivers) reject D-Bus Connect() calls with NotAvailable error.
        # This is normal/expected behavior - the RFCOMM socket connection itself establishes
        # the Bluetooth connection. This matches how the old rfcomm tool worked.
        logger.info(
            f"Device {mac_address} is paired and trusted, ready for RFCOMM socket connection"
        )

        # Get RFCOMM channel
        channel = self.discover_rfcomm_channel(mac_address)

        logger.info(f"Device {mac_address} ready on channel {channel}")
        return mac_address, channel

    def _pair_and_trust(self, mac_address: str, pin: str) -> None:
        """Pair and trust a device (helper for ensure_device_ready).

        Args:
            mac_address: Device MAC address.
            pin: PIN to use if BlueZ requests one during pairing.

        Raises:
            BluetoothError: If pairing or trusting fails.
        """
        if not self.pair_device(mac_address, pin):
            raise BluetoothError(f"Failed to pair with {mac_address}")

        if not self.trust_device(mac_address):
            raise BluetoothError(f"Failed to trust {mac_address}")

    def force_repair(self, mac_address: str, pin: str, scan_timeout: int = 30) -> bool:
        """Discard an existing bond and re-pair using a newly supplied PIN.

        For the case where a device's configured PIN changed after it was
        already bonded: ``pair_device``'s "already paired" fast path would
        otherwise make the new PIN permanently irrelevant, since it never
        re-attempts pairing against an existing bond. This is one atomic
        operation -- remove the bond, wait for BlueZ to repopulate the
        device's D-Bus interface (removal can transiently strip it, the
        same condition ``ensure_device_ready`` already handles by polling
        for it), re-pair with ``pin``, then trust -- rather than exposing
        removal and pairing as separate calls a caller could invoke out of
        order or leave half-done.

        Proceeds unconditionally regardless of the device's current bonded
        state: a "not found" outcome from the removal step is a harmless
        no-op, since the caller may not know the device was already
        unbonded. There is no rollback or retry -- if removal succeeds but
        the subsequent pairing or trust step then fails, the device is
        left in whatever state that step left it, and this method raises
        identifying which stage failed, rather than attempting to restore
        the prior (believed-wrong) bond.

        Args:
            mac_address: Device MAC address.
            pin: PIN to pair with. Required, with no default -- unlike
                ``pair_device``, defaulting the one argument this
                operation exists to change would be a footgun.
            scan_timeout: Maximum seconds to wait for BlueZ to repopulate
                the ``org.bluez.Device1`` interface after removal.

        Returns:
            True if the device was successfully removed, re-paired, and
            trusted.

        Raises:
            BluetoothError: Identifies which stage failed (remove, pair,
                or trust). A caller can use this to tell "still bonded,
                retry is free" apart from "now unbonded, retry needs
                attention."
        """

        def _remove_stage() -> None:
            self._remove_bond(mac_address)

        def _pair_stage() -> None:
            # A timeout waiting for BlueZ to repopulate org.bluez.Device1
            # is attributed to this stage too: the pairing call itself
            # can't even be attempted until the interface reappears.
            self._run_async(
                self._async_wait_for_device_interface(mac_address, scan_timeout),
                timeout=max(float(scan_timeout) + 15.0, _DEFAULT_ASYNC_TIMEOUT),
            )
            if not self.pair_device(mac_address, pin):
                raise BluetoothError(f"Failed to pair with {mac_address}")

        def _trust_stage() -> None:
            if not self.trust_device(mac_address):
                raise BluetoothError(f"Failed to trust {mac_address}")

        for stage_name, stage in (
            ("remove", _remove_stage),
            ("pair", _pair_stage),
            ("trust", _trust_stage),
        ):
            try:
                stage()
            except BluetoothError as e:
                raise BluetoothError(f"force_repair: {stage_name} stage failed: {e}")

        logger.info(f"force_repair succeeded for {mac_address}")
        return True

    def _remove_bond(self, mac_address: str) -> None:
        """Remove an existing bond for ``mac_address``, if any.

        Args:
            mac_address: Device MAC address.

        Raises:
            BluetoothError: If removal fails for a reason other than the
                device not currently being known to BlueZ.
        """
        self._run_async(self._async_remove_bond(mac_address))

    async def _async_remove_bond(self, mac_address: str) -> None:
        """Async implementation of _remove_bond."""
        device_path = f"{self.adapter_path}/dev_{mac_address.replace(':', '_')}"

        try:
            if self._bus is None:
                raise BluetoothError("Bus not initialized")
            if self._adapter is None:
                raise BluetoothError("Adapter not initialized")

            await self._adapter.call_remove_device(device_path)  # type: ignore[attr-defined]
            self._invalidate_device_cache(device_path)
            logger.info(f"Removed existing bond for {mac_address}")

        except BluetoothError:
            raise
        except Exception as e:
            if self._is_not_found_error(e):
                logger.info(f"Device {mac_address} was not bonded; nothing to remove")
                return
            if isinstance(e, DBusError):
                raise BluetoothError(f"D-Bus error removing device: {e}")
            raise BluetoothError(f"Failed to remove device: {e}")

    @staticmethod
    def _is_not_found_error(exc: Exception) -> bool:
        """Whether ``exc`` represents BlueZ's "device does not exist" error.

        Checks both the exception's message and, for a real ``DBusError``,
        its D-Bus error type name -- ``DBusError.__str__`` only returns
        the error's text, not its type, so a check against ``str(exc)``
        alone would miss ``org.bluez.Error.DoesNotExist`` replies whose
        text doesn't happen to repeat the type name.
        """
        haystack = f"{exc} {getattr(exc, 'type', '')}".lower()
        return "doesnotexist" in haystack or "does not exist" in haystack

    def close(self) -> None:
        """Clean up the background event loop and D-Bus connection.

        Disconnects from the D-Bus bus and stops the background event loop thread.
        """
        try:
            self._run_async(
                self._async_unregister_agent(), timeout=_AGENT_UNREGISTER_TIMEOUT
            )
        except Exception:
            pass

        try:
            if self._bus is not None:
                self._loop.call_soon_threadsafe(self._bus.disconnect)
        except Exception:
            pass

        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=5.0)
        except Exception:
            pass
