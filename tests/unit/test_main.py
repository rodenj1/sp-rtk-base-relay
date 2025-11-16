# pyright: reportPrivateUsage=false
"""Comprehensive unit tests for main.py - CLI and service orchestration."""

import argparse
import signal
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from sp_base_relay.config import Config, LoggingConfig, MetricsConfig
from sp_base_relay.exceptions import (
    ConfigurationError,
    ServiceError,
)
from sp_base_relay.main import (
    SPBaseRelayService,
    create_parser,
    main,
    setup_signal_handlers,
)


# Fixtures


@pytest.fixture
def mock_config() -> Mock:
    """Create a mock configuration object."""
    config = Mock(spec=Config)

    # Logging config
    logging_config = Mock(spec=LoggingConfig)
    logging_config.level = "INFO"
    config.logging = logging_config

    # Metrics config
    metrics_config = Mock(spec=MetricsConfig)
    metrics_config.enabled = True
    metrics_config.host = "0.0.0.0"
    metrics_config.port = 8080
    config.metrics = metrics_config

    # Input config
    input_config = Mock()
    input_config.source = "tcp"
    tcp_config = Mock()
    tcp_config.host = "localhost"
    tcp_config.port = 5015
    tcp_config.timeout = 30
    input_config.get_tcp_config.return_value = tcp_config
    config.input = input_config

    # Server config
    server_config = Mock()
    server_config.host = "rtcm.example.com"
    server_config.port = 50010
    config.server = server_config

    return config


@pytest.fixture
def mock_input_source() -> Mock:
    """Create a mock input source."""
    source = Mock()
    source.is_connected = True
    source.connection_statistics = {
        "connected": True,
        "bytes_read": 1000,
        "errors": 0,
    }
    return source


@pytest.fixture
def mock_rtcm_client() -> Mock:
    """Create a mock RTCM client."""
    client = Mock()
    client.is_connected = True
    client.connection_statistics = {
        "connected": True,
        "bytes_sent": 1000,
        "messages_sent": 10,
    }
    return client


@pytest.fixture
def mock_pipeline() -> Mock:
    """Create a mock data pipeline."""
    pipeline = Mock()
    pipeline.is_healthy = True
    pipeline.is_running = True
    pipeline.pipeline_statistics = {
        "messages_processed": 10,
        "bytes_processed": 1000,
        "errors": 0,
    }
    return pipeline


@pytest.fixture
def mock_metrics() -> Mock:
    """Create a mock metrics collector."""
    metrics = Mock()
    return metrics


# SPBaseRelayService Tests


class TestSPBaseRelayServiceInitialization:
    """Tests for SPBaseRelayService initialization."""

    def test_service_initialization(self, mock_config: Mock):
        """Test service initializes correctly."""
        service = SPBaseRelayService(mock_config)

        assert service.config == mock_config
        assert not service._running
        assert not service._shutdown_requested
        assert service.metrics is None
        assert service.input_source is None
        assert service.rtcm_client is None
        assert service.pipeline is None

    def test_service_has_logger(self, mock_config: Mock):
        """Test service has logger attribute."""
        service = SPBaseRelayService(mock_config)
        assert hasattr(service, "logger")

    def test_service_stores_config(self, mock_config: Mock):
        """Test service stores configuration."""
        service = SPBaseRelayService(mock_config)
        assert service.config is mock_config


