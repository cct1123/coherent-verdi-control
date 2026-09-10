"""Injected transport and an opt-in pySerial adapter. Never enumerates ports."""

from threading import RLock
from time import monotonic
from typing import Protocol

from .errors import ConnectionUnusable, ResponseTimeout, TransportError
from .models import SerialConfig


class Transport(Protocol):
    """One complete, bounded, serialized request/reply; close never sends commands."""

    @property
    def is_simulated(self) -> bool: ...

    def exchange(self, request: bytes) -> bytes: ...

    def close(self) -> None: ...


class ByteStream(Protocol):
    timeout: float | None
    write_timeout: float | None

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


class SerialTransport:
    """Owns an already-open byte stream; construct with a fake for hardware-free tests.

    A timeout, partial write or framing failure poisons the session. Late untagged
    replies cannot safely be assigned to another query. Replacing the transport is
    an explicit caller action; there is no automatic retry, flush or reconnect.
    """

    is_simulated = False

    def __init__(self, stream: ByteStream, config: SerialConfig) -> None:
        self._stream = stream
        self._config = config
        self._lock = RLock()
        self._closed = False
        self._failed = False

    def exchange(self, request: bytes) -> bytes:
        if not request.endswith(b"\r\n") or b"\r" in request[:-2] or b"\n" in request[:-2]:
            raise ValueError("request must contain one CR/LF-terminated instruction")
        with self._lock:
            if self._closed or self._failed:
                raise ConnectionUnusable("serial session is closed or desynchronized")
            try:
                deadline = monotonic() + self._config.timeout_s
                self._stream.write_timeout = self._config.timeout_s
                if self._stream.write(request) != len(request):
                    raise TransportError("partial write; command outcome is unknown")
                response = bytearray()
                while len(response) < self._config.max_response_bytes:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise ResponseTimeout(f"reply timed out after {len(response)} bytes")
                    self._stream.timeout = remaining
                    chunk = self._stream.read(1)
                    if not chunk or monotonic() > deadline:
                        raise ResponseTimeout(f"reply timed out after {len(response)} bytes")
                    response.extend(chunk)
                    if response.endswith(b"\r\n"):
                        return bytes(response)
                raise TransportError("reply exceeds configured byte limit")
            except BaseException as exc:
                # An interrupt or unexpected stream failure can also leave an
                # untagged reply pending. Preserve the exception, poison the session.
                self._failed = True
                if isinstance(exc, OSError):
                    raise TransportError(
                        f"serial I/O failed: {exc}; outcome may be unknown"
                    ) from exc
                raise

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self._stream.close()
                except OSError as exc:
                    raise TransportError(f"serial close failed: {exc}") from exc


def open_serial(config: SerialConfig, *, hardware_allowed: bool = False) -> SerialTransport:
    """For later approved physical validation only. No import/open unless opted in.

    This flag is an accident guard, not human authorization or a security boundary.
    Connection sends no Verdi instructions and performs no autodetection.
    """
    if hardware_allowed is not True:
        raise PermissionError("physical access disabled; use SimulatedTransport in this phase")
    import serial

    stream = serial.Serial(
        port=None,
        baudrate=config.baudrate,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=config.timeout_s,
        write_timeout=config.timeout_s,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    try:
        stream.dtr = False
        stream.rts = False
        stream.port = config.port
        stream.open()
    except (OSError, ValueError) as exc:
        stream.close()
        raise TransportError(f"could not open explicit serial connection: {exc}") from exc
    return SerialTransport(stream, config)
