"""TEST-003/009: serial framing and cleanup using byte-stream fakes only."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from time import sleep

import pytest
import serial

from coherent_verdi import (
    ConnectionUnusable,
    ControllerConfig,
    Model,
    ResponseTimeout,
    SerialConfig,
    SerialTransport,
    TransportError,
    VerdiController,
    open_serial,
)


class FakeStream:
    def __init__(self, responses=(), *, partial=False, io_error=False, delay=0):
        self.responses = deque(responses)
        self.pending = bytearray()
        self.writes = []
        self.close_count = 0
        self.timeout = None
        self.write_timeout = None
        self.partial = partial
        self.io_error = io_error
        self.delay = delay

    def write(self, data):
        assert not self.pending, "overlapping requests consumed the wrong response"
        if self.io_error:
            raise OSError("fake cable loss")
        self.writes.append(data)
        self.pending.extend(self.responses.popleft() if self.responses else b"")
        return len(data) - int(self.partial)

    def read(self, size=1):
        if self.delay:
            sleep(self.delay)
        chunk = self.pending[:size]
        del self.pending[:size]
        return bytes(chunk)

    def close(self):
        self.close_count += 1


def transport(stream, **kwargs):
    return SerialTransport(stream, SerialConfig("FAKE-ONLY", **kwargs))


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


def test_fragmented_bytes_and_passive_lifecycle():
    stream = FakeStream([b"1.234\r\n"])
    t = transport(stream)
    assert not stream.writes
    assert t.exchange(b"?P\r\n") == b"1.234\r\n"
    assert stream.write_timeout == 1.0
    assert 0 < stream.timeout <= 1.0
    t.close()
    t.close()
    assert stream.close_count == 1
    assert stream.writes == [b"?P\r\n"]


@pytest.mark.parametrize("reply", [b"", b"1.2", b"1.2\r"])
def test_timeout_prevents_reusing_late_reply(reply):
    stream = FakeStream([reply, b"9.000\r\n"])
    t = transport(stream)
    with pytest.raises(ResponseTimeout):
        t.exchange(b"?P\r\n")
    with pytest.raises(ConnectionUnusable):
        t.exchange(b"?P\r\n")
    assert len(stream.writes) == 1


def test_total_deadline_not_reset_per_byte():
    stream = FakeStream([b"123456789.000\r\n"], delay=0.003)
    t = transport(stream, timeout_s=0.005)
    with pytest.raises(ResponseTimeout):
        t.exchange(b"?P\r\n")


def test_complete_reply_arriving_after_deadline_is_rejected(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("coherent_verdi.transport.monotonic", lambda: clock[0])

    class LateTerminator(FakeStream):
        def read(self, size=1):
            result = super().read(size)
            if result == b"\n":
                clock[0] = 0.02
            return result

    t = transport(LateTerminator([b"\r\n"]), timeout_s=0.01)
    with pytest.raises(ResponseTimeout):
        t.exchange(b"L=1\r\n")


@pytest.mark.parametrize("kwargs", [{"partial": True}, {"io_error": True}])
def test_write_failure_never_retried(kwargs):
    stream = FakeStream([b"\r\n"], **kwargs)
    t = transport(stream)
    with pytest.raises(TransportError):
        t.exchange(b"L=1\r\n")
    with pytest.raises(ConnectionUnusable):
        t.exchange(b"L=1\r\n")
    assert len(stream.writes) <= 1


def test_bounded_response_size():
    t = transport(FakeStream([b"X" * 100]), max_response_bytes=16)
    with pytest.raises(TransportError, match="byte limit"):
        t.exchange(b"?SV\r\n")


def test_interrupted_transaction_cannot_reuse_the_connection():
    class InterruptedStream(FakeStream):
        def read(self, size=1):
            raise KeyboardInterrupt

    stream = InterruptedStream([b"\r\n"])
    t = transport(stream)
    with pytest.raises(KeyboardInterrupt):
        t.exchange(b"L=1\r\n")
    with pytest.raises(ConnectionUnusable):
        t.exchange(b"?L\r\n")
    assert stream.writes == [b"L=1\r\n"]


def test_many_threads_share_serial_transactions():
    stream = FakeStream([b"1.234\r\n"] * 80, delay=0.00001)
    with VerdiController(transport(stream), ControllerConfig(Model.V5)) as controller:
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(lambda _: controller.power_w(), range(80))) == [1.234] * 80
    assert len(stream.writes) == 80


def test_physical_factory_disabled_before_import_or_open():
    with pytest.raises(PermissionError, match="physical access disabled"):
        open_serial(SerialConfig("FAKE-ONLY"))


def test_factory_configuration_without_hardware(monkeypatch):
    captured = {}

    class FakeSerial(FakeStream):
        def __init__(self, **kwargs):
            super().__init__()
            captured.update(kwargs)

        def open(self):
            captured["dtr"] = self.dtr
            captured["rts"] = self.rts
            captured["explicit_port"] = self.port

    monkeypatch.setattr(serial, "Serial", FakeSerial)
    t = open_serial(SerialConfig("FAKE-ONLY"), hardware_allowed=True)
    t.close()
    assert captured == {
        "port": None,
        "baudrate": 19200,
        "bytesize": 8,
        "parity": "N",
        "stopbits": 1,
        "timeout": 1.0,
        "write_timeout": 1.0,
        "xonxoff": False,
        "rtscts": False,
        "dsrdtr": False,
        "dtr": False,
        "rts": False,
        "explicit_port": "FAKE-ONLY",
    }


@pytest.mark.parametrize(
    "failure,cleanup_fails",
    [
        (OSError("fake open failure"), False),
        (KeyboardInterrupt("fake open interrupted"), False),
        (KeyboardInterrupt("fake open interrupted"), True),
    ],
)
def test_failed_open_closes_handle_and_preserves_primary_error(monkeypatch, failure, cleanup_fails):
    closed = []

    class FailingSerial:
        def __init__(self, **kwargs):
            pass

        def open(self):
            raise failure

        def close(self):
            closed.append(True)
            if cleanup_fails:
                raise OSError("fake cleanup failure")

    monkeypatch.setattr(serial, "Serial", FailingSerial)
    expected = TransportError if isinstance(failure, OSError) else KeyboardInterrupt
    with pytest.raises(
        expected, match="could not open" if isinstance(failure, OSError) else str(failure)
    ) as caught:
        open_serial(SerialConfig("FAKE-ONLY"), hardware_allowed=True)
    assert closed == [True]
    if cleanup_fails:
        assert "fake cleanup failure" in caught.value.__notes__[0]


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
    with pytest.raises(expected, match="close failed" if isinstance(failure, OSError) else None):
        controller.close()
    with pytest.raises(ConnectionUnusable):
        controller.power_w()
    with pytest.raises(ConnectionUnusable):
        transport.exchange(b"?P\r\n")
    controller.close()
    controller.close()
    assert stream.close_count == 2
