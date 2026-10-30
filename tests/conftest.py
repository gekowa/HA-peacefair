"""Use a real HA test instance with only the external meter replaced."""

from pathlib import Path
from threading import get_ident

import pytest


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations, socket_enabled, monkeypatch):
    """Allow the custom integration and loopback protocol tests."""
    import custom_components

    monkeypatch.setattr(custom_components, "__path__", [
        str(Path(__file__).parents[1] / "custom_components")
    ])


@pytest.fixture
def meter(monkeypatch):
    from custom_components.peacefair.pzwifi import PzSensorResult

    event_loop_thread = get_ident()

    def read(host, port):
        assert get_ident() != event_loop_thread, "TCP must run outside the event loop"
        assert host and 1 <= port <= 65535
        return PzSensorResult(230, 1.234, 283.8, 123.456, 50, 0.95)

    class Meter:
        # A plain callable uses HA's real executor; its test helpers execute
        # unittest.mock objects inline instead.
        side_effect = staticmethod(read)

        def __call__(self, host, port):
            if isinstance(self.side_effect, Exception):
                raise self.side_effect
            return self.side_effect(host, port)

    fake = Meter()
    monkeypatch.setattr("custom_components.peacefair.pzwifi.poll", fake)
    return fake
