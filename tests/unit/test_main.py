# pyright: reportPrivateUsage=false
"""Unit tests for main.py v2 — BroadcastHub + DestinationFactory orchestration."""

import argparse
import signal
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from sp_rtk_base_relay.config import Config, LoggingConfig, MetricsConfig
from sp_rtk_base_relay.exceptions import (
    ConfigurationError,
    ServiceError,
)
from sp_rtk_base_relay.main import (
    SPBaseRelayService,
    create_parser,
    main,
    setup_signal_handlers,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config() -> Mock:
    """Create a mock v2 configuration object."""
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

    # Destinations list (v2)
    config.destinations = [Mock()]

    return config


@pytest.fixture
def mock_input_source() -> Mock:
    """Create a mock input source."""
    source = Mock()
    source.is_connected = True
    return source


@pytest.fixture
def mock_hub() -> Mock:
    """Create a mock BroadcastHub."""
    hub = Mock()
    hub.is_running = True
    return hub


@pytest.fixture
def mock_destination() -> Mock:
    """Create a mock BaseDestination."""
    dest = Mock()
    dest.name = "sp1"
    dest.destination_type = "surepath"
    dest.is_connected = True
    return dest


@pytest.fixture
def mock_metrics() -> Mock:
    """Create a mock MetricsCollector."""
    return Mock()


# ---------------------------------------------------------------------------
# SPBaseRelayService — Initialization
# ---------------------------------------------------------------------------


class TestServiceInit:
    """Tests for SPBaseRelayService initialization."""

    def test_service_initialization(self, mock_config: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        assert service.config == mock_config
        assert not service._running
        assert not service._shutdown_requested
        assert service.metrics is None
        assert service.input_source is None
        assert service.destinations == []
        assert service.hub is None

    def test_service_has_logger(self, mock_config: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        assert hasattr(service, "logger")


# ---------------------------------------------------------------------------
# SPBaseRelayService — Startup
# ---------------------------------------------------------------------------


class TestServiceStartup:
    """Tests for service startup process."""

    @patch("sp_rtk_base_relay.main.MetricsCollector")
    @patch("sp_rtk_base_relay.main.InputSourceFactory")
    @patch("sp_rtk_base_relay.main.DestinationFactory")
    @patch("sp_rtk_base_relay.main.BroadcastHub")
    def test_start_success(
        self,
        mock_hub_cls: Mock,
        mock_dest_factory: Mock,
        mock_input_factory: Mock,
        mock_metrics_cls: Mock,
        mock_config: Mock,
        mock_input_source: Mock,
        mock_destination: Mock,
    ) -> None:
        mock_metrics_cls.return_value = Mock()
        mock_input_factory.create_input_source.return_value = mock_input_source
        mock_dest_factory.create_all.return_value = [mock_destination]
        mock_hub_cls.return_value = Mock()

        service = SPBaseRelayService(mock_config)
        service.start()

        assert service._running
        assert service.metrics is not None
        assert service.input_source is not None
        assert len(service.destinations) == 1
        assert service.hub is not None

    @patch("sp_rtk_base_relay.main.MetricsCollector")
    def test_start_with_metrics_enabled(
        self, mock_metrics_cls: Mock, mock_config: Mock
    ) -> None:
        mock_metrics = Mock()
        mock_metrics_cls.return_value = mock_metrics
        mock_config.metrics.enabled = True

        service = SPBaseRelayService(mock_config)
        with (
            patch.object(service, "_create_input_source"),
            patch.object(service, "_create_destinations"),
            patch.object(service, "_start_hub"),
        ):
            service.start()

        mock_metrics.start_metrics_server.assert_called_once_with(
            port=mock_config.metrics.port, host=mock_config.metrics.host
        )

    @patch("sp_rtk_base_relay.main.MetricsCollector")
    def test_start_without_metrics(
        self, mock_metrics_cls: Mock, mock_config: Mock
    ) -> None:
        mock_config.metrics.enabled = False
        service = SPBaseRelayService(mock_config)
        with (
            patch.object(service, "_create_input_source"),
            patch.object(service, "_create_destinations"),
            patch.object(service, "_start_hub"),
        ):
            service.start()
        assert service.metrics is None
        mock_metrics_cls.assert_not_called()

    def test_start_when_already_running(self, mock_config: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = True
        with pytest.raises(ServiceError, match="already running"):
            service.start()

    def test_start_failure_triggers_cleanup(self, mock_config: Mock) -> None:
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


# ---------------------------------------------------------------------------
# SPBaseRelayService — Shutdown
# ---------------------------------------------------------------------------


class TestServiceShutdown:
    """Tests for service shutdown."""

    def test_stop_success(
        self,
        mock_config: Mock,
        mock_input_source: Mock,
        mock_hub: Mock,
        mock_metrics: Mock,
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.input_source = mock_input_source
        service.hub = mock_hub
        service.metrics = mock_metrics

        service.stop()

        assert not service._running
        assert service._shutdown_requested
        mock_hub.stop.assert_called_once()
        mock_input_source.disconnect.assert_called_once()
        mock_metrics.stop_metrics_server.assert_called_once()

    def test_stop_when_not_running(self, mock_config: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = False
        service.stop()
        assert not service._running

    def test_stop_with_partial_components(
        self, mock_config: Mock, mock_hub: Mock
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.hub = mock_hub
        service.input_source = None
        service.metrics = None

        service.stop()

        assert not service._running
        mock_hub.stop.assert_called_once()

    def test_stop_handles_errors(self, mock_config: Mock, mock_hub: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.hub = mock_hub
        mock_hub.stop.side_effect = Exception("Stop error")

        with pytest.raises(ServiceError):
            service.stop()


# ---------------------------------------------------------------------------
# SPBaseRelayService — Run loop
# ---------------------------------------------------------------------------


class TestServiceRun:
    """Tests for service run loop."""

    @patch("sp_rtk_base_relay.main.time.sleep")
    def test_run_until_shutdown(
        self, mock_sleep: Mock, mock_config: Mock, mock_hub: Mock
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.hub = mock_hub
        service.metrics = None

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

    def test_run_not_started_raises_error(self, mock_config: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = False
        with pytest.raises(ServiceError, match="must be started"):
            service.run()

    @patch("sp_rtk_base_relay.main.time.sleep")
    def test_run_handles_keyboard_interrupt(
        self, mock_sleep: Mock, mock_config: Mock, mock_hub: Mock
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.hub = mock_hub
        service.metrics = None
        mock_sleep.side_effect = KeyboardInterrupt()

        with patch.object(service, "stop"):
            exit_code = service.run()
        assert exit_code == 0

    @patch("sp_rtk_base_relay.main.time.sleep")
    def test_run_handles_exceptions(
        self, mock_sleep: Mock, mock_config: Mock, mock_hub: Mock
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.hub = mock_hub
        service.metrics = None
        mock_sleep.side_effect = RuntimeError("Unexpected error")

        with patch.object(service, "stop"):
            exit_code = service.run()
        assert exit_code == 1

    @patch("sp_rtk_base_relay.main.time.sleep")
    def test_run_updates_metrics(
        self,
        mock_sleep: Mock,
        mock_config: Mock,
        mock_hub: Mock,
        mock_metrics: Mock,
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = True
        service.hub = mock_hub
        service.metrics = mock_metrics

        def sleep_side_effect(seconds: float) -> None:
            service._shutdown_requested = True

        mock_sleep.side_effect = sleep_side_effect

        with (
            patch.object(service, "_update_metrics") as mock_update,
            patch.object(service, "stop"),
        ):
            service.run()
        mock_update.assert_called()


# ---------------------------------------------------------------------------
# SPBaseRelayService — Component creation
# ---------------------------------------------------------------------------


class TestServiceComponents:
    """Tests for component creation methods."""

    @patch("sp_rtk_base_relay.main.InputSourceFactory")
    def test_create_tcp_input_source(
        self, mock_factory: Mock, mock_config: Mock, mock_input_source: Mock
    ) -> None:
        mock_factory.create_input_source.return_value = mock_input_source
        mock_config.input.source = "tcp"

        service = SPBaseRelayService(mock_config)
        service._create_input_source()

        assert service.input_source is mock_input_source
        args = mock_factory.create_input_source.call_args
        assert args[0][0] == "tcp"

    @patch("sp_rtk_base_relay.main.InputSourceFactory")
    def test_create_serial_input_source(
        self, mock_factory: Mock, mock_config: Mock, mock_input_source: Mock
    ) -> None:
        mock_factory.create_input_source.return_value = mock_input_source
        mock_config.input.source = "serial"
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

        args = mock_factory.create_input_source.call_args
        assert args[0][0] == "serial"

    @patch("sp_rtk_base_relay.main.InputSourceFactory")
    def test_create_usb_serial_maps_to_serial(
        self, mock_factory: Mock, mock_config: Mock, mock_input_source: Mock
    ) -> None:
        mock_factory.create_input_source.return_value = mock_input_source
        mock_config.input.source = "usb_serial"
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

        args = mock_factory.create_input_source.call_args
        assert args[0][0] == "serial"

    def test_create_input_source_unsupported_type(self, mock_config: Mock) -> None:
        mock_config.input.source = "invalid"
        service = SPBaseRelayService(mock_config)
        with pytest.raises(ConfigurationError, match="Unsupported input source"):
            service._create_input_source()

    @patch("sp_rtk_base_relay.main.DestinationFactory")
    def test_create_destinations(
        self, mock_factory: Mock, mock_config: Mock, mock_destination: Mock
    ) -> None:
        mock_factory.create_all.return_value = [mock_destination]

        service = SPBaseRelayService(mock_config)
        service._create_destinations()

        assert len(service.destinations) == 1
        mock_factory.create_all.assert_called_once_with(mock_config.destinations)

    def test_create_destinations_no_config(self, mock_config: Mock) -> None:
        mock_config.destinations = []
        service = SPBaseRelayService(mock_config)
        with pytest.raises(ConfigurationError, match="No destinations configured"):
            service._create_destinations()

    @patch("sp_rtk_base_relay.main.DestinationFactory")
    def test_create_destinations_none_enabled(
        self, mock_factory: Mock, mock_config: Mock
    ) -> None:
        mock_factory.create_all.return_value = []
        service = SPBaseRelayService(mock_config)
        with pytest.raises(ConfigurationError, match="No enabled destinations"):
            service._create_destinations()

    @patch("sp_rtk_base_relay.main.BroadcastHub")
    def test_start_hub(
        self,
        mock_hub_cls: Mock,
        mock_config: Mock,
        mock_input_source: Mock,
        mock_destination: Mock,
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service.input_source = mock_input_source
        service.destinations = [mock_destination]
        service._start_hub()

        assert service.hub is not None
        mock_hub_cls.assert_called_once_with(
            input_source=mock_input_source,
            destinations=[mock_destination],
        )
        mock_hub_cls.return_value.start.assert_called_once()

    def test_start_hub_without_input_raises(self, mock_config: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        service.input_source = None
        service.destinations = [Mock()]
        with pytest.raises(ServiceError, match="Input source must be created"):
            service._start_hub()

    def test_start_hub_without_destinations_raises(
        self, mock_config: Mock, mock_input_source: Mock
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service.input_source = mock_input_source
        service.destinations = []
        with pytest.raises(ServiceError, match="Destinations must be created"):
            service._start_hub()


# ---------------------------------------------------------------------------
# SPBaseRelayService — Health
# ---------------------------------------------------------------------------


class TestServiceHealth:
    """Tests for health checking."""

    def test_check_health_when_healthy(self, mock_config: Mock, mock_hub: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        service.hub = mock_hub
        mock_hub.is_running = True
        assert service._check_health()

    def test_check_health_when_unhealthy(
        self, mock_config: Mock, mock_hub: Mock
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service.hub = mock_hub
        mock_hub.is_running = False
        assert not service._check_health()

    def test_check_health_without_hub(self, mock_config: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        service.hub = None
        assert not service._check_health()


# ---------------------------------------------------------------------------
# SPBaseRelayService — Metrics
# ---------------------------------------------------------------------------


class TestServiceMetrics:
    """Tests for metrics updates."""

    def test_update_metrics_with_all_components(
        self,
        mock_config: Mock,
        mock_hub: Mock,
        mock_input_source: Mock,
        mock_destination: Mock,
        mock_metrics: Mock,
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service.hub = mock_hub
        service.input_source = mock_input_source
        service.destinations = [mock_destination]
        service.metrics = mock_metrics

        service._update_metrics()

        mock_metrics.update_all.assert_called_once()

    def test_update_metrics_without_collector(
        self, mock_config: Mock, mock_hub: Mock
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service.hub = mock_hub
        service.metrics = None
        # Should not raise
        service._update_metrics()

    def test_update_metrics_handles_errors(
        self, mock_config: Mock, mock_hub: Mock, mock_metrics: Mock
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service.hub = mock_hub
        service.metrics = mock_metrics
        mock_metrics.update_all.side_effect = Exception("Metrics error")
        # Should not raise
        service._update_metrics()


# ---------------------------------------------------------------------------
# SPBaseRelayService — Cleanup
# ---------------------------------------------------------------------------


class TestServiceCleanup:
    """Tests for cleanup."""

    def test_cleanup_all_components(
        self,
        mock_config: Mock,
        mock_hub: Mock,
        mock_input_source: Mock,
        mock_metrics: Mock,
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service.hub = mock_hub
        service.input_source = mock_input_source
        service.metrics = mock_metrics

        service._cleanup()

        mock_hub.stop.assert_called_once()
        mock_input_source.disconnect.assert_called_once()
        mock_metrics.stop_metrics_server.assert_called_once()

    def test_cleanup_handles_errors(self, mock_config: Mock, mock_hub: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        service.hub = mock_hub
        mock_hub.stop.side_effect = Exception("Cleanup error")
        # Should not raise
        service._cleanup()


# ---------------------------------------------------------------------------
# CLI Parser
# ---------------------------------------------------------------------------


class TestCLIParser:
    """Tests for CLI argument parser."""

    def test_parser_creation(self) -> None:
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_parse_default_config_path(self) -> None:
        parser = create_parser()
        args = parser.parse_args([])
        assert args.config == Path("/etc/sp-rtk-base-relay/config.yaml")

    def test_parse_custom_config_path(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["--config", "/custom/path/config.yaml"])
        assert args.config == Path("/custom/path/config.yaml")

    def test_parse_config_short_flag(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["-c", "/custom/config.yaml"])
        assert args.config == Path("/custom/config.yaml")

    def test_parse_validate_flag(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["--validate"])
        assert args.validate is True

    def test_parse_generate_config_flag(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["--generate-config"])
        assert args.generate_config is True

    def test_parse_foreground_flag(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["--foreground"])
        assert args.foreground is True

    def test_parse_log_level(self) -> None:
        parser = create_parser()
        args = parser.parse_args(["--log-level", "DEBUG"])
        assert args.log_level == "DEBUG"

    def test_parse_multiple_flags(self) -> None:
        parser = create_parser()
        args = parser.parse_args(
            ["--config", "/custom/config.yaml", "--foreground", "--log-level", "DEBUG"]
        )
        assert args.config == Path("/custom/config.yaml")
        assert args.foreground is True
        assert args.log_level == "DEBUG"


# ---------------------------------------------------------------------------
# Signal Handlers
# ---------------------------------------------------------------------------


class TestSignalHandlers:
    """Tests for signal handler setup."""

    def test_setup_signal_handlers(self, mock_config: Mock) -> None:
        service = SPBaseRelayService(mock_config)
        with patch("signal.signal") as mock_signal:
            setup_signal_handlers(service)
            calls = mock_signal.call_args_list
            assert len(calls) == 2
            assert calls[0][0][0] == signal.SIGTERM
            assert calls[1][0][0] == signal.SIGINT

    @patch("sp_rtk_base_relay.main.sys.exit")
    def test_signal_handler_stops_service(
        self, mock_exit: Mock, mock_config: Mock
    ) -> None:
        service = SPBaseRelayService(mock_config)
        service._running = True

        with patch("signal.signal") as mock_signal:
            setup_signal_handlers(service)
            handler = mock_signal.call_args_list[0][0][1]
            with patch.object(service, "stop") as mock_stop:
                handler(signal.SIGTERM, None)
                mock_stop.assert_called_once()
                mock_exit.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# Main Function
# ---------------------------------------------------------------------------


class TestMainFunction:
    """Tests for main() entry point."""

    @patch("sp_rtk_base_relay.main.ConfigManager.generate_default_config")
    def test_main_generate_config_mode(
        self, mock_gen: Mock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_gen.return_value = "# Config"
        with patch("sys.argv", ["sp-rtk-base-relay", "--generate-config"]):
            exit_code = main()
        assert exit_code == 0
        assert "# Config" in capsys.readouterr().out

    @patch("sp_rtk_base_relay.main.ConfigManager")
    @patch("sp_rtk_base_relay.main.LoggerManager")
    def test_main_validate_mode(
        self,
        mock_logger_mgr: Mock,
        mock_config_mgr_cls: Mock,
        mock_config: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_config_mgr = Mock()
        mock_config_mgr.load_config.return_value = mock_config
        mock_config_mgr_cls.return_value = mock_config_mgr

        with patch("sys.argv", ["sp-rtk-base-relay", "--validate"]):
            exit_code = main()
        assert exit_code == 0
        assert "valid" in capsys.readouterr().out.lower()

    @patch("sp_rtk_base_relay.main.ConfigManager")
    def test_main_config_load_error(
        self, mock_config_mgr_cls: Mock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_config_mgr = Mock()
        mock_config_mgr.load_config.side_effect = ConfigurationError("Invalid config")
        mock_config_mgr_cls.return_value = mock_config_mgr

        with patch("sys.argv", ["sp-rtk-base-relay"]):
            exit_code = main()
        assert exit_code == 1
        assert "Error loading configuration" in capsys.readouterr().err

    @patch("sp_rtk_base_relay.main.ConfigManager")
    @patch("sp_rtk_base_relay.main.LoggerManager")
    def test_main_logger_setup_error(
        self,
        mock_logger_mgr: Mock,
        mock_config_mgr_cls: Mock,
        mock_config: Mock,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        mock_config_mgr = Mock()
        mock_config_mgr.load_config.return_value = mock_config
        mock_config_mgr_cls.return_value = mock_config_mgr
        mock_logger_mgr.setup_logging.side_effect = Exception("Logger error")

        with patch("sys.argv", ["sp-rtk-base-relay"]):
            exit_code = main()
        assert exit_code == 1
        assert "Error setting up logging" in capsys.readouterr().err

    @patch("sp_rtk_base_relay.main.ConfigManager")
    @patch("sp_rtk_base_relay.main.LoggerManager")
    @patch("sp_rtk_base_relay.main.SPBaseRelayService")
    @patch("sp_rtk_base_relay.main.setup_signal_handlers")
    def test_main_successful_run(
        self,
        mock_setup_signals: Mock,
        mock_service_cls: Mock,
        mock_logger_mgr: Mock,
        mock_config_mgr_cls: Mock,
        mock_config: Mock,
    ) -> None:
        mock_config_mgr = Mock()
        mock_config_mgr.load_config.return_value = mock_config
        mock_config_mgr_cls.return_value = mock_config_mgr
        mock_service = Mock()
        mock_service.run.return_value = 0
        mock_service_cls.return_value = mock_service

        with patch("sys.argv", ["sp-rtk-base-relay"]):
            exit_code = main()

        assert exit_code == 0
        mock_service.start.assert_called_once()
        mock_service.run.assert_called_once()
        mock_logger_mgr.shutdown_logging.assert_called_once()

    @patch("sp_rtk_base_relay.main.ConfigManager")
    @patch("sp_rtk_base_relay.main.LoggerManager")
    @patch("sp_rtk_base_relay.main.SPBaseRelayService")
    def test_main_service_error(
        self,
        mock_service_cls: Mock,
        mock_logger_mgr: Mock,
        mock_config_mgr_cls: Mock,
        mock_config: Mock,
    ) -> None:
        mock_config_mgr = Mock()
        mock_config_mgr.load_config.return_value = mock_config
        mock_config_mgr_cls.return_value = mock_config_mgr
        mock_service = Mock()
        mock_service.start.side_effect = ServiceError("Service error")
        mock_service_cls.return_value = mock_service

        with patch("sys.argv", ["sp-rtk-base-relay"]):
            exit_code = main()
        assert exit_code == 1

    @patch("sp_rtk_base_relay.main.ConfigManager")
    @patch("sp_rtk_base_relay.main.LoggerManager")
    @patch("sp_rtk_base_relay.main.SPBaseRelayService")
    def test_main_keyboard_interrupt(
        self,
        mock_service_cls: Mock,
        mock_logger_mgr: Mock,
        mock_config_mgr_cls: Mock,
        mock_config: Mock,
    ) -> None:
        mock_config_mgr = Mock()
        mock_config_mgr.load_config.return_value = mock_config
        mock_config_mgr_cls.return_value = mock_config_mgr
        mock_service = Mock()
        mock_service.start.side_effect = KeyboardInterrupt()
        mock_service_cls.return_value = mock_service

        with patch("sys.argv", ["sp-rtk-base-relay"]):
            exit_code = main()
        assert exit_code == 0

    @patch("sp_rtk_base_relay.main.ConfigManager")
    @patch("sp_rtk_base_relay.main.LoggerManager")
    def test_main_log_level_override(
        self,
        mock_logger_mgr: Mock,
        mock_config_mgr_cls: Mock,
        mock_config: Mock,
    ) -> None:
        mock_config_mgr = Mock()
        mock_config_mgr.load_config.return_value = mock_config
        mock_config_mgr_cls.return_value = mock_config_mgr

        with (
            patch("sys.argv", ["sp-rtk-base-relay", "--log-level", "DEBUG"]),
            patch("sp_rtk_base_relay.main.SPBaseRelayService"),
            patch("sp_rtk_base_relay.main.setup_signal_handlers"),
        ):
            try:
                main()
            except Exception:
                pass
        assert mock_config.logging.level == "DEBUG"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
