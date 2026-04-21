"""Unit tests for RTCM connection state management.

Tests the ConnectionState enum and its properties to ensure proper
state tracking throughout the connection lifecycle.
"""

from sp_rtk_base_relay.core.connection_states import ConnectionState


class TestConnectionState:
    """Test cases for ConnectionState enum."""

    def test_connection_state_values(self):
        """Test that connection states have expected string values."""
        assert ConnectionState.DISCONNECTED.value == "disconnected"
        assert ConnectionState.CONNECTING.value == "connecting"
        assert ConnectionState.AUTHENTICATING.value == "authenticating"
        assert ConnectionState.CONNECTED.value == "connected"
        assert ConnectionState.RECONNECTING.value == "reconnecting"
        assert ConnectionState.ERROR.value == "error"
        assert ConnectionState.STOPPING.value == "stopping"

    def test_connection_state_str(self):
        """Test string representation of connection states."""
        assert str(ConnectionState.DISCONNECTED) == "disconnected"
        assert str(ConnectionState.CONNECTING) == "connecting"
        assert str(ConnectionState.AUTHENTICATING) == "authenticating"
        assert str(ConnectionState.CONNECTED) == "connected"
        assert str(ConnectionState.RECONNECTING) == "reconnecting"
        assert str(ConnectionState.ERROR) == "error"
        assert str(ConnectionState.STOPPING) == "stopping"

    def test_is_connected_property(self):
        """Test is_connected property returns correct values."""
        assert ConnectionState.CONNECTED.is_connected is True
        assert ConnectionState.DISCONNECTED.is_connected is False
        assert ConnectionState.CONNECTING.is_connected is False
        assert ConnectionState.AUTHENTICATING.is_connected is False
        assert ConnectionState.RECONNECTING.is_connected is False
        assert ConnectionState.ERROR.is_connected is False
        assert ConnectionState.STOPPING.is_connected is False

    def test_is_connecting_property(self):
        """Test is_connecting property returns correct values."""
        assert ConnectionState.CONNECTING.is_connecting is True
        assert ConnectionState.AUTHENTICATING.is_connecting is True
        assert ConnectionState.CONNECTED.is_connecting is False
        assert ConnectionState.DISCONNECTED.is_connecting is False
        assert ConnectionState.RECONNECTING.is_connecting is False
        assert ConnectionState.ERROR.is_connecting is False
        assert ConnectionState.STOPPING.is_connecting is False

    def test_can_send_data_property(self):
        """Test can_send_data property returns correct values."""
        assert ConnectionState.CONNECTED.can_send_data is True
        assert ConnectionState.DISCONNECTED.can_send_data is False
        assert ConnectionState.CONNECTING.can_send_data is False
        assert ConnectionState.AUTHENTICATING.can_send_data is False
        assert ConnectionState.RECONNECTING.can_send_data is False
        assert ConnectionState.ERROR.can_send_data is False
        assert ConnectionState.STOPPING.can_send_data is False

    def test_should_retry_property(self):
        """Test should_retry property returns correct values."""
        assert ConnectionState.DISCONNECTED.should_retry is True
        assert ConnectionState.ERROR.should_retry is True
        assert ConnectionState.CONNECTED.should_retry is False
        assert ConnectionState.CONNECTING.should_retry is False
        assert ConnectionState.AUTHENTICATING.should_retry is False
        assert ConnectionState.RECONNECTING.should_retry is False
        assert ConnectionState.STOPPING.should_retry is False

    def test_all_states_defined(self):
        """Test that all expected states are defined."""
        expected_states = {
            "DISCONNECTED",
            "CONNECTING",
            "AUTHENTICATING",
            "CONNECTED",
            "RECONNECTING",
            "ERROR",
            "STOPPING",
        }

        actual_states = {state.name for state in ConnectionState}
        assert actual_states == expected_states

    def test_state_equality(self):
        """Test state equality comparisons."""
        assert ConnectionState.CONNECTED == ConnectionState.CONNECTED
        assert ConnectionState.CONNECTED != ConnectionState.DISCONNECTED

        # Test with variables
        state1 = ConnectionState.CONNECTED
        state2 = ConnectionState.CONNECTED
        state3 = ConnectionState.DISCONNECTED

        assert state1 == state2
        assert state1 != state3

    def test_state_membership(self):
        """Test state membership in collections."""
        connecting_states = {ConnectionState.CONNECTING, ConnectionState.AUTHENTICATING}

        assert ConnectionState.CONNECTING in connecting_states
        assert ConnectionState.AUTHENTICATING in connecting_states
        assert ConnectionState.CONNECTED not in connecting_states
        assert ConnectionState.DISCONNECTED not in connecting_states

    def test_state_transitions_logic(self):
        """Test state transition logic is sound."""
        # Only CONNECTED state can send data
        data_sending_states = [
            state for state in ConnectionState if state.can_send_data
        ]
        assert data_sending_states == [ConnectionState.CONNECTED]

        # Only DISCONNECTED and ERROR states should retry
        retry_states = [state for state in ConnectionState if state.should_retry]
        assert set(retry_states) == {
            ConnectionState.DISCONNECTED,
            ConnectionState.ERROR,
        }

        # CONNECTING and AUTHENTICATING are both connecting states
        connecting_states = [state for state in ConnectionState if state.is_connecting]
        assert set(connecting_states) == {
            ConnectionState.CONNECTING,
            ConnectionState.AUTHENTICATING,
        }
