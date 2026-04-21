"""Logging configuration and setup for SP-Base-Relay.

This module provides structured logging with support for:
- JSON and text output formats
- File rotation and console output
- Configurable log levels
- Structured logging with context information
"""

import json
import logging
import logging.handlers
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import LoggingConfig
from .exceptions import ConfigurationError


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON.

        Args:
            record: Log record to format

        Returns:
            JSON-formatted log string
        """
        # Base log entry
        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add module and function information
        if record.module:
            log_entry["module"] = record.module
        if record.funcName and record.funcName != "<module>":
            log_entry["function"] = record.funcName
        if record.lineno:
            log_entry["line"] = record.lineno

        # Add process and thread info for debugging
        if record.process:
            log_entry["process"] = record.process
        if record.thread:
            log_entry["thread"] = record.thread

        # Add exception information if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        # Add extra fields if present
        extra_fields: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "exc_info",
                "exc_text",
                "stack_info",
                "getMessage",
                "extra",
            }:
                extra_fields[key] = value

        if extra_fields:
            log_entry["extra"] = extra_fields

        return json.dumps(log_entry, default=str)


class TextFormatter(logging.Formatter):
    """Enhanced text formatter with color support and structured information."""

    # Color codes for different log levels
    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def __init__(self, use_colors: bool = True):
        """Initialize text formatter.

        Args:
            use_colors: Whether to use color codes in output
        """
        super().__init__()
        self.use_colors = use_colors

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as human-readable text.

        Args:
            record: Log record to format

        Returns:
            Formatted log string
        """
        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S")

        # Format level with optional color
        level = record.levelname
        if self.use_colors and sys.stderr.isatty():
            color = self.COLORS.get(level, "")
            level = f"{color}{level}{self.RESET}"

        # Build base message
        parts = [
            f"[{timestamp}]",
            f"[{level}]",
            f"[{record.name}]",
            record.getMessage(),
        ]

        # Add location info for debug level
        if record.levelno <= logging.DEBUG:
            location = f"{record.filename}:{record.lineno}"
            if record.funcName and record.funcName != "<module>":
                location += f":{record.funcName}()"
            parts.insert(-1, f"[{location}]")

        message = " ".join(parts)

        # Add exception information if present
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        # Add extra fields if present
        extra_fields: dict[str, Any] = {}
        for key, value in record.__dict__.items():
            if key not in {
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "exc_info",
                "exc_text",
                "stack_info",
                "getMessage",
                "extra",
            }:
                extra_fields[key] = value

        if extra_fields:
            extra_str = " | ".join(
                f"{str(k)}={str(v)}" for k, v in extra_fields.items()
            )
            message += f" | {extra_str}"

        return message


class LoggerManager:
    """Manager for SP-Base-Relay logging configuration."""

    _configured = False
    _root_logger: logging.Logger | None = None

    @classmethod
    def setup_logging(
        cls, config: LoggingConfig, logger_name: str = "sp_rtk_base_relay"
    ) -> logging.Logger:
        """Set up logging configuration.

        Args:
            config: Logging configuration
            logger_name: Name of the root logger

        Returns:
            Configured logger instance

        Raises:
            ConfigurationError: If logging setup fails
        """
        if cls._configured:
            if cls._root_logger:
                return cls._root_logger
            else:
                return logging.getLogger(logger_name)

        try:
            # Get root logger
            root_logger = logging.getLogger(logger_name)
            root_logger.setLevel(getattr(logging, config.level))

            # Clear existing handlers
            root_logger.handlers.clear()

            # Set up formatter
            if config.format == "json":
                formatter = JSONFormatter()
            else:  # text format
                formatter = TextFormatter(use_colors=True)

            # Set up console handler (always present)
            console_handler = logging.StreamHandler(sys.stderr)
            console_handler.setLevel(getattr(logging, config.level))
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)

            # Set up file handler if configured
            if config.file:
                try:
                    # Ensure log directory exists
                    log_file = Path(config.file)
                    log_file.parent.mkdir(parents=True, exist_ok=True)

                    # Create rotating file handler
                    max_bytes = config.max_size_mb * 1024 * 1024  # Convert MB to bytes
                    file_handler = logging.handlers.RotatingFileHandler(
                        filename=config.file,
                        maxBytes=max_bytes,
                        backupCount=config.backup_count,
                        encoding="utf-8",
                    )

                    file_handler.setLevel(getattr(logging, config.level))

                    # Use JSON formatter for file output regardless of console format
                    file_formatter = JSONFormatter()
                    file_handler.setFormatter(file_formatter)

                    root_logger.addHandler(file_handler)

                except (OSError, PermissionError) as e:
                    # Log to console that file logging failed, but don't fail startup
                    root_logger.warning(
                        f"Failed to set up file logging to {config.file}: {e}",
                        extra={"error_type": type(e).__name__},
                    )

            # Prevent propagation to avoid duplicate logs
            root_logger.propagate = False

            # Mark as configured
            cls._configured = True
            cls._root_logger = root_logger

            # Log initial message
            root_logger.info(
                "Logging system initialized",
                extra={
                    "log_level": config.level,
                    "log_format": config.format,
                    "log_file": config.file,
                    "file_max_size_mb": config.max_size_mb,
                    "backup_count": config.backup_count,
                },
            )

            return root_logger

        except Exception as e:
            raise ConfigurationError(
                f"Failed to set up logging: {e}", config_key="logging", details=str(e)
            )

    @classmethod
    def get_logger(cls, name: str = "sp_rtk_base_relay") -> logging.Logger:
        """Get a logger instance.

        Args:
            name: Logger name (will be prefixed with root logger name)

        Returns:
            Logger instance
        """
        if not cls._configured:
            # Return a basic logger if not configured yet
            logger = logging.getLogger(name)
            if not logger.handlers:
                handler = logging.StreamHandler()
                handler.setFormatter(
                    logging.Formatter(
                        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
                    )
                )
                logger.addHandler(handler)
                logger.setLevel(logging.INFO)
            return logger

        # Return child logger
        if cls._root_logger:
            if name == "sp_rtk_base_relay":
                return cls._root_logger
            else:
                return cls._root_logger.getChild(name.replace("sp_rtk_base_relay.", ""))
        else:
            return logging.getLogger(name)

    @classmethod
    def reconfigure_logging(cls, config: LoggingConfig) -> None:
        """Reconfigure logging with new settings.

        Args:
            config: New logging configuration
        """
        cls._configured = False
        cls._root_logger = None
        cls.setup_logging(config)

    @classmethod
    def shutdown_logging(cls) -> None:
        """Shutdown logging system and cleanup resources."""
        if cls._root_logger:
            for handler in cls._root_logger.handlers[:]:
                handler.close()
                cls._root_logger.removeHandler(handler)

        cls._configured = False
        cls._root_logger = None

        # Shutdown logging module
        logging.shutdown()


