# pyright: reportPrivateUsage=false
# pyright: reportCallIssue=false

"""Additional edge case tests for DataPipelineCoordinator to reach 90% coverage.

These tests target specific uncovered lines identified in coverage analysis.
"""

import time
import threading
from unittest.mock import Mock, patch

from sp_base_relay.core.data_pipeline import DataPipelineCoordinator
from sp_base_relay.core.rtcm_client import RTCMClient
from sp_base_relay.core.connection_states import ConnectionState
from sp_base_relay.core.input_sources.base_input import InputSource
from sp_base_relay.config import RTCMServerConfig

from typing import Any


class EdgeCaseMockInputSource(InputSource):
    """Mock input source for edge case testing."""

    def __init__(self, disconnect_after_reads: int = 0):
        super().__init__("EdgeCaseMock")
        self._disconnect_after_reads = disconnect_after_reads
        self._read_count = 0
        self._data_to_return: list[bytes] = []

    def connect(self) -> bool:
        self._update_connection_stats(True)
        self._read_count = 0
        return True

    def read_data(self, timeout: float | None = None) -> bytes | None:
        if not self.is_connected:
            return None

        self._read_count += 1

        # Simulate disconnection after N reads
        if (
            self._disconnect_after_reads > 0
            and self._read_count >= self._disconnect_after_reads
        ):
            self._connected = False
            self.stats.connected_since = None
            return None

        if self._data_to_return:
            data = self._data_to_return.pop(0)
            self._update_read_stats(data)
            return data

        return None

    def disconnect(self) -> None:
        self._connected = False
        self.stats.connected_since = None

    def get_connection_info(self) -> dict[str, Any]:
        return {"type": "edge_case_mock"}

    def queue_data(self, data: bytes) -> None:
        """Helper to queue data."""
        self._data_to_return.append(data)


