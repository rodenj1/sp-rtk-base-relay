"""SP-Base-Relay v2 main entry point and service orchestration.

Uses BroadcastHub + DestinationFactory for multi-destination fan-out.
"""

import argparse
import signal
import sys
import time
from pathlib import Path
from typing import Any

# Ensure destination builders are registered on import
import sp_rtk_base_relay.core.destinations as _destinations_registry  # pyright: ignore[reportUnusedImport]
from sp_rtk_base_relay import __version__
from sp_rtk_base_relay.config import Config, ConfigManager
from sp_rtk_base_relay.core.broadcast_hub import BroadcastHub
from sp_rtk_base_relay.core.destinations.base_destination import BaseDestination
from sp_rtk_base_relay.core.destinations.destination_factory import DestinationFactory
from sp_rtk_base_relay.core.input_sources.base_input import InputSource
from sp_rtk_base_relay.core.input_sources.input_factory import InputSourceFactory
from sp_rtk_base_relay.exceptions import (
    ConfigurationError,
    ServiceError,
    SPBaseRelayError,
)
from sp_rtk_base_relay.logger import LoggerManager, get_logger
from sp_rtk_base_relay.metrics import MetricsCollector

_ = _destinations_registry  # Keep pyright happy


class SPBaseRelayService:
    """Main service orchestration class for SP-Base-Relay v2.

    Coordinates input source → BroadcastHub → multiple destinations.
    BroadcastHub handles input reading, RTCM frame parsing, filtering,
    reconnection, and fan-out distribution internally.
    """

    def __init__(self, config: Config) -> None:
        """Initialize service with configuration.

        Args:
            config: Complete service configuration (v2 format with destinations list)
        """
        self.config = config
        self.logger = get_logger(__name__)
        self._running = False
        self._shutdown_requested = False

        # Components (initialized in start())
        self.metrics: MetricsCollector | None = None
        self.input_source: InputSource | None = None
        self.destinations: list[BaseDestination] = []
        self.hub: BroadcastHub | None = None

    def start(self) -> None:
        """Start the relay service.

        Initializes all components: input source, destinations, broadcast hub.

        Raises:
            ServiceError: If service fails to start
        """
        if self._running:
            raise ServiceError("Service is already running")

        self.logger.info(
            "Starting SP-Base-Relay v2 service",
            extra={"version": __version__, "input_source": self.config.input.source},
        )

        try:
            # Initialize metrics collector if enabled
            if self.config.metrics.enabled:
                self._start_metrics_server()

            # Create input source (unchanged from v1)
            self._create_input_source()

            # Create destinations from config
            self._create_destinations()

            # Create and start the broadcast hub
            self._start_hub()

            self._running = True
            self.logger.info(
                "SP-Base-Relay v2 service started successfully",
                extra={"destination_count": len(self.destinations)},
            )

        except Exception as e:
            self.logger.error(f"Failed to start service: {e}", exc_info=True)
            self._cleanup()
            raise ServiceError(f"Service startup failed: {e}") from e

    def stop(self) -> None:
        """Stop the relay service gracefully.

        Stops broadcast hub (which stops all destinations and input reading).
        """
        if not self._running:
            self.logger.warning("Service is not running")
            return

        self.logger.info("Stopping SP-Base-Relay v2 service")
        self._shutdown_requested = True

        try:
            # Stop hub (stops broadcast thread, destination threads, input thread)
            if self.hub:
                self.logger.info("Stopping broadcast hub")
                self.hub.stop()

            # Disconnect input source
            if self.input_source:
                self.logger.info("Disconnecting input source")
                self.input_source.disconnect()

            # Stop metrics server
            if self.metrics:
                self.logger.info("Stopping metrics server")
                self.metrics.stop_metrics_server()

            self._running = False
            self.logger.info("SP-Base-Relay v2 service stopped successfully")

        except Exception as e:
            self.logger.error(f"Error during service shutdown: {e}", exc_info=True)
            raise ServiceError(f"Service shutdown failed: {e}") from e

    def run(self) -> int:
        """Run the service until shutdown is requested.

        BroadcastHub handles input reading, reconnection, and distribution
        internally. This loop just monitors health and updates metrics.

        Returns:
            Exit code (0 for success, non-zero for error)
        """
        if not self._running:
            raise ServiceError("Service must be started before running")

        self.logger.info("Service running, press Ctrl+C to stop")

        try:
            while not self._shutdown_requested:
                # Check service health
                if not self._check_health():
                    self.logger.warning("Service health check failed")

                # Update metrics if enabled
                if self.metrics:
                    self._update_metrics()

                time.sleep(1.0)

            return 0

        except KeyboardInterrupt:
            self.logger.info("Received keyboard interrupt")
            return 0
        except Exception as e:
            self.logger.error(f"Service error: {e}", exc_info=True)
            return 1
        finally:
            self.stop()

    # ------------------------------------------------------------------
    # Component creation
    # ------------------------------------------------------------------

    def _start_metrics_server(self) -> None:
        """Start Prometheus metrics server."""
        self.logger.info(
            "Starting metrics server",
            extra={"host": self.config.metrics.host, "port": self.config.metrics.port},
        )
        self.metrics = MetricsCollector()
        self.metrics.start_metrics_server(
            port=self.config.metrics.port, host=self.config.metrics.host
        )

    def _create_input_source(self) -> None:
        """Create input source from configuration (unchanged from v1)."""
        self.logger.info(f"Creating input source: {self.config.input.source}")

        if self.config.input.source == "tcp":
            input_config: dict[str, Any] = {
                "host": self.config.input.get_tcp_config().host,
                "port": self.config.input.get_tcp_config().port,
                "timeout": self.config.input.get_tcp_config().timeout,
            }
        elif self.config.input.source in ("serial", "usb_serial"):
            serial_cfg = self.config.input.get_serial_config()
            input_config = {
                "port": serial_cfg.port,
                "baudrate": serial_cfg.baudrate,
                "timeout": serial_cfg.timeout,
                "bytesize": serial_cfg.bytesize,
                "parity": serial_cfg.parity,
                "stopbits": serial_cfg.stopbits,
            }
        elif self.config.input.source == "bluetooth":
            input_config = self.config.input.config
        else:
            raise ConfigurationError(
                f"Unsupported input source: {self.config.input.source}"
            )

        source_type = (
            "serial"
            if self.config.input.source in ("serial", "usb_serial")
            else self.config.input.source
        )

        self.input_source = InputSourceFactory.create_input_source(
            source_type, input_config
        )

    def _create_destinations(self) -> None:
        """Create destinations from v2 config using DestinationFactory.

        Raises:
            ConfigurationError: If no enabled destinations are configured
        """
        if not hasattr(self.config, "destinations") or not self.config.destinations:
            raise ConfigurationError(
                "No destinations configured. Use 'destinations:' list in config.",
                config_key="destinations",
            )

        self.destinations = DestinationFactory.create_all(self.config.destinations)

        if not self.destinations:
            raise ConfigurationError(
                "No enabled destinations found in configuration.",
                config_key="destinations",
            )

        for dest in self.destinations:
            self.logger.info(
                f"Created destination: {dest.name} ({dest.destination_type})"
            )

    def _start_hub(self) -> None:
        """Create and start the BroadcastHub.

        Raises:
            ServiceError: If input source or destinations not ready
        """
        if not self.input_source:
            raise ServiceError("Input source must be created first")
        if not self.destinations:
            raise ServiceError("Destinations must be created first")

        self.logger.info("Starting broadcast hub")

        self.hub = BroadcastHub(
            input_source=self.input_source,
            destinations=self.destinations,
        )
        self.hub.start()

    # ------------------------------------------------------------------
    # Health & metrics
    # ------------------------------------------------------------------

    def _check_health(self) -> bool:
        """Check service health.

        Returns:
            True if hub is running, False otherwise
        """
        if not self.hub:
            return False
        return self.hub.is_running

    def _update_metrics(self) -> None:
        """Update all Prometheus metrics (v2 per-destination + global).

        Reads DestinationStats from each destination and BroadcastHub
        health data. Called once per main-loop iteration (~1 s).
        """
        if not self.metrics or not self.hub:
            return

        try:
            input_connected = (
                self.input_source.is_connected if self.input_source else False
            )

            self.metrics.update_all(
                destinations=self.destinations,
                hub=self.hub,
                input_connected=input_connected,
            )

        except Exception as e:
            self.logger.warning(f"Failed to update metrics: {e}")

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def _cleanup(self) -> None:
        """Clean up resources on error."""
        try:
            if self.hub:
                self.hub.stop()
            if self.input_source:
                self.input_source.disconnect()
            if self.metrics:
                self.metrics.stop_metrics_server()
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")


