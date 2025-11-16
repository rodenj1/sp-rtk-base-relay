"""Unit tests for SP-Base-Relay logging system."""

import logging
import tempfile
import json
from unittest.mock import Mock
import pytest

from sp_base_relay.logger import (
    JSONFormatter,
    TextFormatter,
    LoggerManager,
    get_logger,
    setup_logging,
    LogLevelContext,
    log_with_context,
    log_operation_start,
    log_operation_success,
    log_operation_error,
)
from sp_base_relay.config import LoggingConfig
from sp_base_relay.exceptions import ConfigurationError


class TestJSONFormatter:
    """Test JSON log formatter."""

    def test_format_basic_message(self):
        """Test formatting basic log message."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "Test message"
        assert data["line"] == 42
        assert "timestamp" in data

    def test_format_with_extra_fields(self):
        """Test formatting with extra context fields."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="/test/path.py",
            lineno=42,
            msg="Error occurred",
            args=(),
            exc_info=None,
        )
        record.operation = "test_operation"
        record.error_code = 500

        output = formatter.format(record)
        data = json.loads(output)

        assert data["message"] == "Error occurred"
        assert data["extra"]["operation"] == "test_operation"
        assert data["extra"]["error_code"] == 500

    def test_format_with_exception(self):
        """Test formatting with exception info."""
        formatter = JSONFormatter()

        try:
            raise ValueError("Test exception")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test.logger",
                level=logging.ERROR,
                pathname="/test/path.py",
                lineno=42,
                msg="Exception occurred",
                args=(),
                exc_info=sys.exc_info(),
            )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["message"] == "Exception occurred"
        assert "exception" in data
        assert "ValueError: Test exception" in data["exception"]


