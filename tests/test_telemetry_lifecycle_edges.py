"""Application logging and configuration cannot undermine telemetry ownership."""

import asyncio
import importlib.util
import logging
from pathlib import Path
from threading import Event, get_ident

import pytest

from coherent_verdi import (
    ControllerConfig,
    Model,
    SimulatedTransport,
    TelemetryService,
    VerdiController,
)
from coherent_verdi.telemetry import logger


@pytest.mark.parametrize("attribute,value", [("controller", None), ("interval_s", -1)])
def test_service_configuration_cannot_be_reassigned(attribute, value):
    with VerdiController(SimulatedTransport(Model.V2), ControllerConfig(Model.V2)) as controller:
        service = TelemetryService(controller)
        with pytest.raises(AttributeError):
            setattr(service, attribute, value)
        assert service.controller is controller
        assert service.interval_s == 1
        assert service.poll_once().status.model == service.snapshot().model == Model.V2


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


def test_async_example_keeps_cleanup_with_inflight_worker_on_cancellation(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "examples" / "async_integration.py"
    spec = importlib.util.spec_from_file_location("verdi_async_example", source)
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    entered, release, closed = Event(), Event(), Event()
    threads = []

    class FakeController:
        def __init__(self, *args):
            pass

        def __enter__(self):
            threads.append(get_ident())
            return self

        def status(self):
            threads.append(get_ident())
            entered.set()
            assert release.wait(3)
            return object()

        def diagnostics(self):
            return object()

        def __exit__(self, *args):
            threads.append(get_ident())
            closed.set()

    monkeypatch.setattr(example, "VerdiController", FakeController)

    async def scenario():
        task = asyncio.create_task(example.main())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not closed.is_set(), "cleanup overtook the unfinished worker operation"
        finally:
            release.set()
            assert await asyncio.to_thread(closed.wait, 2)

    asyncio.run(scenario())
    assert len(threads) == 3 and len(set(threads)) == 1
    assert threads[0] != get_ident()
