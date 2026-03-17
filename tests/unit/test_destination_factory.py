"""Tests for DestinationFactory — registry-based destination creation.

Tests cover:
- Registration / unregistration
- create() — happy path, unknown type, builder failure
- create_all() — multiple configs, skip_disabled, empty list
- Enabled flag propagation
- Filter config wiring
- Edge cases
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any

import pytest

from sp_base_relay.config import (
    DestinationConfig,
    DestinationFilterConfig,
    SurePathDestinationConfig,
    NtripDestinationConfig,
    TcpServerDestinationConfig,
)
from sp_base_relay.core.destinations.base_destination import (
    BaseDestination,
    DEFAULT_QUEUE_SIZE,
)
from sp_base_relay.core.destinations.destination_factory import (
    DestinationFactory,
)
from sp_base_relay.core.message_filter import FilterConfig
from sp_base_relay.exceptions import ConfigurationError, DestinationError


# ============================================================================
# Fake destination for testing
# ============================================================================


class FakeDestination(BaseDestination):
    """Minimal concrete destination for factory tests."""

    def __init__(
        self,
        name: str,
        filter_config: FilterConfig,
        queue_size: int = DEFAULT_QUEUE_SIZE,
    ) -> None:
        super().__init__(name, "fake", filter_config, queue_size)
        self._mock_connected = False

    def _connect(self) -> None:
        self._mock_connected = True

    def _disconnect(self) -> None:
        self._mock_connected = False

    def _send_data(self, data: bytes) -> None:
        pass

    def _is_connected(self) -> bool:
        return self._mock_connected

    def get_connection_info(self) -> dict[str, Any]:
        return {"name": self.name}


def _fake_builder(cfg: DestinationConfig) -> BaseDestination:
    """Builder that creates a FakeDestination from config."""
    fc = cfg.filter.to_filter_config()
    return FakeDestination(name=cfg.name, filter_config=fc)


def _failing_builder(cfg: DestinationConfig) -> BaseDestination:
    """Builder that always raises."""
    raise RuntimeError("boom")


# ============================================================================
# Helpers — DestinationConfig construction
# ============================================================================


def _surepath_cfg(
    name: str = "sp",
    enabled: bool = True,
    filter_mode: str = "pass_all",
    filter_ids: list[int] | None = None,
) -> DestinationConfig:
    """Create a minimal SurePath DestinationConfig."""
    return DestinationConfig(
        name=name,
        type="surepath",
        enabled=enabled,
        filter=DestinationFilterConfig(
            mode=filter_mode,
            message_ids=filter_ids or [],
        ),
        config=SurePathDestinationConfig(
            host="example.com",
            port=50010,
            username="user",
            password="pass",
        ),
    )


def _ntrip_cfg(
    name: str = "ntrip1",
    enabled: bool = True,
) -> DestinationConfig:
    return DestinationConfig(
        name=name,
        type="ntrip",
        enabled=enabled,
        filter=DestinationFilterConfig(),
        config=NtripDestinationConfig(
            caster="rtk2go.com",
            port=2101,
            mountpoint="MOUNT",
            password="secret",
        ),
    )


def _tcp_cfg(
    name: str = "tcp1",
    enabled: bool = True,
) -> DestinationConfig:
    return DestinationConfig(
        name=name,
        type="tcp_server",
        enabled=enabled,
        filter=DestinationFilterConfig(),
        config=TcpServerDestinationConfig(port=5016),
    )


# ============================================================================
# Fixture — isolated registry per test
# ============================================================================


@pytest.fixture(autouse=True)
def _clean_registry() -> None:  # type: ignore[misc]
    """Ensure the registry is empty before and after every test."""
    saved = dict(DestinationFactory._builders)
    DestinationFactory._builders.clear()
    yield  # type: ignore[misc]
    DestinationFactory._builders.clear()
    DestinationFactory._builders.update(saved)


# ============================================================================
# Tests — Registration
# ============================================================================


class TestRegistration:
    """register / unregister / get_available_types / is_registered."""

    def test_register_adds_type(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        assert DestinationFactory.is_registered("surepath")

    def test_get_available_types(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        DestinationFactory.register("ntrip", _fake_builder)
        assert sorted(DestinationFactory.get_available_types()) == [
            "ntrip",
            "surepath",
        ]

    def test_unregister_removes_type(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        assert DestinationFactory.unregister("surepath") is True
        assert not DestinationFactory.is_registered("surepath")

    def test_unregister_nonexistent_returns_false(self) -> None:
        assert DestinationFactory.unregister("nope") is False

    def test_register_empty_type_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            DestinationFactory.register("", _fake_builder)

    def test_re_register_overwrites(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        DestinationFactory.register("surepath", _failing_builder)
        # Should now use the failing builder
        cfg = _surepath_cfg()
        with pytest.raises(DestinationError):
            DestinationFactory.create(cfg)

    def test_empty_registry(self) -> None:
        assert DestinationFactory.get_available_types() == []


# ============================================================================
# Tests — create()
# ============================================================================


class TestCreate:
    """DestinationFactory.create() tests."""

    def test_create_returns_destination(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        dest = DestinationFactory.create(_surepath_cfg())
        assert isinstance(dest, FakeDestination)
        assert dest.name == "sp"

    def test_create_sets_enabled_true(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        dest = DestinationFactory.create(_surepath_cfg(enabled=True))
        assert dest.enabled is True

    def test_create_sets_enabled_false(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        dest = DestinationFactory.create(_surepath_cfg(enabled=False))
        assert dest.enabled is False

    def test_create_wires_pass_all_filter(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        dest = DestinationFactory.create(_surepath_cfg())
        assert dest.message_filter.mode.value == "pass_all"

    def test_create_wires_allowlist_filter(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        cfg = _surepath_cfg(filter_mode="allowlist", filter_ids=[1005, 1077])
        dest = DestinationFactory.create(cfg)
        assert dest.message_filter.mode.value == "allowlist"
        assert dest.message_filter.should_pass(1005) is True
        assert dest.message_filter.should_pass(9999) is False

    def test_create_wires_blocklist_filter(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        cfg = _surepath_cfg(filter_mode="blocklist", filter_ids=[4072])
        dest = DestinationFactory.create(cfg)
        assert dest.message_filter.mode.value == "blocklist"
        assert dest.message_filter.should_pass(4072) is False
        assert dest.message_filter.should_pass(1005) is True

    def test_create_unknown_type_raises_configuration_error(self) -> None:
        cfg = _surepath_cfg()
        with pytest.raises(ConfigurationError, match="Unknown destination type"):
            DestinationFactory.create(cfg)

    def test_create_unknown_type_lists_available(self) -> None:
        DestinationFactory.register("ntrip", _fake_builder)
        cfg = _surepath_cfg()
        with pytest.raises(ConfigurationError, match="ntrip"):
            DestinationFactory.create(cfg)

    def test_create_builder_failure_raises_destination_error(self) -> None:
        DestinationFactory.register("surepath", _failing_builder)
        cfg = _surepath_cfg()
        with pytest.raises(DestinationError, match="boom"):
            DestinationFactory.create(cfg)

    def test_create_builder_configuration_error_passthrough(self) -> None:
        """ConfigurationError from builder passes through unwrapped."""

        def bad_config_builder(cfg: DestinationConfig) -> BaseDestination:
            raise ConfigurationError("bad config")

        DestinationFactory.register("surepath", bad_config_builder)
        with pytest.raises(ConfigurationError, match="bad config"):
            DestinationFactory.create(_surepath_cfg())


# ============================================================================
# Tests — create_all()
# ============================================================================


class TestCreateAll:
    """DestinationFactory.create_all() tests."""

    def test_create_all_multiple(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        DestinationFactory.register("ntrip", _fake_builder)
        configs = [_surepath_cfg(), _ntrip_cfg()]
        dests = DestinationFactory.create_all(configs)
        assert len(dests) == 2
        assert dests[0].name == "sp"
        assert dests[1].name == "ntrip1"

    def test_create_all_three_types(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        DestinationFactory.register("ntrip", _fake_builder)
        DestinationFactory.register("tcp_server", _fake_builder)
        configs = [_surepath_cfg(), _ntrip_cfg(), _tcp_cfg()]
        dests = DestinationFactory.create_all(configs)
        assert len(dests) == 3
        assert dests[2].name == "tcp1"

    def test_create_all_preserves_order(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        DestinationFactory.register("ntrip", _fake_builder)
        configs = [_ntrip_cfg(name="b"), _surepath_cfg(name="a")]
        dests = DestinationFactory.create_all(configs)
        assert [d.name for d in dests] == ["b", "a"]

    def test_create_all_includes_disabled_by_default(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        configs = [
            _surepath_cfg(name="a", enabled=True),
            _surepath_cfg(name="b", enabled=False),
        ]
        dests = DestinationFactory.create_all(configs)
        assert len(dests) == 2
        assert dests[1].enabled is False

    def test_create_all_skip_disabled(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        configs = [
            _surepath_cfg(name="a", enabled=True),
            _surepath_cfg(name="b", enabled=False),
        ]
        dests = DestinationFactory.create_all(configs, skip_disabled=True)
        assert len(dests) == 1
        assert dests[0].name == "a"

    def test_create_all_all_disabled_raises(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        configs = [_surepath_cfg(name="a", enabled=False)]
        with pytest.raises(ConfigurationError, match="No destinations to create"):
            DestinationFactory.create_all(configs, skip_disabled=True)

    def test_create_all_empty_list_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="At least one"):
            DestinationFactory.create_all([])

    def test_create_all_unknown_type_in_list_raises(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        configs = [_surepath_cfg(), _ntrip_cfg()]  # ntrip not registered
        with pytest.raises(ConfigurationError, match="Unknown destination type"):
            DestinationFactory.create_all(configs)


# ============================================================================
# Tests — get_type_info()
# ============================================================================


class TestGetTypeInfo:
    """get_type_info() diagnostic method."""

    def test_empty_registry(self) -> None:
        assert DestinationFactory.get_type_info() == {}

    def test_registered_types_listed(self) -> None:
        DestinationFactory.register("surepath", _fake_builder)
        info = DestinationFactory.get_type_info()
        assert "surepath" in info
        assert info["surepath"]["registered"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
