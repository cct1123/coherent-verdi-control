"""Every test is hardware-free, including serial adapter tests."""

import pytest
import serial
import serial.tools.list_ports


@pytest.fixture(autouse=True)
def prohibit_physical_hardware(monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError("physical serial access/discovery prohibited in hardware-free tests")

    monkeypatch.setattr(serial, "Serial", prohibited)
    monkeypatch.setattr(serial, "serial_for_url", prohibited)
    monkeypatch.setattr(serial.tools.list_ports, "comports", prohibited)
    monkeypatch.setattr(serial.tools.list_ports, "grep", prohibited)


@pytest.fixture
def callback_payload():
    """Build the real Dash callback request shared by client integration tests."""

    def build(app):
        key = next(iter(app.callback_map))
        return {
            "output": key,
            "outputs": [
                {"id": output.component_id, "property": output.component_property}
                for output in app.callback_map[key]["output"]
            ],
            "inputs": [{"id": "refresh", "property": "n_intervals", "value": 1}],
            "changedPropIds": ["refresh.n_intervals"],
            "state": [],
        }

    return build
