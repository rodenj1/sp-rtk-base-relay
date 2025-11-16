#!/usr/bin/env python3
"""Manual test script for production RTCM server validation.

This script performs end-to-end testing with the real RTCM server at
91.186.9.136:50010 using actual RTCM data from a TCP hardware source.

Usage:
    # Run with default 60 second duration
    uv run python tests/manual/test_production_rtcm.py

    # Run with custom duration
    uv run python tests/manual/test_production_rtcm.py --duration 120

    # With specific config file
    uv run python tests/manual/test_production_rtcm.py --config config.yaml --duration 300

    # Stop early with Ctrl+C for graceful shutdown
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path
from types import FrameType

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sp_base_relay.config import ConfigManager, RTCMServerConfig
from sp_base_relay.core.input_sources.tcp_input import TCPInputSource, TCPConfig
from sp_base_relay.core.rtcm_client import RTCMClient


# Global flag for graceful shutdown
shutdown_requested = False


def signal_handler(signum: int, frame: FrameType | None) -> None:
    """Handle Ctrl+C gracefully."""
    global shutdown_requested
    print("\n[INFO] Shutdown requested (Ctrl+C)... cleaning up")
    shutdown_requested = True


def setup_test_logging() -> logging.Logger:
    """Setup DEBUG level logging for the test."""
    # Configure root logger for DEBUG output
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(__name__)


def format_bytes(bytes_count: int) -> str:
    """Format bytes into human-readable string."""
    if bytes_count < 1024:
        return f"{bytes_count} B"
    elif bytes_count < 1024 * 1024:
        return f"{bytes_count / 1024:.1f} KB"
    else:
        return f"{bytes_count / (1024 * 1024):.1f} MB"


def format_duration(seconds: float) -> str:
    """Format duration in seconds to readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


class ProductionTestStatistics:
    """Track statistics during production test."""

    def __init__(self):
        self.start_time = time.time()
        self.bytes_transferred = 0
        self.messages_sent = 0
        self.heartbeats_received = 0
        self.input_read_attempts = 0
        self.input_read_successes = 0
        self.rtcm_send_attempts = 0
        self.rtcm_send_successes = 0
        self.input_errors = 0
        self.rtcm_errors = 0

    def elapsed_time(self) -> float:
        """Get elapsed time in seconds."""
        return time.time() - self.start_time

    def average_throughput(self) -> float:
        """Calculate average throughput in bytes/second."""
        elapsed = self.elapsed_time()
        return self.bytes_transferred / elapsed if elapsed > 0 else 0.0

    def success_rate(self) -> float:
        """Calculate overall success rate as percentage."""
        total_attempts = self.rtcm_send_attempts
        if total_attempts == 0:
            return 0.0
        return (self.rtcm_send_successes / total_attempts) * 100

    def print_progress(self, logger: logging.Logger) -> None:
        """Print progress update."""
        elapsed = self.elapsed_time()
        throughput = self.average_throughput()

        logger.info(
            f"[{elapsed:.0f}s] Transferred: {format_bytes(self.bytes_transferred)}, "
            f"Rate: {format_bytes(int(throughput))}/s, "
            f"Messages: {self.messages_sent}, "
            f"Heartbeats: {self.heartbeats_received}"
        )

    def print_final_report(self, logger: logging.Logger) -> None:
        """Print final statistics report."""
        elapsed = self.elapsed_time()
        throughput = self.average_throughput()
        success_rate = self.success_rate()

        logger.info("=" * 60)
        logger.info("FINAL STATISTICS REPORT")
        logger.info("=" * 60)
        logger.info(f"Test Duration: {format_duration(elapsed)}")
        logger.info(
            f"Bytes Transferred: {self.bytes_transferred:,} bytes ({format_bytes(self.bytes_transferred)})"
        )
        logger.info(f"Messages Sent: {self.messages_sent}")
        logger.info(f"Average Throughput: {format_bytes(int(throughput))}/s")
        logger.info(f"Heartbeats Received: {self.heartbeats_received}")
        logger.info("")
        logger.info("Input Source Statistics:")
        logger.info(f"  Read Attempts: {self.input_read_attempts}")
        logger.info(f"  Read Successes: {self.input_read_successes}")
        logger.info(f"  Read Errors: {self.input_errors}")
        logger.info("")
        logger.info("RTCM Server Statistics:")
        logger.info(f"  Send Attempts: {self.rtcm_send_attempts}")
        logger.info(f"  Send Successes: {self.rtcm_send_successes}")
        logger.info(f"  Send Errors: {self.rtcm_errors}")
        logger.info(f"  Success Rate: {success_rate:.1f}%")
        logger.info("=" * 60)