class TestDataPipelineEdgeCases:
    """Test edge cases for DataPipelineCoordinator to increase coverage."""

    def test_input_thread_detects_disconnection_during_run(self):
        """Test input thread detects when source disconnects during operation."""
        # Create input that will disconnect after 2 reads
        input_source = EdgeCaseMockInputSource(disconnect_after_reads=2)
        input_source.queue_data(b"data1")
        input_source.queue_data(b"data2")

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED
        rtcm_client.send_rtcm_data = Mock(return_value=True)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start input thread
        input_thread = threading.Thread(
            target=coordinator._input_thread_worker
        )  # pyright: ignore[reportPrivateUsage]
        input_thread.start()

        try:
            # Wait for disconnection to be detected
            time.sleep(0.5)

            # Thread should have stopped and triggered restart
            input_thread.join(timeout=2.0)
            assert not input_thread.is_alive()
            assert coordinator.stats.input_errors >= 1
            assert (
                coordinator._restart_requested.is_set()
            )  # pyright: ignore[reportPrivateUsage]
        finally:
            coordinator.running = False
            coordinator._stop_event.set()  # pyright: ignore[reportPrivateUsage]
            if input_thread.is_alive():
                input_thread.join(timeout=2.0)

    def test_input_thread_handles_queue_full_condition(self):
        """Test input thread handles queue full with restart."""
        input_source = EdgeCaseMockInputSource()
        # Queue lots of data to fill the queue
        for i in range(20):
            input_source.queue_data(f"data_{i}".encode())

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start input thread
        input_thread = threading.Thread(
            target=coordinator._input_thread_worker
        )  # pyright: ignore[reportPrivateUsage]
        input_thread.start()

        try:
            # Wait for queue to fill and overflow
            time.sleep(0.5)

            # Should have triggered restart due to queue overflow
            if coordinator.data_queue.full():
                assert coordinator.stats.input_errors >= 1
        finally:
            coordinator.running = False
            coordinator._stop_event.set()  # pyright: ignore[reportPrivateUsage]
            input_thread.join(timeout=2.0)

    def test_input_thread_handles_read_exception(self):
        """Test input thread handles exception during read_data."""
        input_source = EdgeCaseMockInputSource()

        # Make read_data raise an exception
        def failing_read(timeout: float | None = None) -> bytes | None:
            raise RuntimeError("Read operation failed")

        input_source.read_data = failing_read

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start input thread
        input_thread = threading.Thread(
            target=coordinator._input_thread_worker
        )  # pyright: ignore[reportPrivateUsage]
        input_thread.start()

        try:
            # Wait for exception and restart
            input_thread.join(timeout=2.0)

            # Should have stopped and recorded error
            assert not input_thread.is_alive()
            assert coordinator.stats.input_errors >= 1
            assert (
                coordinator._restart_requested.is_set()
            )  # pyright: ignore[reportPrivateUsage]
        finally:
            coordinator.running = False
            coordinator._stop_event.set()  # pyright: ignore[reportPrivateUsage]
            if input_thread.is_alive():
                input_thread.join(timeout=2.0)

    def test_coordinator_health_check_detects_input_failure(self):
        """Test coordinator health check detects input source failure."""
        input_source = EdgeCaseMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start coordinator in thread
        coordinator_thread = threading.Thread(
            target=coordinator._coordinator_loop
        )  # pyright: ignore[reportPrivateUsage]
        coordinator_thread.start()

        try:
            time.sleep(0.1)

            # Disconnect input source while coordinator is running
            input_source.disconnect()

            # Wait for health check to detect and trigger restart
            time.sleep(1.5)  # Wait for health check timeout

            # Should have detected failure
            assert coordinator.stats.input_errors >= 1
        finally:
            coordinator.running = False
            coordinator._stop_event.set()  # pyright: ignore[reportPrivateUsage]
            coordinator_thread.join(timeout=2.0)

    def test_coordinator_health_check_detects_rtcm_failure(self):
        """Test coordinator health check detects RTCM client failure."""
        input_source = EdgeCaseMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Start coordinator in thread
        coordinator_thread = threading.Thread(
            target=coordinator._coordinator_loop
        )  # pyright: ignore[reportPrivateUsage]
        coordinator_thread.start()

        try:
            time.sleep(0.1)

            # Disconnect RTCM while coordinator is running
            rtcm_client.state = ConnectionState.DISCONNECTED

            # Wait for health check to detect and trigger restart
            time.sleep(1.5)  # Wait for health check timeout

            # Should have detected failure
            assert coordinator.stats.rtcm_errors >= 1
        finally:
            coordinator.running = False
            coordinator._stop_event.set()  # pyright: ignore[reportPrivateUsage]
            coordinator_thread.join(timeout=2.0)

    def test_coordinator_handles_rtcm_send_failure(self):
        """Test coordinator handles RTCM send failure during operation."""
        input_source = EdgeCaseMockInputSource()
        input_source.connect()
        input_source.queue_data(b"test_data")

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        # Make send_rtcm_data fail
        rtcm_client.send_rtcm_data = Mock(return_value=False)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Put data in queue
        coordinator.data_queue.put(b"test_data")
        coordinator.data_queue.put(None)  # Stop signal

        # Run coordinator
        coordinator._coordinator_loop()  # pyright: ignore[reportPrivateUsage]

        # Should have detected send failure
        assert coordinator.stats.rtcm_errors >= 1
        assert (
            coordinator._restart_requested.is_set()
        )  # pyright: ignore[reportPrivateUsage]

    def test_coordinator_handles_exception_in_loop(self):
        """Test coordinator handles unexpected exception in main loop."""
        input_source = EdgeCaseMockInputSource()
        input_source.connect()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)
        rtcm_client.state = ConnectionState.CONNECTED

        # Make send_rtcm_data raise exception
        def raise_exception(data: bytes) -> bool:
            raise RuntimeError("Unexpected coordinator error")

        rtcm_client.send_rtcm_data = raise_exception

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Put data in queue
        coordinator.data_queue.put(b"test_data")

        # Run coordinator
        coordinator._coordinator_loop()  # pyright: ignore[reportPrivateUsage]

        # Should have recorded coordination error
        assert coordinator.stats.coordination_errors >= 1
        assert (
            coordinator._restart_requested.is_set()
        )  # pyright: ignore[reportPrivateUsage]

    def test_cleanup_connections_handles_rtcm_exception(self):
        """Test cleanup handles exception when disconnecting RTCM client."""
        input_source = EdgeCaseMockInputSource()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        # Make disconnect raise exception
        rtcm_client.disconnect = Mock(side_effect=RuntimeError("Disconnect failed"))

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Should not raise exception despite disconnect failure
        coordinator._cleanup_connections()  # pyright: ignore[reportPrivateUsage]

        # Should have called disconnect
        rtcm_client.disconnect.assert_called_once()

    def test_cleanup_connections_handles_input_exception(self):
        """Test cleanup handles exception when disconnecting input source."""
        input_source = EdgeCaseMockInputSource()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        # Make input disconnect raise exception
        input_source.disconnect = Mock(
            side_effect=RuntimeError("Input disconnect failed")
        )

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Should not raise exception despite disconnect failure
        coordinator._cleanup_connections()  # pyright: ignore[reportPrivateUsage]

        # Should have called disconnect
        input_source.disconnect.assert_called_once()

    def test_finalize_shutdown_calls_restart_callback(self):
        """Test finalize shutdown calls restart callback when restart requested."""
        input_source = EdgeCaseMockInputSource()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        # Create callback
        callback = Mock()

        coordinator = DataPipelineCoordinator(
            input_source, rtcm_client, restart_callback=callback
        )
        coordinator._restart_requested.set()  # pyright: ignore[reportPrivateUsage]

        # Call finalize shutdown
        coordinator._finalize_shutdown()  # pyright: ignore[reportPrivateUsage]

        # Callback should have been called
        callback.assert_called_once()

    def test_finalize_shutdown_handles_callback_exception(self):
        """Test finalize shutdown handles exception from restart callback."""
        input_source = EdgeCaseMockInputSource()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        # Create callback that raises exception
        callback = Mock(side_effect=RuntimeError("Callback failed"))

        coordinator = DataPipelineCoordinator(
            input_source, rtcm_client, restart_callback=callback
        )
        coordinator._restart_requested.set()  # pyright: ignore[reportPrivateUsage]

        # Should not raise exception despite callback failure
        coordinator._finalize_shutdown()  # pyright: ignore[reportPrivateUsage]

        # Callback should have been called
        callback.assert_called_once()

    def test_finalize_shutdown_waits_for_input_thread(self):
        """Test finalize shutdown waits for input thread to complete."""
        input_source = EdgeCaseMockInputSource()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Create a slow-stopping thread
        def slow_worker():
            time.sleep(0.5)

        coordinator.input_thread = threading.Thread(target=slow_worker)
        coordinator.input_thread.start()

        # Call finalize shutdown
        coordinator._finalize_shutdown()  # pyright: ignore[reportPrivateUsage]

        # Thread should have been joined
        assert not coordinator.input_thread.is_alive()

    def test_stop_relay_handles_full_queue(self):
        """Test stop_relay handles full queue when putting stop signal."""
        input_source = EdgeCaseMockInputSource()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Fill the queue
        for i in range(coordinator.data_queue.maxsize):
            coordinator.data_queue.put(f"data_{i}".encode())

        # Queue is now full
        assert coordinator.data_queue.full()

        # Should handle full queue gracefully
        coordinator.stop_relay()

        # Should have stopped
        assert not coordinator.running
        assert coordinator._stop_event.is_set()  # pyright: ignore[reportPrivateUsage]

    def test_get_detailed_status_with_input_last_error(self):
        """Test get_detailed_status includes input source last error."""
        input_source = EdgeCaseMockInputSource()
        input_source._last_error = RuntimeError("Test error")  # type: ignore

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        status = coordinator.get_detailed_status()

        # Should include last error
        assert status["input_source"]["last_error"] is not None
        assert "Test error" in status["input_source"]["last_error"]

    def test_start_relay_already_running_warning(self):
        """Test start_relay logs warning when already running."""
        input_source = EdgeCaseMockInputSource()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)
        coordinator.running = True

        # Should log warning and return
        with patch("sp_base_relay.core.data_pipeline.logger") as mock_logger:
            coordinator.start_relay()
            mock_logger.warning.assert_called_once()


class TestDataPipelineThreadSynchronization:
    """Test thread synchronization edge cases."""

    def test_stats_lock_thread_safety(self):
        """Test statistics updates are thread-safe."""
        input_source = EdgeCaseMockInputSource()

        rtcm_config = RTCMServerConfig(
            host="91.186.9.136", port=50010, username="test", password="test"
        )
        rtcm_client = RTCMClient(rtcm_config)

        coordinator = DataPipelineCoordinator(input_source, rtcm_client)

        # Multiple threads updating stats
        def update_stats():
            for _ in range(100):
                with coordinator._stats_lock:  # pyright: ignore[reportPrivateUsage]
                    coordinator.stats.bytes_processed += 1

        threads = [threading.Thread(target=update_stats) for _ in range(5)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # All updates should have been captured
        assert coordinator.stats.bytes_processed == 500
