# pyright: reportPrivateUsage=false
"""Example of integrating Prometheus metrics with SP-Base-Relay service.

This example demonstrates how to:
1. Initialize the metrics collector
2. Start the metrics HTTP server
3. Integrate metrics collection into the main service loop
4. Handle graceful shutdown
"""

import time
import logging
import signal
import sys
from pathlib import Path
from typing import Any

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sp_base_relay.config import ConfigManager
from sp_base_relay.logger import setup_logging
from sp_base_relay.metrics import MetricsCollector
from sp_base_relay.core.rtcm_client import RTCMClient
from sp_base_relay.core.input_sources.input_factory import InputSourceFactory
from sp_base_relay.core.data_pipeline import DataPipelineCoordinator


logger = logging.getLogger(__name__)
running = True


def signal_handler(signum: int, frame: Any) -> None:
    """Handle shutdown signals gracefully."""
    global running
    logger.info(f"Received signal {signum}, initiating shutdown")
    running = False


def main() -> None:
    """Main service loop with metrics integration."""
    global running
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Load configuration
    config_path = Path("config.yaml")
    config = ConfigManager.load_config(str(config_path))
    
    # Set up logging
    setup_logging(config.logging)
    logger.info("SP-Base-Relay service starting with metrics enabled")
    
    # Initialize metrics collector
    metrics = MetricsCollector(namespace="sp_base_relay")
    
    # Start metrics HTTP server if enabled
    if config.metrics.enabled:
        try:
            metrics.start_metrics_server(
                port=config.metrics.port,
                host=config.metrics.host
            )
            logger.info(f"Metrics available at http://{config.metrics.host}:{config.metrics.port}{config.metrics.path}")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
            logger.warning("Continuing without metrics")
    
    # Initialize RTCM client
    rtcm_client = RTCMClient(config.server)
    
    # Create input source
    if config.input.source == "tcp":
        input_config = {
            "host": config.input.get_tcp_config().host,
            "port": config.input.get_tcp_config().port,
            "timeout": config.input.get_tcp_config().timeout,
        }
    elif config.input.source in ("serial", "usb_serial"):
        serial_cfg = config.input.get_serial_config()
        input_config = {
            "port": serial_cfg.port,
            "baudrate": serial_cfg.baudrate,
            "timeout": serial_cfg.timeout,
            "bytesize": serial_cfg.bytesize,
            "parity": serial_cfg.parity,
            "stopbits": serial_cfg.stopbits,
        }
    else:
        raise ValueError(f"Unsupported input source: {config.input.source}")
    
    source_type = "serial" if config.input.source in ("serial", "usb_serial") else config.input.source
    input_source = InputSourceFactory.create_input_source(source_type, input_config)
    
    # Create data pipeline coordinator
    coordinator = DataPipelineCoordinator(input_source, rtcm_client)
    
    # Track previous stats for delta calculations
    prev_stats = (None, None, None)
    
    try:
        # Start the relay in a separate thread (non-blocking for metrics updates)
        import threading
        relay_thread = threading.Thread(
            target=coordinator.start_relay,
            name="RelayMain",
            daemon=False
        )
        relay_thread.start()
        
        logger.info("Data pipeline relay started")
        
        # Main metrics collection loop
        while running and relay_thread.is_alive():
            # Collect and update all metrics
            prev_stats = metrics.collect_all_metrics(
                rtcm_client,
                coordinator,
                input_source,
                *prev_stats
            )
            
            # Log current status periodically
            if config.metrics.enabled:
                logger.debug(
                    f"Metrics: RTCM={'connected' if rtcm_client.is_connected else 'disconnected'}, "
                    f"Input={'connected' if input_source.is_connected else 'disconnected'}, "
                    f"Pipeline={'running' if coordinator.is_running else 'stopped'}"
                )
            
            # Sleep before next update (5 second interval)
            time.sleep(5)
        
        # If loop exited due to relay thread stopping
        if not relay_thread.is_alive():
            logger.warning("Relay thread stopped unexpectedly")
        
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Service error: {e}", exc_info=True)
    finally:
        # Graceful shutdown
        logger.info("Shutting down service")
        
        # Stop relay
        coordinator.stop_relay()
        
        # Final metrics update
        if config.metrics.enabled:
            metrics.collect_all_metrics(
                rtcm_client,
                coordinator,
                input_source,
                *prev_stats
            )
        
        # Stop metrics server
        if config.metrics.enabled:
            metrics.stop_metrics_server()
        
        logger.info("Service shutdown complete")


if __name__ == "__main__":
    main()
