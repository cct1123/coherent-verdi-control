"""Focused validation of resource failures, invalid configuration and long fake runs."""

import pytest
import serial

from coherent_verdi import (
    ControllerConfig,
    DeviceError,
    Model,
    SerialConfig,
    SerialTransport,
    SimulatedTransport,
    TelemetryService,
    TransportError,
    VerdiController,
    open_serial,
)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"port": ""},
        {"port": "loop://"},
        {"port": "FAKE", "baudrate": 19200.0},
        {"port": "FAKE", "baudrate": 115200},
        {"port": "FAKE", "timeout_s": float("inf")},
        {"port": "FAKE", "max_response_bytes": True},
    ],
)
def test_serial_configuration_rejects_unsupported_values(kwargs):
    with pytest.raises(ValueError):
        SerialConfig(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "V5"},
        {"model": Model.V5, "allow_writes": "yes"},
        {"model": Model.V2, "power_limit_w": 3},
    ],
)
def test_controller_config_is_runtime_validated(kwargs):
    with pytest.raises(ValueError):
        ControllerConfig(**kwargs)


def test_failed_open_closes_fake_handle(monkeypatch):
    closed = []

    class FailingSerial:
        def __init__(self, **kwargs):
            pass

        def open(self):
            raise OSError("injected opening failure")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(serial, "Serial", FailingSerial)
    with pytest.raises(TransportError, match="could not open"):
        open_serial(SerialConfig("FAKE"), hardware_allowed=True)
    assert closed == [True]


def test_close_failure_is_not_suppressed():
    class BrokenClose:
        def close(self):
            raise OSError("injected close failure")

    t = SerialTransport(BrokenClose(), SerialConfig("FAKE"))
    with pytest.raises(TransportError, match="close failed"):
        t.close()


def test_long_simulated_telemetry_run_is_bounded():
    sim = SimulatedTransport()
    with VerdiController(sim, ControllerConfig(Model.V5)) as c:
        service = TelemetryService(c, history_size=17)
        for _ in range(1000):
            assert service.poll_once().error is None
        assert len(service.history) == 17
        assert service.history[-1].sequence == 1000
        assert service.history[0].sequence == 984
        assert len(sim.requests) == 4096


def test_device_rejection_leaves_complete_session_usable():
    sim = SimulatedTransport()
    with VerdiController(sim, ControllerConfig(Model.V5, allow_writes=True)) as c:
        sim.inject(b"RANGE ERROR: P=1.0000\r\n")
        with pytest.raises(DeviceError):
            c.set_power_w(1)
        assert c.power_w() == 0
