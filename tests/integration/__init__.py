"""Integration tests for SP-Base-Relay.

This package contains integration tests that verify the complete system
functionality with real hardware and network connections. These tests are
designed to be run manually when hardware is available.

Test Suites:
- test_tcp_input_hardware.py: Tests TCP input with real hardware
- test_end_to_end_integration.py: Complete pipeline integration tests

Usage:
    # Run all integration tests
    uv run pytest tests/integration/ -v

    # Run specific test suite
    uv run pytest tests/integration/test_tcp_input_hardware.py -v

    # Run with detailed output
    uv run pytest tests/integration/ -v -s

See README.md for detailed information about running integration tests.
"""

__all__ = []