class TestSPBaseRelayServiceStartup:
    """Tests for service startup process."""

    @patch("sp_base_relay.main.MetricsCollector")
    @patch("sp_base_relay.main.InputSourceFactory")
    @patch("sp_base_relay.main.RTCMClient")
    @patch("sp_base_relay.main.DataPipelineCoordinator")
    def test_service_start_success(
        self,
        mock_pipeline_class: Mock,
        mock_client_class: Mock,
        mock_factory: Mock,
        mock_metrics_class: Mock,
        mock_config: Mock,
        mock_input_source: Mock,
        mock_rtcm_client: Mock,
        mock_pipeline: Mock,
    ):
        """Test successful service startup."""
        # Setup mocks
        mock_metrics_class.return_value = Mock()
        mock_factory.create_input_source.return_value = mock_input_source
        mock_client_class.return_value = mock_rtcm_client
        mock_pipeline_class.return_value = mock_pipeline

        service = SPBaseRelayService(mock_config)
        service.start()

        assert service._running
        assert service.metrics is not None
        assert service.input_source is not None
        assert service.rtcm_client is not None
        assert service.pipeline is not None

    @patch("sp_base_relay.main.MetricsCollector")
    def test_service_start_with_metrics_enabled(
        self,
        mock_metrics_class: Mock,
        mock_config: Mock,
    ):
        """Test service starts metrics server when enabled."""
        mock_metrics = Mock()
        mock_metrics_class.return_value = mock_metrics
        mock_config.metrics.enabled = True

        service = SPBaseRelayService(mock_config)

        with (
            patch.object(service, "_create_input_source"),
            patch.object(service, "_create_rtcm_client"),
            patch.object(service, "_start_pipeline"),
        ):
            service.start()

        mock_metrics.start_metrics_server.assert_called_once_with(
            port=mock_config.metrics.port, host=mock_config.metrics.host
        )

    @patch("sp_base_relay.main.MetricsCollector")
    def test_service_start_without_metrics(
        self,
        mock_metrics_class: Mock,
        mock_config: Mock,
    ):
        """Test service skips metrics when disabled."""
        mock_config.metrics.enabled = False

        service = SPBaseRelayService(mock_config)

        with (
            patch.object(service, "_create_input_source"),
            patch.object(service, "_create_rtcm_client"),
            patch.object(service, "_start_pipeline"),
        ):
            service.start()

        assert service.metrics is None
        mock_metrics_class.assert_not_called()

    def test_service_start_when_already_running(self, mock_config: Mock):
        """Test starting service when already running raises error."""
        service = SPBaseRelayService(mock_config)
        service._running = True

        with pytest.raises(ServiceError, match="already running"):
            service.start()

    def test_service_start_failure_triggers_cleanup(self, mock_config: Mock):
        """Test service cleanup on startup failure."""
        service = SPBaseRelayService(mock_config)

        with (
            patch.object(service, "_start_metrics_server"),
            patch.object(
                service, "_create_input_source", side_effect=Exception("Test error")
            ),
            patch.object(service, "_cleanup") as mock_cleanup,
        ):

            with pytest.raises(ServiceError):
                service.start()

            mock_cleanup.assert_called_once()
            assert not service._running


class TestSPBaseRelayServiceShutdown:
    """Tests for service shutdown process."""

    def test_service_stop_success(
        self,
        mock_config: Mock,
        mock_input_source: Mock,
        mock_rtcm_client: Mock,
        mock_pipeline: Mock,
        mock_metrics: Mock,
    ):
        """Test successful service shutdown."""
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.input_source = mock_input_source
        service.rtcm_client = mock_rtcm_client
        service.pipeline = mock_pipeline
        service.metrics = mock_metrics

        service.stop()

        assert not service._running
        assert service._shutdown_requested
        mock_pipeline.stop_relay.assert_called_once()
        mock_input_source.disconnect.assert_called_once()
        mock_rtcm_client.disconnect.assert_called_once()
        mock_metrics.stop_metrics_server.assert_called_once()

    def test_service_stop_when_not_running(self, mock_config: Mock):
        """Test stopping service when not running logs warning."""
        service = SPBaseRelayService(mock_config)
        service._running = False

        # Should not raise error, just log warning
        service.stop()

        assert not service._running

    def test_service_stop_with_partial_components(
        self, mock_config: Mock, mock_pipeline: Mock
    ):
        """Test stopping service with only some components initialized."""
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.pipeline = mock_pipeline
        service.input_source = None
        service.rtcm_client = None
        service.metrics = None

        service.stop()

        assert not service._running
        mock_pipeline.stop_relay.assert_called_once()

    def test_service_stop_handles_errors(self, mock_config: Mock, mock_pipeline: Mock):
        """Test service stop handles component errors."""
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.pipeline = mock_pipeline
        mock_pipeline.stop_relay.side_effect = Exception("Stop error")

        with pytest.raises(ServiceError):
            service.stop()


