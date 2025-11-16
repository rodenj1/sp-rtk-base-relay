"""Input source management for SP-Base-Relay.

This package provides multiple input source implementations for reading RTCM
correction data from various sources including serial ports, TCP connections,
and USB serial adapters.
"""

from .base_input import InputSource, InputSourceStats
from .serial_input import SerialInputSource, SerialConfig
from .tcp_input import TCPInputSource, TCPConfig
from .input_factory import InputSourceFactory

__all__ = [
    "InputSource",
    "InputSourceStats",
    "SerialInputSource",
    "SerialConfig",
    "TCPInputSource",
    "TCPConfig",
    "InputSourceFactory",
]