def create_parser() -> argparse.ArgumentParser:
    """Create command-line argument parser.

    Returns:
        Configured argument parser
    """
    parser = argparse.ArgumentParser(
        prog="sp-rtk-base-relay",
        description="RTCM relay service for custom GPS correction servers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start service with configuration file
  sp-rtk-base-relay --config /etc/sp-rtk-base-relay/config.yaml
  
  # Validate configuration
  sp-rtk-base-relay --config config.yaml --validate
  
  # Generate example configuration
  sp-rtk-base-relay --generate-config > config.yaml
  
  # Run in foreground with debug logging
  sp-rtk-base-relay --config config.yaml --foreground --log-level DEBUG
        """,
    )

    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("/etc/sp-rtk-base-relay/config.yaml"),
        help="Path to configuration file (default: /etc/sp-rtk-base-relay/config.yaml)",
    )

    parser.add_argument(
        "--validate", action="store_true", help="Validate configuration and exit"
    )

    parser.add_argument(
        "--generate-config",
        action="store_true",
        help="Generate example configuration and exit",
    )

    parser.add_argument(
        "--foreground", action="store_true", help="Run in foreground (do not daemonize)"
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Override configured log level",
    )

    return parser


def setup_signal_handlers(service: SPBaseRelayService) -> None:
    """Set up signal handlers for graceful shutdown.

    Args:
        service: Service instance to shut down on signal
    """

    def signal_handler(signum: int, frame: Any) -> None:
        """Handle shutdown signals."""
        signal_name = signal.Signals(signum).name
        logger = get_logger(__name__)
        logger.info(f"Received signal {signal_name}, initiating graceful shutdown")
        service.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def main() -> int:
    """Main entry point for SP-Base-Relay.

    Returns:
        Exit code (0 for success, non-zero for error)
    """
    parser = create_parser()
    args = parser.parse_args()

    # Handle generate-config mode
    if args.generate_config:
        print(ConfigManager.generate_default_config())
        return 0

    # Load configuration
    try:
        config_manager = ConfigManager()
        config = config_manager.load_config(str(args.config))
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        return 1

    # Override log level if specified
    if args.log_level:
        config.logging.level = args.log_level

    # Setup logging
    try:
        LoggerManager.setup_logging(config.logging)
        logger = get_logger(__name__)
    except Exception as e:
        print(f"Error setting up logging: {e}", file=sys.stderr)
        return 1

    # Handle validate mode
    if args.validate:
        logger.info("Configuration validation successful")
        print("Configuration is valid")
        return 0

    # Create and start service
    try:
        service = SPBaseRelayService(config)
        setup_signal_handlers(service)
        service.start()
        exit_code = service.run()
        LoggerManager.shutdown_logging()
        return exit_code

    except SPBaseRelayError as e:
        logger.error(f"Service error: {e}")
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