class TestSPBaseRelayServiceRun:
    """Tests for service run loop."""

    @patch("sp_base_relay.main.time.sleep")
    def test_service_run_until_shutdown(
        self, mock_sleep: Mock, mock_config: Mock, mock_pipeline: Mock
    ) -> None:
        """Test service runs until shutdown requested."""
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.pipeline = mock_pipeline
        service.metrics = None

        # Simulate shutdown after 2 iterations
        call_count = [0]

        def sleep_side_effect(seconds: float) -> None:
            call_count[0] += 1
            if call_count[0] >= 2:
                service._shutdown_requested = True

        mock_sleep.side_effect = sleep_side_effect

        with patch.object(service, "stop"):
            exit_code = service.run()

        assert exit_code == 0
        assert mock_sleep.call_count >= 2

    def test_service_run_not_started_raises_error(self, mock_config: Mock):
        """Test running service when not started raises error."""
        service = SPBaseRelayService(mock_config)
        service._running = False

        with pytest.raises(ServiceError, match="must be started"):
            service.run()

    @patch("sp_base_relay.main.time.sleep")
    def test_service_run_handles_keyboard_interrupt(
        self, mock_sleep: Mock, mock_config: Mock, mock_pipeline: Mock
    ):
        """Test service handles KeyboardInterrupt gracefully."""
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.pipeline = mock_pipeline
        service.metrics = None

        mock_sleep.side_effect = KeyboardInterrupt()

        with patch.object(service, "stop"):
            exit_code = service.run()

        assert exit_code == 0

    @patch("sp_base_relay.main.time.sleep")
    def test_service_run_handles_exceptions(
        self, mock_sleep: Mock, mock_config: Mock, mock_pipeline: Mock
    ):
        """Test service handles unexpected exceptions."""
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.pipeline = mock_pipeline
        service.metrics = None

        mock_sleep.side_effect = RuntimeError("Unexpected error")

        with patch.object(service, "stop"):
            exit_code = service.run()

        assert exit_code == 1

    @patch("sp_base_relay.main.time.sleep")
    def test_service_run_updates_metrics(
        self,
        mock_sleep: Mock,
        mock_config: Mock,
        mock_pipeline: Mock,
        mock_metrics: Mock,
    ) -> None:
        """Test service updates metrics during run loop."""
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.pipeline = mock_pipeline
        service.metrics = mock_metrics

        # Run for one iteration
        def sleep_side_effect(seconds: float) -> None:
            service._shutdown_requested = True

        mock_sleep.side_effect = sleep_side_effect

        with (
            patch.object(service, "_update_metrics") as mock_update,
            patch.object(service, "stop"),
        ):
            service.run()

        mock_update.assert_called()


