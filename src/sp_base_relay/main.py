"""SP-Base-Relay main entry point and service orchestration."""

import argparse
import signal
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from sp_base_relay import __version__
from sp_base_relay.config import Config, ConfigManager
from sp_base_relay.core.data_pipeline import DataPipelineCoordinator
from sp_base_relay.core.input_sources.base_input import InputSource
from sp_base_relay.core.input_sources.input_factory import InputSourceFactory
from sp_base_relay.core.rtcm_client import RTCMClient
from sp_base_relay.exceptions import (
    ConfigurationError,
    ServiceError,
    SPBaseRelayError,
)
from sp_base_relay.logger import LoggerManager, get_logger
from sp_base_relay.metrics import MetricsCollector


class SPBaseRelayService:
    """Main service orchestration class for SP-Base-Relay.

    Coordinates all components including configuration, logging, metrics,
    input sources, RTCM client, and data pipeline. Handles graceful startup
    and shutdown with proper signal handling.
    """

    def __init__(self, config: Config) -> None:
        """Initialize service with configuration.

        Args:
            config: Complete service configuration
        """
        self.config = config
        self.logger = get_logger(__name__)
        self._running = False
        self._shutdown_requested = False

        # Components (initialized in start())
        self.metrics: MetricsCollector | None = None
        self.input_source: InputSource | None = None
        self.rtcm_client: RTCMClient | None = None
        self.pipeline: DataPipelineCoordinator | None = None
        self._pipeline_thread: threading.Thread | None = None

        # Previous stats for delta calculations
        self._prev_rtcm_stats: Any | None = None
        self._prev_pipeline_stats: Any | None = None
        self._prev_input_stats: Any | None = None

        # Restart tracking
        self._restart_count = 0
        self._max_restart_attempts = 60  # Allow ~60 minutes of retries (60 attempts × 60s avg)
        self._last_restart_time: float = 0.0
        self._min_uptime_for_reset = 300.0  # 5 minutes

    def start(self) -> None:
        """Start the relay service.

        Initializes all components and starts the data relay pipeline.

        Raises:
            ServiceError: If service fails to start
        """
        if self._running:
            raise ServiceError("Service is already running")

        self.logger.info(
            "Starting SP-Base-Relay service",
            extra={"version": __version__, "input_source": self.config.input.source},
        )

        try:
            # Initialize metrics collector if enabled
            if self.config.metrics.enabled:
                self._start_metrics_server()

            # Create input source
            self._create_input_source()

            # Create RTCM client
            self._create_rtcm_client()

            # Create and start data pipeline
            self._start_pipeline()

            self._running = True
            self.logger.info("SP-Base-Relay service started successfully")

        except Exception as e:
            self.logger.error(f"Failed to start service: {e}", exc_info=True)
            self._cleanup()
            raise ServiceError(f"Service startup failed: {e}") from e

    def stop(self) -> None:
        """Stop the relay service gracefully.

        Stops all components in reverse order and ensures proper cleanup.
        """
        if not self._running:
            self.logger.warning("Service is not running")
            return

        self.logger.info("Stopping SP-Base-Relay service")
        self._shutdown_requested = True

        try:
            # Stop pipeline first (stops data flow)
            if self.pipeline:
                self.logger.info("Stopping data pipeline")
                self.pipeline.stop_relay()

            # Disconnect input source
            if self.input_source:
                self.logger.info("Disconnecting input source")
                self.input_source.disconnect()

            # Disconnect RTCM client
            if self.rtcm_client:
                self.logger.info("Disconnecting RTCM client")
                self.rtcm_client.disconnect()

            # Stop metrics server
            if self.metrics:
                self.logger.info("Stopping metrics server")
                self.metrics.stop_metrics_server()

            self._running = False
            self.logger.info("SP-Base-Relay service stopped successfully")

        except Exception as e:
            self.logger.error(f"Error during service shutdown: {e}", exc_info=True)
            raise ServiceError(f"Service shutdown failed: {e}") from e

    def run(self) -> int:
        """Run the service until shutdown is requested.

        Monitors service health and handles graceful shutdown.

        Returns:
            Exit code (0 for success, non-zero for error)
        """
        if not self._running:
            raise ServiceError("Service must be started before running")

        self.logger.info("Service running, press Ctrl+C to stop")

        try:
            # Main service loop
            while not self._shutdown_requested:
                # Check if pipeline thread has stopped (indicates restart needed)
                if self._pipeline_thread and not self._pipeline_thread.is_alive():
                    # Log at INFO for first restart (expected), WARNING for retries (problems)
                    if self._restart_count == 0:
                        self.logger.info("Pipeline thread stopped, initiating reconnection")
                    else:
                        self.logger.warning(
                            f"Pipeline thread stopped again, initiating restart (retry {self._restart_count + 1})"
                        )
                    
                    # Check restart limits
                    if self._restart_count >= self._max_restart_attempts:
                        self.logger.error(
                            f"Maximum restart attempts ({self._max_restart_attempts}) reached, stopping service"
                        )
                        return 1
                    
                    # Attempt pipeline restart
                    if not self._restart_pipeline():
                        self.logger.warning(
                            f"Pipeline restart attempt {self._restart_count}/{self._max_restart_attempts} failed, "
                            "will retry on next iteration"
                        )
                        # Don't exit - continue loop to retry
                        # The restart counter is already incremented in _restart_pipeline()
                        # Next iteration will try again after the sleep delay
                    else:
                        # Restart succeeded, continue monitoring
                        pass
                    
                    continue

                # Check service health
                if not self._check_health():
                    self.logger.warning("Service health check failed")

                # Reset restart counter if we've been running successfully for a while
                if (self._restart_count > 0 and 
                    self.pipeline and 
                    self.pipeline.pipeline_statistics.uptime_start is not None):
                    uptime = time.time() - self.pipeline.pipeline_statistics.uptime_start
                    if uptime >= self._min_uptime_for_reset:
                        self.logger.info(
                            f"Pipeline stable for {uptime:.0f}s, resetting restart counter"
                        )
                        self._restart_count = 0

                # Update metrics if enabled
                if self.metrics and self.pipeline:
                    self._update_metrics()

                # Sleep to avoid busy waiting
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
        """Create input source from configuration."""
        self.logger.info(f"Creating input source: {self.config.input.source}")

        # Get input config dict
        if self.config.input.source == "tcp":
            input_config = {
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
            # Bluetooth config is already in the right format
            input_config = self.config.input.config
        else:
            raise ConfigurationError(
                f"Unsupported input source: {self.config.input.source}"
            )

        # Use 'serial' as the type for both serial and usb_serial
        source_type = (
            "serial"
            if self.config.input.source in ("serial", "usb_serial")
            else self.config.input.source
        )

        self.input_source = InputSourceFactory.create_input_source(
            source_type, input_config
        )

    def _create_rtcm_client(self) -> None:
        """Create RTCM client from configuration."""
        self.logger.info(
            "Creating RTCM client",
            extra={"host": self.config.server.host, "port": self.config.server.port},
        )

        self.rtcm_client = RTCMClient(self.config.server)

    def _start_pipeline(self) -> None:
        """Start data pipeline coordinator in a separate thread."""
        self.logger.info("Starting data pipeline")

        if not self.input_source or not self.rtcm_client:
            raise ServiceError("Input source and RTCM client must be created first")

        self.pipeline = DataPipelineCoordinator(
            input_source=self.input_source,
            rtcm_client=self.rtcm_client,
            metrics_collector=self.metrics,
        )

        # Start pipeline in a separate thread (start_relay blocks)
        self._pipeline_thread = threading.Thread(
            target=self.pipeline.start_relay,
            name="DataPipeline",
            daemon=False
        )
        self._pipeline_thread.start()

        # Wait a moment for pipeline to start
        time.sleep(0.5)

        # Verify pipeline started successfully
        if not self.pipeline.is_running:
            raise ServiceError("Pipeline failed to start")

    def _check_health(self) -> bool:
        """Check service health.

        Returns:
            True if service is healthy, False otherwise
        """
        if not self.pipeline:
            return False

        return self.pipeline.is_healthy

    def _update_metrics(self) -> None:
        """Update Prometheus metrics from component stats."""
        if not self.metrics or not self.pipeline:
            return

        try:
            # Get current stats (properties, not methods)
            pipeline_stats = self.pipeline.pipeline_statistics

            # Update metrics with previous stats for delta calculations
            self.metrics.update_from_pipeline_stats(
                pipeline_stats, self._prev_pipeline_stats
            )

            if self.input_source:
                input_stats = self.input_source.connection_statistics
                self.metrics.update_from_input_stats(input_stats, self._prev_input_stats)
                # Store COPY of current stats as previous for next iteration
                try:
                    self._prev_input_stats = replace(input_stats)
                except (TypeError, AttributeError):
                    # Fallback for non-dataclass objects (e.g., in tests)
                    self._prev_input_stats = input_stats

            if self.rtcm_client:
                rtcm_stats = self.rtcm_client.connection_statistics
                self.metrics.update_from_rtcm_stats(rtcm_stats, self._prev_rtcm_stats)
                # Store COPY of current stats as previous for next iteration
                try:
                    self._prev_rtcm_stats = replace(rtcm_stats)
                except (TypeError, AttributeError):
                    # Fallback for non-dataclass objects (e.g., in tests)
                    self._prev_rtcm_stats = rtcm_stats

            # Store COPY of current pipeline stats as previous for next iteration
            try:
                self._prev_pipeline_stats = replace(pipeline_stats)
            except (TypeError, AttributeError):
                # Fallback for non-dataclass objects (e.g., in tests)
                self._prev_pipeline_stats = pipeline_stats

            # Update connection status (properties, not methods)
            rtcm_connected = (
                self.rtcm_client.is_connected if self.rtcm_client else False
            )
            input_connected = (
                self.input_source.is_connected if self.input_source else False
            )
            self.metrics.update_connection_status(
                rtcm_connected=rtcm_connected, input_connected=input_connected
            )

            # Update pipeline status (property, not method)
            self.metrics.update_pipeline_status(running=self.pipeline.is_running)

            # Update service uptime
            self.metrics.update_service_uptime()

        except Exception as e:
            self.logger.warning(f"Failed to update metrics: {e}")

    def _restart_pipeline(self) -> bool:
        """Restart the data pipeline with fresh connections.

        Returns:
            True if restart successful, False otherwise
        """
        self._restart_count += 1
        self.logger.info(
            f"Attempting pipeline restart (attempt {self._restart_count}/{self._max_restart_attempts})"
        )

        try:
            # Wait for pipeline thread to fully stop
            if self._pipeline_thread and self._pipeline_thread.is_alive():
                self._pipeline_thread.join(timeout=5.0)
                if self._pipeline_thread.is_alive():
                    self.logger.error("Pipeline thread did not stop cleanly")
                    return False

            # Reset and get retry delay from RTCM client (ensures initial delay is used)
            if self.rtcm_client:
                self.rtcm_client.reset_retry_delay()
                retry_delay = self.rtcm_client.get_retry_delay()
                self.logger.info(f"Waiting {retry_delay}s before reconnection attempt")
                time.sleep(retry_delay)

            # Cleanup old connections with verification
            self.logger.debug("Cleaning up old connections")
            try:
                if self.input_source:
                    self.input_source.disconnect()
                    time.sleep(0.1)  # Let OS release resources
            except Exception as e:
                self.logger.debug(f"Input source cleanup error (expected if already disconnected): {e}")

            try:
                if self.rtcm_client:
                    # Verify socket is cleared before disconnect
                    if self.rtcm_client.socket is not None:
                        self.logger.warning("Socket still exists before disconnect - disconnect() will handle cleanup")
                    
                    self.rtcm_client.disconnect()
                    
                    # Extra time after disconnect for OS to release FD
                    time.sleep(0.2)
                    
                    # Verify socket is now None
                    if self.rtcm_client.socket is not None:
                        self.logger.error("Socket cleanup failed - socket still exists!")
                    else:
                        self.logger.debug("Socket confirmed cleared")
                    
                    # CRITICAL: Verify HeartbeatMonitor thread is actually dead
                    # This prevents "Bad file descriptor" errors on reconnection
                    monitor = self.rtcm_client.heartbeat_monitor
                    if monitor.thread:
                        # Poll until thread is confirmed dead (max 10 seconds)
                        for attempt in range(20):  # 20 * 0.5s = 10 seconds max
                            if not monitor.thread.is_alive():
                                self.logger.debug(
                                    f"HeartbeatMonitor thread confirmed dead after {attempt * 0.5:.1f}s"
                                )
                                break
                            time.sleep(0.5)
                        else:
                            # Thread still alive after 10 seconds
                            self.logger.error(
                                "HeartbeatMonitor thread still alive after 10 seconds - "
                                "proceeding anyway but connection may fail"
                            )
                    
                    # Extra delay before creating new client to ensure OS has fully released resources
                    time.sleep(0.2)
                    self.logger.debug("RTCM client cleanup complete, ready for new connection")
            except Exception as e:
                self.logger.debug(f"RTCM client cleanup error (expected if already disconnected): {e}")

            # Create fresh input source
            self.logger.debug("Creating fresh input source")
            self._create_input_source()

            # Create fresh RTCM client
            self.logger.debug("Creating fresh RTCM client")
            self._create_rtcm_client()

            # Start new pipeline
            self.logger.debug("Starting new pipeline")
            self._start_pipeline()

            # Reset metrics previous stats for fresh start
            self._prev_rtcm_stats = None
            self._prev_pipeline_stats = None
            self._prev_input_stats = None

            self.logger.info("Pipeline restarted successfully")
            self._last_restart_time = time.time()
            return True

        except Exception as e:
            self.logger.error(f"Pipeline restart failed: {e}", exc_info=True)
            return False

    def _cleanup(self) -> None:
        """Clean up resources on error."""
        try:
            if self.pipeline:
                self.pipeline.stop_relay()
            if self.input_source:
                self.input_source.disconnect()
            if self.rtcm_client:
                self.rtcm_client.disconnect()
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
        prog="sp-base-relay",
        description="RTCM relay service for custom GPS correction servers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start service with configuration file
  sp-base-relay --config /etc/sp-base-relay/config.yaml
  
  # Validate configuration
  sp-base-relay --config config.yaml --validate
  
  # Generate example configuration
  sp-base-relay --generate-config > config.yaml
  
  # Run in foreground with debug logging
  sp-base-relay --config config.yaml --foreground --log-level DEBUG
        """,
    )

    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("/etc/sp-base-relay/config.yaml"),
        help="Path to configuration file (default: /etc/sp-base-relay/config.yaml)",
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

    # Register signal handlers
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

        # Setup signal handlers for graceful shutdown
        setup_signal_handlers(service)

        # Start service
        service.start()

        # Run service
        exit_code = service.run()

        # Shutdown logging
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