def run_production_test(
    tcp_config: TCPConfig,
    rtcm_config: RTCMServerConfig,
    duration: int,
    logger: logging.Logger,
) -> bool:
    """Run the production RTCM test.

    Args:
        tcp_config: TCP input source configuration
        rtcm_config: RTCM server configuration
        duration: Test duration in seconds
        logger: Logger instance

    Returns:
        True if test completed successfully, False otherwise
    """
    global shutdown_requested

    stats = ProductionTestStatistics()
    tcp_input: TCPInputSource | None = None
    rtcm_client: RTCMClient | None = None

    try:
        # Setup signal handler for Ctrl+C
        signal.signal(signal.SIGINT, signal_handler)

        logger.info("=" * 60)
        logger.info("PRODUCTION RTCM SERVER TEST")
        logger.info("=" * 60)
        logger.info(f"Test Duration: {duration} seconds")
        logger.info(f"TCP Input: {tcp_config.host}:{tcp_config.port}")
        logger.info(f"RTCM Server: {rtcm_config.host}:{rtcm_config.port}")
        logger.info(f"RTCM Username: {rtcm_config.username}")
        logger.info("=" * 60)

        # Create TCP input source
        logger.info("Connecting to TCP input source...")
        tcp_input = TCPInputSource(tcp_config)

        if not tcp_input.connect():
            logger.error("Failed to connect to TCP input source")
            return False

        logger.info("✓ TCP input connected successfully")
        logger.info(f"  Connection info: {tcp_input.get_connection_info()}")

        # Create RTCM client
        logger.info("Connecting to production RTCM server...")
        rtcm_client = RTCMClient(rtcm_config)

        if not rtcm_client.connect():
            logger.error("Failed to connect to RTCM server")
            return False

        logger.info("✓ RTCM server connected successfully")
        logger.info("✓ Authentication successful")

        # Wait a moment for heartbeat monitoring to stabilize
        time.sleep(0.5)

        logger.info("=" * 60)
        logger.info("Starting data relay...")
        logger.info("(Press Ctrl+C to stop early)")
        logger.info("=" * 60)

        # Main data relay loop
        last_progress_time = time.time()
        progress_interval = 5.0  # Progress update every 5 seconds

        while stats.elapsed_time() < duration and not shutdown_requested:
            # Read data from TCP input
            stats.input_read_attempts += 1
            data = tcp_input.read_data(timeout=2.0)

            if data:
                stats.input_read_successes += 1

                # Send to RTCM server
                stats.rtcm_send_attempts += 1
                success = rtcm_client.send_rtcm_data(data)

                if success:
                    stats.rtcm_send_successes += 1
                    stats.bytes_transferred += len(data)
                    stats.messages_sent += 1
                    logger.debug(f"Sent {len(data)} bytes to RTCM server")
                else:
                    stats.rtcm_errors += 1
                    logger.warning("Failed to send data to RTCM server")
            else:
                # No data available (timeout or no data)
                logger.debug("No data available from TCP input")

            # Check connection health
            if not tcp_input.is_connected:
                stats.input_errors += 1
                logger.error("TCP input disconnected!")
                break

            if not rtcm_client.is_connected:
                stats.rtcm_errors += 1
                logger.error("RTCM server disconnected!")
                break

            # Update heartbeat count (approximate based on elapsed time)
            stats.heartbeats_received = int(stats.elapsed_time())

            # Print progress update
            current_time = time.time()
            if current_time - last_progress_time >= progress_interval:
                stats.print_progress(logger)
                last_progress_time = current_time

        # Final progress update
        logger.info("=" * 60)
        if shutdown_requested:
            logger.info("Test stopped by user")
        else:
            logger.info("Test duration completed")

        # Print final statistics
        stats.print_final_report(logger)

        # Determine success
        success = (
            stats.rtcm_send_successes > 0
            and stats.input_errors == 0
            and stats.rtcm_errors == 0
            and stats.success_rate() > 95.0
        )

        if success:
            logger.info("=" * 60)
            logger.info("✓ TEST COMPLETED SUCCESSFULLY")
            logger.info("=" * 60)
        else:
            logger.warning("=" * 60)
            logger.warning("⚠ TEST COMPLETED WITH ISSUES")
            logger.warning("=" * 60)

        return success

    except KeyboardInterrupt:
        logger.info("\nTest interrupted by user")
        return False

    except Exception as e:
        logger.error(f"Test failed with exception: {e}", exc_info=True)
        return False

    finally:
        # Cleanup
        logger.info("Cleaning up connections...")

        if tcp_input:
            try:
                tcp_input.disconnect()
                logger.info("✓ TCP input disconnected")
            except Exception as e:
                logger.warning(f"Error disconnecting TCP input: {e}")

        if rtcm_client:
            try:
                rtcm_client.disconnect()
                logger.info("✓ RTCM client disconnected")
            except Exception as e:
                logger.warning(f"Error disconnecting RTCM client: {e}")

        logger.info("Cleanup complete")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test SP-Base-Relay with production RTCM server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default 60 second duration
  python tests/manual/test_production_rtcm.py
  
  # Run for 5 minutes
  python tests/manual/test_production_rtcm.py --duration 300
  
  # Use custom config file
  python tests/manual/test_production_rtcm.py --config my-config.yaml
        """,
    )

    parser.add_argument(
        "--config",
        type=str,
        default="config.example.yaml",
        help="Path to configuration file (default: config.example.yaml)",
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Test duration in seconds (default: 60)",
    )

    args = parser.parse_args()

    # Setup logging
    logger = setup_test_logging()

    logger.info(f"Loading configuration from: {args.config}")

    # Load configuration
    try:
        config = ConfigManager.load_config(args.config, apply_env_overrides=True)
    except Exception as e:
        logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Validate we have required configuration
    if not config.server:
        logger.error("No RTCM server configuration found in config file")
        sys.exit(1)

    if not config.input or config.input.source != "tcp":
        logger.error("TCP input source not configured in config file")
        sys.exit(1)

    # Extract configurations
    tcp_input_config = config.input.get_tcp_config()

    # Convert TCPInputConfig to TCPConfig for TCPInputSource
    tcp_config = TCPConfig(
        host=tcp_input_config.host,
        port=tcp_input_config.port,
        timeout=tcp_input_config.timeout,
        read_timeout=tcp_input_config.timeout,  # Use same timeout for reads
        buffer_size=tcp_input_config.buffer_size,
        keepalive=True,
    )

    rtcm_config = config.server

    # Run the test
    success = run_production_test(
        tcp_config=tcp_config,
        rtcm_config=rtcm_config,
        duration=args.duration,
        logger=logger,
    )

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