class TestSPBaseRelayServiceComponents:
    """Tests for service component creation."""

    @patch("sp_base_relay.main.InputSourceFactory")
    def test_create_tcp_input_source(
        self, mock_factory: Mock, mock_config: Mock, mock_input_source: Mock
    ):
        """Test creating TCP input source."""
        mock_factory.create_input_source.return_value = mock_input_source
        mock_config.input.source = "tcp"

        service = SPBaseRelayService(mock_config)
        service._create_input_source()

        assert service.input_source is mock_input_source
        mock_factory.create_input_source.assert_called_once()
        args = mock_factory.create_input_source.call_args
        assert args[0][0] == "tcp"

    @patch("sp_base_relay.main.InputSourceFactory")
    def test_create_serial_input_source(
        self, mock_factory: Mock, mock_config: Mock, mock_input_source: Mock
    ):
        """Test creating serial input source."""
        mock_factory.create_input_source.return_value = mock_input_source
        mock_config.input.source = "serial"

        # Setup serial config
        serial_config = Mock()
        serial_config.port = "/dev/ttyUSB0"
        serial_config.baudrate = 115200
        serial_config.timeout = 1.0
        serial_config.bytesize = 8
        serial_config.parity = "N"
        serial_config.stopbits = 1
        mock_config.input.get_serial_config.return_value = serial_config

        service = SPBaseRelayService(mock_config)
        service._create_input_source()

        assert service.input_source is mock_input_source
        mock_factory.create_input_source.assert_called_once()
        args = mock_factory.create_input_source.call_args
        assert args[0][0] == "serial"

    @patch("sp_base_relay.main.InputSourceFactory")
    def test_create_usb_serial_input_source(
        self, mock_factory: Mock, mock_config: Mock, mock_input_source: Mock
    ):
        """Test creating USB serial input source."""
        mock_factory.create_input_source.return_value = mock_input_source
        mock_config.input.source = "usb_serial"

        # Setup serial config
        serial_config = Mock()
        serial_config.port = "/dev/ttyUSB0"
        serial_config.baudrate = 115200
        serial_config.timeout = 1.0
        serial_config.bytesize = 8
        serial_config.parity = "N"
        serial_config.stopbits = 1
        mock_config.input.get_serial_config.return_value = serial_config

        service = SPBaseRelayService(mock_config)
        service._create_input_source()

        assert service.input_source is mock_input_source
        # Should use 'serial' as the type for both serial and usb_serial
        args = mock_factory.create_input_source.call_args
        assert args[0][0] == "serial"

    def test_create_input_source_unsupported_type(self, mock_config: Mock):
        """Test creating input source with unsupported type raises error."""
        mock_config.input.source = "invalid"

        service = SPBaseRelayService(mock_config)

        with pytest.raises(ConfigurationError, match="Unsupported input source"):
            service._create_input_source()

    @patch("sp_base_relay.main.RTCMClient")
    def test_create_rtcm_client(
        self, mock_client_class: Mock, mock_config: Mock, mock_rtcm_client: Mock
    ):
        """Test creating RTCM client."""
        mock_client_class.return_value = mock_rtcm_client

        service = SPBaseRelayService(mock_config)
        service._create_rtcm_client()

        assert service.rtcm_client is mock_rtcm_client
        mock_client_class.assert_called_once_with(mock_config.server)

    @patch("sp_base_relay.main.DataPipelineCoordinator")
    def test_start_pipeline(
        self,
        mock_pipeline_class: Mock,
        mock_config: Mock,
        mock_input_source: Mock,
        mock_rtcm_client: Mock,
        mock_pipeline: Mock,
    ):
        """Test starting data pipeline."""
        mock_pipeline_class.return_value = mock_pipeline

        service = SPBaseRelayService(mock_config)
        service.input_source = mock_input_source
        service.rtcm_client = mock_rtcm_client
        service._start_pipeline()

        assert service.pipeline is mock_pipeline
        mock_pipeline_class.assert_called_once_with(
            input_source=mock_input_source,
            rtcm_client=mock_rtcm_client,
            metrics_collector=None,
        )
        mock_pipeline.start_relay.assert_called_once()

    def test_start_pipeline_without_components_raises_error(self, mock_config: Mock):
        """Test starting pipeline without components raises error."""
        service = SPBaseRelayService(mock_config)
        service.input_source = None
        service.rtcm_client = None

        with pytest.raises(ServiceError, match="must be created first"):
            service._start_pipeline()


class TestSPBaseRelayServiceHealth:
    """Tests for service health monitoring."""

    def test_check_health_when_healthy(self, mock_config: Mock, mock_pipeline: Mock):
        """Test health check returns True when healthy."""
        service = SPBaseRelayService(mock_config)
        service.pipeline = mock_pipeline
        mock_pipeline.is_healthy = True

        assert service._check_health()

    def test_check_health_when_unhealthy(self, mock_config: Mock, mock_pipeline: Mock):
        """Test health check returns False when unhealthy."""
        service = SPBaseRelayService(mock_config)
        service.pipeline = mock_pipeline
        mock_pipeline.is_healthy = False

        assert not service._check_health()

    def test_check_health_without_pipeline(self, mock_config: Mock):
        """Test health check returns False without pipeline."""
        service = SPBaseRelayService(mock_config)
        service.pipeline = None

        assert not service._check_health()