class TestTextFormatter:
    """Test text log formatter."""

    def test_format_basic_message(self):
        """Test formatting basic log message."""
        formatter = TextFormatter(use_colors=False)
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)

        assert "[INFO]" in output
        assert "[test.logger]" in output
        assert "Test message" in output

    def test_format_with_colors_disabled(self):
        """Test formatting without colors."""
        formatter = TextFormatter(use_colors=False)
        record = logging.LogRecord(
            name="test.logger",
            level=logging.ERROR,
            pathname="/test/path.py",
            lineno=42,
            msg="Error message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)

        # Should not contain ANSI color codes
        assert "\033[" not in output
        assert "[ERROR]" in output

    def test_format_debug_with_location(self):
        """Test debug level includes location info."""
        formatter = TextFormatter(use_colors=False)
        record = logging.LogRecord(
            name="test.logger",
            level=logging.DEBUG,
            pathname="/test/path.py",
            lineno=42,
            msg="Debug message",
            args=(),
            exc_info=None,
        )
        record.filename = "path.py"
        record.funcName = "test_function"

        output = formatter.format(record)

        assert "[DEBUG]" in output
        assert "path.py:42:test_function()" in output

    def test_format_with_extra_fields(self):
        """Test formatting with extra context fields."""
        formatter = TextFormatter(use_colors=False)
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/path.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.operation = "test_op"
        record.user_id = 123

        output = formatter.format(record)

        assert "Test message" in output
        assert "operation=test_op" in output
        assert "user_id=123" in output


class TestLoggerManager:
    """Test logger manager."""

    def teardown_method(self):
        """Clean up after each test."""
        LoggerManager.shutdown_logging()

    def test_setup_logging_basic(self):
        """Test basic logging setup."""
        config = LoggingConfig(level="DEBUG", format="text", file=None)

        logger = LoggerManager.setup_logging(config)

        assert logger is not None
        assert logger.level == logging.DEBUG
        assert len(logger.handlers) == 1  # Console handler

    def test_setup_logging_with_file(self):
        """Test logging setup with file output."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            config = LoggingConfig(
                level="INFO", format="json", file=f.name, max_size_mb=10, backup_count=2
            )

            logger = LoggerManager.setup_logging(config)

            assert logger is not None
            assert len(logger.handlers) == 2  # Console + file handlers

    def test_setup_logging_file_permission_error(self):
        """Test logging setup with file permission error."""
        config = LoggingConfig(
            level="INFO", format="json", file="/root/no-permission.log"  # Should fail
        )

        # Should not raise exception, but log warning
        logger = LoggerManager.setup_logging(config)

        assert logger is not None
        assert len(logger.handlers) == 1  # Only console handler

    def test_get_logger_before_setup(self):
        """Test getting logger before setup."""
        logger = LoggerManager.get_logger("test")

        assert logger is not None
        assert logger.name == "test"

    def test_get_logger_after_setup(self):
        """Test getting logger after setup."""
        config = LoggingConfig(level="DEBUG", format="text", file=None)
        root_logger = LoggerManager.setup_logging(config)

        child_logger = LoggerManager.get_logger("child")

        assert child_logger is not None
        assert child_logger.parent == root_logger

    def test_reconfigure_logging(self):
        """Test reconfiguring logging."""
        config1 = LoggingConfig(level="INFO", format="text", file=None)
        LoggerManager.setup_logging(config1)

        config2 = LoggingConfig(level="DEBUG", format="json", file=None)
        LoggerManager.reconfigure_logging(config2)

        logger2 = LoggerManager.get_logger()
        assert logger2.level == logging.DEBUG

    def test_setup_logging_invalid_config(self):
        """Test setup with invalid config should raise error."""
        # Config validation happens during LoggingConfig creation
        with pytest.raises(ConfigurationError):
            LoggingConfig(level="INVALID", format="json", file=None)


class TestConvenienceFunctions:
    """Test convenience functions."""

    def teardown_method(self):
        """Clean up after each test."""
        LoggerManager.shutdown_logging()

    def test_get_logger_function(self):
        """Test get_logger convenience function."""
        logger = get_logger("test")
        assert logger is not None

    def test_setup_logging_function(self):
        """Test setup_logging convenience function."""
        config = LoggingConfig(level="INFO", format="text", file=None)
        logger = setup_logging(config)
        assert logger is not None


class TestLogLevelContext:
    """Test log level context manager."""

    def test_temporary_log_level_change(self):
        """Test temporary log level change."""
        logger = logging.getLogger("test")
        original_level = logging.INFO
        logger.setLevel(original_level)

        with LogLevelContext(logger, logging.DEBUG):
            assert logger.level == logging.DEBUG

        assert logger.level == original_level

    def test_temporary_log_level_change_string(self):
        """Test temporary log level change with string."""
        logger = logging.getLogger("test")
        original_level = logging.INFO
        logger.setLevel(original_level)

        with LogLevelContext(logger, "ERROR"):
            assert logger.level == logging.ERROR

        assert logger.level == original_level


class TestStructuredLoggingHelpers:
    """Test structured logging helper functions."""

    def test_log_with_context(self):
        """Test logging with context."""
        logger = Mock()

        log_with_context(
            logger, logging.INFO, "Test message", operation="test_op", user_id=123
        )

        logger.log.assert_called_once_with(
            logging.INFO, "Test message", extra={"operation": "test_op", "user_id": 123}
        )

    def test_log_operation_start(self):
        """Test operation start logging."""
        logger = Mock()

        log_operation_start(logger, "data_processing", user_id=123)

        logger.log.assert_called_once_with(
            logging.INFO,
            "Starting operation: data_processing",
            extra={
                "operation": "data_processing",
                "operation_status": "start",
                "user_id": 123,
            },
        )

    def test_log_operation_success(self):
        """Test operation success logging."""
        logger = Mock()

        log_operation_success(logger, "data_processing", duration=1.5, records=100)

        logger.log.assert_called_once_with(
            logging.INFO,
            "Operation completed successfully: data_processing (took 1.50s)",
            extra={
                "operation": "data_processing",
                "operation_status": "success",
                "duration_seconds": 1.5,
                "records": 100,
            },
        )

    def test_log_operation_success_no_duration(self):
        """Test operation success logging without duration."""
        logger = Mock()

        log_operation_success(logger, "data_processing", records=100)

        logger.log.assert_called_once()
        args, kwargs = logger.log.call_args
        assert "took" not in args[1]  # Message should not contain duration
        assert "duration_seconds" not in kwargs["extra"]

    def test_log_operation_error(self):
        """Test operation error logging."""
        logger = Mock()
        error = ValueError("Test error")

        log_operation_error(logger, "data_processing", error, duration=0.5, user_id=123)

        logger.error.assert_called_once()
        args, kwargs = logger.error.call_args

        assert "Operation failed: data_processing - Test error" in args[0]
        assert "(after 0.50s)" in args[0]

        extra = kwargs["extra"]
        assert extra["operation"] == "data_processing"
        assert extra["operation_status"] == "error"
        assert extra["error_type"] == "ValueError"
        assert extra["error_message"] == "Test error"
        assert extra["duration_seconds"] == 0.5
        assert extra["user_id"] == 123
        assert kwargs["exc_info"] is True

    def test_log_operation_error_no_duration(self):
        """Test operation error logging without duration."""
        logger = Mock()
        error = ConnectionError("Connection failed")

        log_operation_error(logger, "network_request", error)

        logger.error.assert_called_once()
        args, kwargs = logger.error.call_args

        assert "Operation failed: network_request - Connection failed" in args[0]
        assert "after" not in args[0]  # Should not contain duration info

        extra = kwargs["extra"]
        assert "duration_seconds" not in extra


if __name__ == "__main__":
    pytest.main([__file__])
