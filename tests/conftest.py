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