class TestSPBaseRelayServiceMetrics:
    """Tests for service metrics updates."""

    def test_update_metrics_with_all_components(
        self,
        mock_config: Mock,
        mock_pipeline: Mock,
        mock_input_source: Mock,
        mock_rtcm_client: Mock,
        mock_metrics: Mock,
    ):
        """Test updating metrics with all components."""
        service = SPBaseRelayService(mock_config)
        service.pipeline = mock_pipeline
        service.input_source = mock_input_source
        service.rtcm_client = mock_rtcm_client
        service.metrics = mock_metrics

        service._update_metrics()

        mock_metrics.update_from_pipeline_stats.assert_called_once()
        mock_metrics.update_from_input_stats.assert_called_once()
        mock_metrics.update_from_rtcm_stats.assert_called_once()
        mock_metrics.update_connection_status.assert_called_once()
        mock_metrics.update_pipeline_status.assert_called_once()
        mock_metrics.update_service_uptime.assert_called_once()

    def test_update_metrics_without_metrics_collector(
        self, mock_config: Mock, mock_pipeline: Mock
    ):
        """Test updating metrics without metrics collector does nothing."""
        service = SPBaseRelayService(mock_config)
        service.pipeline = mock_pipeline
        service.metrics = None

        # Should not raise error
        service._update_metrics()

    def test_update_metrics_handles_errors(
        self, mock_config: Mock, mock_pipeline: Mock, mock_metrics: Mock
    ):
        """Test updating metrics handles component errors gracefully."""
        service = SPBaseRelayService(mock_config)
        service.pipeline = mock_pipeline
        service.metrics = mock_metrics
        mock_metrics.update_from_pipeline_stats.side_effect = Exception("Metrics error")

        # Should not raise error, just log warning
        service._update_metrics()


class TestSPBaseRelayServiceCleanup:
    """Tests for service cleanup."""

    def test_cleanup_all_components(
        self,
        mock_config: Mock,
        mock_pipeline: Mock,
        mock_input_source: Mock,
        mock_rtcm_client: Mock,
        mock_metrics: Mock,
    ):
        """Test cleanup stops all components."""
        service = SPBaseRelayService(mock_config)
        service.pipeline = mock_pipeline
        service.input_source = mock_input_source
        service.rtcm_client = mock_rtcm_client
        service.metrics = mock_metrics

        service._cleanup()

        mock_pipeline.stop_relay.assert_called_once()
        mock_input_source.disconnect.assert_called_once()
        mock_rtcm_client.disconnect.assert_called_once()
        mock_metrics.stop_metrics_server.assert_called_once()

    def test_cleanup_handles_component_errors(
        self, mock_config: Mock, mock_pipeline: Mock
    ):
        """Test cleanup handles component errors gracefully."""
        service = SPBaseRelayService(mock_config)
        service.pipeline = mock_pipeline
        mock_pipeline.stop_relay.side_effect = Exception("Cleanup error")

        # Should not raise error, just log
        service._cleanup()


# CLI Parser Tests


