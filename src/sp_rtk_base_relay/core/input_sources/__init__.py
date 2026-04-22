"""Input source management for SP-Base-Relay.

This package provides multiple input source implementations for reading RTCM
correction data from various sources including serial ports, TCP connections,
and USB serial adapters.
"""

from .base_input import InputSource, InputSourceStats
from .input_factory import InputSourceFactory
from .serial_input import SerialConfig, SerialInputSource
from .tcp_input import TCPConfig, TCPInputSource

__all__ = [
    "InputSource",
    "InputSourceFactory",
    "InputSourceStats",
    "SerialConfig",
    "SerialInputSource",
    "TCPConfig",
    "TCPInputSource",
]