# Convenience functions for getting loggers
def get_logger(name: str = "sp_rtk_base_relay") -> logging.Logger:
    """Get a logger instance.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return LoggerManager.get_logger(name)


def setup_logging(config: LoggingConfig) -> logging.Logger:
    """Set up logging configuration.

    Args:
        config: Logging configuration

    Returns:
        Configured logger instance
    """
    return LoggerManager.setup_logging(config)


# Context manager for temporary log level changes
class LogLevelContext:
    """Context manager for temporarily changing log level."""

    def __init__(self, logger: logging.Logger, level: int | str):
        """Initialize context manager.

        Args:
            logger: Logger to modify
            level: Temporary log level
        """
        self.logger = logger
        self.original_level = logger.level

        if isinstance(level, str):
            self.temp_level = getattr(logging, level.upper())
        else:
            self.temp_level = level

    def __enter__(self) -> logging.Logger:
        """Enter context and set temporary log level."""
        self.logger.setLevel(self.temp_level)
        return self.logger

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit context and restore original log level."""
        self.logger.setLevel(self.original_level)


# Structured logging helper functions
def log_with_context(
    logger: logging.Logger, level: int, message: str, **context: Any
) -> None:
    """Log message with additional context information.

    Args:
        logger: Logger to use
        level: Log level
        message: Log message
        **context: Additional context fields
    """
    logger.log(level, message, extra=context)


def log_operation_start(logger: logging.Logger, operation: str, **context: Any) -> None:
    """Log the start of an operation.

    Args:
        logger: Logger to use
        operation: Name of the operation starting
        **context: Additional context fields
    """
    log_with_context(
        logger,
        logging.INFO,
        f"Starting operation: {operation}",
        operation=operation,
        operation_status="start",
        **context,
    )


def log_operation_success(
    logger: logging.Logger,
    operation: str,
    duration: float | None = None,
    **context: Any,
) -> None:
    """Log successful completion of an operation.

    Args:
        logger: Logger to use
        operation: Name of the operation that completed
        duration: Optional operation duration in seconds
        **context: Additional context fields
    """
    extra_context = {"operation": operation, "operation_status": "success", **context}

    if duration is not None:
        extra_context["duration_seconds"] = duration

    message = f"Operation completed successfully: {operation}"
    if duration is not None:
        message += f" (took {duration:.2f}s)"

    log_with_context(logger, logging.INFO, message, **extra_context)


def log_operation_error(
    logger: logging.Logger,
    operation: str,
    error: Exception,
    duration: float | None = None,
    **context: Any,
) -> None:
    """Log failed operation with error information.

    Args:
        logger: Logger to use
        operation: Name of the operation that failed
        error: Exception that caused the failure
        duration: Optional operation duration in seconds
        **context: Additional context fields
    """
    extra_context = {
        "operation": operation,
        "operation_status": "error",
        "error_type": type(error).__name__,
        "error_message": str(error),
        **context,
    }

    if duration is not None:
        extra_context["duration_seconds"] = duration

    message = f"Operation failed: {operation} - {error}"
    if duration is not None:
        message += f" (after {duration:.2f}s)"

    logger.error(message, extra=extra_context, exc_info=True)
