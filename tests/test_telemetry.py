"""TEST-005: bounded acquisition, immutable configuration and worker lifecycle."""

import logging
from threading import Event

import pytest

from coherent_verdi import (
    ControllerConfig,
    Model,
    SimulatedTransport,
    TelemetryService,
    VerdiController,
)
from coherent_verdi.telemetry import logger


@pytest.mark.parametrize(
    "kwargs",
    [{"interval_s": 0}, {"interval_s": float("nan")}, {"history_size": 0}, {"history_size": True}],
)
def test_invalid_service_configuration(kwargs):
    with VerdiController(SimulatedTransport(), ControllerConfig(Model.V5)) as controller:
        with pytest.raises(ValueError):
            TelemetryService(controller, **kwargs)


@pytest.mark.parametrize("attribute,value", [("controller", None), ("interval_s", -1)])
def test_service_configuration_cannot_be_reassigned(attribute, value):
    with VerdiController(SimulatedTransport(Model.V2), ControllerConfig(Model.V2)) as controller:
        service = TelemetryService(controller)
        with pytest.raises(AttributeError):
            setattr(service, attribute, value)
        assert service.controller is controller
        assert service.interval_s == 1
        assert service.poll_once().status.model == service.snapshot().model == Model.V2


def test_programming_errors_are_visible_in_background_sample(monkeypatch):
    c = VerdiController(SimulatedTransport(), ControllerConfig(Model.V5))
    service = TelemetryService(c)

    def broken():
        raise RuntimeError("injected application bug")

    monkeypatch.setattr(c, "status", broken)
    assert service.poll_once().error_type == "RuntimeError"


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


def test_start_stop_idempotent_restart_and_controller_ownership(monkeypatch):
    c = VerdiController(SimulatedTransport(), ControllerConfig(Model.V5))
    service = TelemetryService(c, interval_s=0.01)
    observed = Event()
    real_status = c.status

    def record_status():
        result = real_status()
        observed.set()
        return result

    monkeypatch.setattr(c, "status", record_status)
    assert not service.running
    service.start()
    service.start()
    assert observed.wait(2)
    service.stop()
    service.stop()
    assert not service.running
    assert c.power_w() == 0.0  # service does not own/close controller
    observed.clear()
    service.start()
    assert observed.wait(2)
    service.stop()
    c.close()


def test_stop_timeout_does_not_claim_worker_stopped(monkeypatch):
    c = VerdiController(SimulatedTransport(), ControllerConfig(Model.V5))
    service = TelemetryService(c)
    entered, release = Event(), Event()
    original = c.status

    def delayed():
        entered.set()
        assert release.wait(2)
        return original()

    monkeypatch.setattr(c, "status", delayed)
    service.start()
    try:
        assert entered.wait(2)
        with pytest.raises(TimeoutError, match="still sampling"):
            service.stop(timeout_s=0.001)
        assert service.running
    finally:
        release.set()
        service.stop()


def test_failing_logging_sink_sees_published_errors_and_cannot_break_sampling():
    with VerdiController(SimulatedTransport(), ControllerConfig(Model.V5)) as controller:
        service = TelemetryService(controller)
        controller.close()
        observed = []

        class FailingHandler(logging.Handler):
            def emit(self, record):
                observed.append(service.snapshot().history[-1].sequence)
                raise OSError("simulated logging sink failure")

        handler = FailingHandler()
        logger.addHandler(handler)
        try:
            for sequence in (1, 2):
                sample = service.poll_once()
                assert sample.sequence == sequence
                assert sample.status is None
                assert sample.error_type == "ConnectionUnusable"
        finally:
            logger.removeHandler(handler)
        assert observed == [1, 2]


def test_logging_handler_can_inspect_lifecycle_during_stop():
    with VerdiController(SimulatedTransport(), ControllerConfig(Model.V5)) as controller:
        service = TelemetryService(controller)
        controller.close()
        entered = Event()
        observed = []

        class InspectingHandler(logging.Handler):
            def emit(self, record):
                entered.set()
                # Synchronize against the actual stop request, without a timing race.
                assert service._stop.wait(2)
                observed.append(service.running)
                observed.append(service.snapshot().history[-1].error_type)

        handler = InspectingHandler()
        logger.addHandler(handler)
        service.start()
        try:
            assert entered.wait(2)
            service.stop(timeout_s=1)
        finally:
            logger.removeHandler(handler)
            service.stop()
        assert observed == [True, "ConnectionUnusable"]
        assert not service.running
