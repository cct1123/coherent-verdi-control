"""Resource cleanup must remain retryable without permitting further device I/O."""

import pytest
import serial

from coherent_verdi import (
    ConnectionUnusable,
    ControllerConfig,
    Model,
    SerialConfig,
    SerialTransport,
    SimulatedTransport,
    TransportError,
    VerdiController,
    open_serial,
)


@pytest.mark.parametrize("failure", [OSError("fake close failure"), KeyboardInterrupt()])
def test_failed_close_disables_io_but_allows_cleanup_retry(failure):
    class ClosingStream:
        close_count = 0

        def close(self):
            self.close_count += 1
            if self.close_count == 1:
                raise failure

    stream = ClosingStream()
    transport = SerialTransport(stream, SerialConfig("FAKE-ONLY"))
    controller = VerdiController(transport, ControllerConfig(Model.V5))
    expected = TransportError if isinstance(failure, OSError) else KeyboardInterrupt
    with pytest.raises(expected):
        controller.close()
    with pytest.raises(ConnectionUnusable):
        controller.power_w()
    with pytest.raises(ConnectionUnusable):
        transport.exchange(b"?P\r\n")
    controller.close()
    controller.close()
    assert stream.close_count == 2


def test_failed_replacement_retains_caller_ownership_and_disables_old_session():
    class ClosingSimulator(SimulatedTransport):
        attempts = 0

        def close(self):
            self.attempts += 1
            if self.attempts == 1:
                raise TransportError("old session cleanup failed")
            super().close()

    old, fresh = ClosingSimulator(), SimulatedTransport()
    controller = VerdiController(old, ControllerConfig(Model.V5))
    with pytest.raises(TransportError):
        controller.replace_transport(fresh)
    with pytest.raises(ConnectionUnusable):
        controller.power_w()
    assert old.requests == fresh.requests == ()
    controller.replace_transport(fresh)
    assert fresh.requests == ()
    assert controller.power_w() == 0
    controller.close()


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_interrupted_open_closes_fake_handle_and_preserves_primary_error(
    monkeypatch, cleanup_fails
):
    closed = []

    class InterruptedOpen:
        def __init__(self, **kwargs):
            pass

        def open(self):
            raise KeyboardInterrupt("fake open interrupted")

        def close(self):
            closed.append(True)
            if cleanup_fails:
                raise OSError("fake cleanup failure")

    monkeypatch.setattr(serial, "Serial", InterruptedOpen)
    with pytest.raises(KeyboardInterrupt, match="fake open interrupted") as caught:
        open_serial(SerialConfig("FAKE-ONLY"), hardware_allowed=True)
    assert closed == [True]
    if cleanup_fails:
        assert "fake cleanup failure" in caught.value.__notes__[0]