class TestCLIParser:
    """Tests for CLI argument parser."""

    def test_parser_creation(self):
        """Test parser is created successfully."""
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parse_default_config_path(self):
        """Test parser uses default config path."""
        parser = create_parser()
        args = parser.parse_args([])
        assert args.config == Path("/etc/sp-base-relay/config.yaml")

    def test_parse_custom_config_path(self):
        """Test parser accepts custom config path."""
        parser = create_parser()
        args = parser.parse_args(["--config", "/custom/path/config.yaml"])
        assert args.config == Path("/custom/path/config.yaml")

    def test_parse_config_short_flag(self):
        """Test parser accepts short config flag."""
        parser = create_parser()
        args = parser.parse_args(["-c", "/custom/config.yaml"])
        assert args.config == Path("/custom/config.yaml")

    def test_parse_validate_flag(self):
        """Test parser accepts validate flag."""
        parser = create_parser()
        args = parser.parse_args(["--validate"])
        assert args.validate is True

    def test_parse_generate_config_flag(self):
        """Test parser accepts generate-config flag."""
        parser = create_parser()
        args = parser.parse_args(["--generate-config"])
        assert args.generate_config is True

    def test_parse_foreground_flag(self):
        """Test parser accepts foreground flag."""
        parser = create_parser()
        args = parser.parse_args(["--foreground"])
        assert args.foreground is True

    def test_parse_log_level(self):
        """Test parser accepts log level."""
        parser = create_parser()
        args = parser.parse_args(["--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_parse_multiple_flags(self):
        """Test parser accepts multiple flags."""
        parser = create_parser()
        args = parser.parse_args(
            ["--config", "/custom/config.yaml", "--foreground", "--log-level", "DEBUG"]
        )
        assert args.config == Path("/custom/config.yaml")
        assert args.foreground is True
        assert args.log_level == "DEBUG"


# Signal Handler Tests


class TestSignalHandlers:
    """Tests for signal handler setup."""

    def test_setup_signal_handlers(self, mock_config: Mock):
        """Test signal handlers are registered."""
        service = SPBaseRelayService(mock_config)

        with patch("signal.signal") as mock_signal:
            setup_signal_handlers(service)

            # Verify SIGTERM and SIGINT are registered
            calls = mock_signal.call_args_list
            assert len(calls) == 2
            assert calls[0][0][0] == signal.SIGTERM
            assert calls[1][0][0] == signal.SIGINT

    @patch("sp_base_relay.main.sys.exit")
    def test_signal_handler_stops_service(self, mock_exit: Mock, mock_config: Mock):
        """Test signal handler stops service."""
        service = SPBaseRelayService(mock_config)
        service._running = True

        with patch("signal.signal") as mock_signal:
            setup_signal_handlers(service)

            # Get the signal handler function
            handler = mock_signal.call_args_list[0][0][1]

            with patch.object(service, "stop") as mock_stop:
                # Call the handler (simulating SIGTERM)
                handler(signal.SIGTERM, None)

                mock_stop.assert_called_once()
                mock_exit.assert_called_once_with(0)


# Main Function Tests


class TestMainFunction:
    """Tests for main function."""

    @patch("sp_base_relay.main.ConfigManager.generate_default_config")
    def test_main_generate_config_mode(
        self, mock_generate_config: Mock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main function in generate-config mode."""
        mock_generate_config.return_value = "# Config"

        with patch("sys.argv", ["sp-base-relay", "--generate-config"]):
            exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "# Config" in captured.out

    @patch("sp_base_relay.main.ConfigManager")
    @patch("sp_base_relay.main.LoggerManager")
    def test_main_validate_mode(
        self,
        mock_logger_manager: Mock,
        mock_config_manager_class: Mock,
        mock_config: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main function in validate mode."""
        mock_config_manager = Mock()
        mock_config_manager.load_config.return_value = mock_config
        mock_config_manager_class.return_value = mock_config_manager

        with patch("sys.argv", ["sp-base-relay", "--validate"]):
            exit_code = main()

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "valid" in captured.out.lower()

    @patch("sp_base_relay.main.ConfigManager")
    def test_main_config_load_error(
        self, mock_config_manager_class: Mock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test main function handles config load error."""
        mock_config_manager = Mock()
        mock_config_manager.load_config.side_effect = ConfigurationError(
            "Invalid config"
        )
        mock_config_manager_class.return_value = mock_config_manager

        with patch("sys.argv", ["sp-base-relay"]):
            exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error loading configuration" in captured.err

    @patch("sp_base_relay.main.ConfigManager")
    @patch("sp_base_relay.main.LoggerManager")
    def test_main_logger_setup_error(
        self,
        mock_logger_manager: Mock,
        mock_config_manager_class: Mock,
        mock_config: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Test main function handles logger setup error."""
        mock_config_manager = Mock()
        mock_config_manager.load_config.return_value = mock_config
        mock_config_manager_class.return_value = mock_config_manager

        mock_logger_manager.setup_logging.side_effect = Exception("Logger error")

        with patch("sys.argv", ["sp-base-relay"]):
            exit_code = main()

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error setting up logging" in captured.err

    @patch("sp_base_relay.main.ConfigManager")
    @patch("sp_base_relay.main.LoggerManager")
    @patch("sp_base_relay.main.SPBaseRelayService")
    @patch("sp_base_relay.main.setup_signal_handlers")
    def test_main_successful_run(
        self,
        mock_setup_signals: Mock,
        mock_service_class: Mock,
        mock_logger_manager: Mock,
        mock_config_manager_class: Mock,
        mock_config: Mock,
    ):
        """Test main function successful run."""
        mock_config_manager = Mock()
        mock_config_manager.load_config.return_value = mock_config
        mock_config_manager_class.return_value = mock_config_manager

        mock_service = Mock()
        mock_service.run.return_value = 0
        mock_service_class.return_value = mock_service

        with patch("sys.argv", ["sp-base-relay"]):
            exit_code = main()

        assert exit_code == 0
        mock_service.start.assert_called_once()
        mock_service.run.assert_called_once()
        mock_logger_manager.shutdown_logging.assert_called_once()

    @patch("sp_base_relay.main.ConfigManager")
    @patch("sp_base_relay.main.LoggerManager")
    @patch("sp_base_relay.main.SPBaseRelayService")
    def test_main_service_error(
        self,
        mock_service_class: Mock,
        mock_logger_manager: Mock,
        mock_config_manager_class: Mock,
        mock_config: Mock,
    ):
        """Test main function handles service error."""
        mock_config_manager = Mock()
        mock_config_manager.load_config.return_value = mock_config
        mock_config_manager_class.return_value = mock_config_manager

        mock_service = Mock()
        mock_service.start.side_effect = ServiceError("Service error")
        mock_service_class.return_value = mock_service

        with patch("sys.argv", ["sp-base-relay"]):
            exit_code = main()

        assert exit_code == 1

    @patch("sp_base_relay.main.ConfigManager")
    @patch("sp_base_relay.main.LoggerManager")
    @patch("sp_base_relay.main.SPBaseRelayService")
    def test_main_keyboard_interrupt(
        self,
        mock_service_class: Mock,
        mock_logger_manager: Mock,
        mock_config_manager_class: Mock,
        mock_config: Mock,
    ):
        """Test main function handles KeyboardInterrupt."""
        mock_config_manager = Mock()
        mock_config_manager.load_config.return_value = mock_config
        mock_config_manager_class.return_value = mock_config_manager

        mock_service = Mock()
        mock_service.start.side_effect = KeyboardInterrupt()
        mock_service_class.return_value = mock_service

        with patch("sys.argv", ["sp-base-relay"]):
            exit_code = main()

        assert exit_code == 0

    @patch("sp_base_relay.main.ConfigManager")
    @patch("sp_base_relay.main.LoggerManager")
    def test_main_log_level_override(
        self,
        mock_logger_manager: Mock,
        mock_config_manager_class: Mock,
        mock_config: Mock,
    ):
        """Test main function overrides log level from CLI."""
        mock_config_manager = Mock()
        mock_config_manager.load_config.return_value = mock_config
        mock_config_manager_class.return_value = mock_config_manager

        with (
            patch("sys.argv", ["sp-base-relay", "--log-level", "DEBUG"]),
            patch("sp_base_relay.main.SPBaseRelayService"),
            patch("sp_base_relay.main.setup_signal_handlers"),
        ):
            try:
                main()
            except:
                pass  # Service will fail without full mocking, but that's OK

        # Verify log level was overridden
        assert mock_config.logging.level == "DEBUG"
