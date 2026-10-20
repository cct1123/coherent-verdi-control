"""Synchronous Verdi driver: explicit serial lifecycle, manual protocol, plain results."""

import re
from collections.abc import Callable
from datetime import UTC, datetime
from math import isfinite
from threading import RLock
from time import monotonic
from types import TracebackType
from typing import Any, Self, cast


class VerdiError(Exception):
    """Communication or reply failure. Retire the session; never replay a command."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.instruction: str | None = None
        self.request = b""
        self.raw_response = b""
        self.duration_s: float | None = None
        self.write_outcome: str | None = None


class DeviceError(VerdiError):
    """Complete documented device rejection; the connection remains usable."""

    def __init__(self, instruction: str, response: str) -> None:
        super().__init__(f"{instruction}: {response}")
        self.instruction = instruction
        self.response = response


BAUDRATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600)


def finite_range(value: float, low: float, high: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
    if not low <= value <= high or not isfinite(value):
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
    return float(value)


_TEXT = {
    "?ACAD",
    "?D1PC",
    "?D1RCF",
    "?D1TD",
    "?D15V",
    "?ED",
    "?LBOD",
    "?SV",
    "?VD",
}
_CODES = {
    "?B": BAUDRATES,
    "?D1SS": range(7),
    "?LBOSS": range(7),
    "?ESS": range(4),
    "?LRS": range(4),
    "?VSS": range(4),
    "?L": range(3),
    "?DIOS": range(2),
    "?K": range(2),
    "?LBOH": range(2),
    "?LBOOS": range(2),
    "?M": range(2),
    "?S": range(2),
}
_NONNEGATIVE = {
    "?C",
    "?D1C",
    "?D1H",
    "?D1RCM",
    "?HH",
    "?P",
    "?PSH",
    "?SP",
}

QUERIES = frozenset(
    _TEXT
    | _CODES.keys()
    | _NONNEGATIVE
    | {
        "?BT",
        "?D1HST",
        "?D1ST",
        "?D1T",
        "?EST",
        "?ET",
        "?LBOST",
        "?LBOT",
        "?VST",
        "?VT",
        "?F",
        "?FH",
    }
)

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")


def encode_instruction(instruction: str) -> bytes:
    if not instruction or len(instruction) > 128:
        raise ValueError("instruction must contain 1..128 printable ASCII characters")
    if any(not 32 <= ord(c) <= 126 or c == ";" for c in instruction):
        raise ValueError("only one printable ASCII instruction is allowed")
    return instruction.encode("ascii") + b"\r\n"


def decode_response(
    instruction: str, wire: bytes, *, query: bool, allow_empty: bool = False
) -> str:
    """Accept the four single-line echo/prompt layouts in Table 5-1.

    Extra lines are errors, not discarded data; this prevents silent reply mixing.
    """
    if not wire.endswith(b"\r\n") or b"\r" in wire[:-2] or b"\n" in wire[:-2]:
        raise VerdiError(f"{instruction}: expected exactly one CR/LF-terminated reply")
    try:
        payload = wire[:-2].decode("ascii")
    except UnicodeDecodeError as exc:
        raise VerdiError(f"{instruction}: non-ASCII reply") from exc
    if any(not 32 <= ord(c) <= 126 for c in payload):
        raise VerdiError(f"{instruction}: control character in reply")
    payload = payload.strip(" ")
    if payload.startswith("Verdi>"):
        payload = payload[len("Verdi>") :].lstrip()
    # Echo uses the instruction exactly as transmitted (Table 5-1).
    if payload.startswith(instruction):
        payload = payload[len(instruction) :].lstrip()
    if payload.startswith(("RANGE ERROR:", "Command Error:", "Query Error:")):
        raise DeviceError(instruction, payload)
    if query and not payload and not allow_empty:
        raise VerdiError(f"{instruction}: empty query response")
    if not query and payload:
        raise VerdiError(f"{instruction}: unexpected command acknowledgment {payload!r}")
    return payload


def parse_faults(payload: str, *, clear_reply: str | None = "SYSTEM OK") -> list[int]:
    # The default clear text is documented for history only (Table 5-4).
    if payload == clear_reply:
        return []
    if not re.fullmatch(r"[1-9][0-9]*(?:\s*&\s*[1-9][0-9]*)*", payload):
        raise VerdiError(f"invalid fault list {payload!r}")
    return [_parse_integer(part) for part in payload.split("&")]


def _parse_integer(payload: str) -> int:
    try:
        return int(payload)
    except ValueError as exc:
        # Python bounds decimal conversion independently of the configured wire
        # response limit. Malformed/unrepresentable data must still invalidate
        # the controller session through the normal VerdiError path.
        raise VerdiError("integer reply exceeds the supported conversion limit") from exc


def parse_value(
    query: str, payload: str, *, active_fault_clear_reply: str | None = None
) -> float | int | str | list[int]:
    if query in ("?F", "?FH"):
        return parse_faults(
            payload, clear_reply=active_fault_clear_reply if query == "?F" else "SYSTEM OK"
        )
    if query in _TEXT:
        return payload
    if query in _CODES:
        if not re.fullmatch(r"[0-9]+", payload):
            raise VerdiError(f"{query}: undocumented value {payload!r}")
        integer_value = _parse_integer(payload)
        if integer_value not in _CODES[query]:
            raise VerdiError(f"{query}: undocumented value {payload!r}")
        return integer_value
    if not _NUMBER.fullmatch(payload):
        raise VerdiError(f"{query}: expected decimal number, received {payload!r}")
    value = float(payload)
    if not isfinite(value) or (query in _NONNEGATIVE and value < 0):
        raise VerdiError(f"{query}: invalid numeric value {payload!r}")
    return value


class VerdiController:
    """One controller per connection. Construction sends nothing; connect is passive.

    Pass an explicit native port. Use SimulatedVerdi for hardware-free development.
    A context manager connects and disconnects; neither changes laser state.
    """

    def __init__(
        self,
        port: str,
        *,
        model: str = "V5",
        baudrate: int = 19200,
        timeout_s: float = 1.0,
        allow_writes: bool = False,
        power_limit_w: float | None = None,
        active_fault_clear_reply: str | None = None,
        trace: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        if model not in ("V2", "V5", "V6"):
            raise ValueError("model must be V2, V5 or V6")
        self._model = model
        if type(allow_writes) is not bool:
            raise ValueError("allow_writes must be a bool")
        self._allow_writes = allow_writes
        self._power_limit_w = (
            float(model[1:])
            if power_limit_w is None
            else finite_range(power_limit_w, 0, float(model[1:]), "power_limit_w")
        )
        reply = active_fault_clear_reply
        if reply is not None and (
            not isinstance(reply, str)
            or not 1 <= len(reply) <= 128
            or reply != reply.strip(" ")
            or any(not 32 <= ord(c) <= 126 or c == "&" for c in reply)
            or (reply.isdecimal() and int(reply) > 0)
        ):
            raise ValueError(
                "active_fault_clear_reply must be verified ASCII text or 0, not a fault code"
            )
        self._active_fault_clear_reply = reply
        if trace is not None and not callable(trace):
            raise ValueError("trace must be a callable or None")
        self._trace = trace
        self._tracing = False
        if not isinstance(port, str) or not port.strip() or "://" in port:
            raise ValueError("an explicit native port name is required; no discovery or URLs")
        if type(baudrate) is not int or baudrate not in BAUDRATES:
            raise ValueError("baudrate is not listed in manual Table 5-2")
        self._port = port
        self._baudrate = baudrate
        self._timeout_s = finite_range(timeout_s, 0.001, 60.0, "timeout_s")
        self._stream: Any = None
        self._connected = False
        self._failed = False
        self._lock = RLock()

    @property
    def model(self) -> str:
        return self._model

    is_simulated = False

    def connect(self) -> None:
        """Open without discovery, queries, flushing or configuration commands.

        After uncertain I/O, retire this controller. Establish a clean physical
        session before constructing another; reopening alone cannot prove that.
        """
        with self._lock:
            if self._tracing:
                raise RuntimeError("trace callbacks cannot open or close the connection")
            if self._failed:
                raise VerdiError(
                    "failed session; establish a clean connection and use a new controller"
                )
            if not self._connected:
                try:
                    self._open()
                except BaseException:
                    self._failed = True
                    raise
                self._connected = True

    def disconnect(self) -> None:
        """Release the connection, sending no commands. This does not stop the laser.

        Failed cleanup can be retried. A failed session never becomes reusable.
        """
        with self._lock:
            if self._tracing:
                raise RuntimeError("trace callbacks cannot open or close the connection")
            self._connected = False
            try:
                self._close()
            except BaseException:
                self._failed = True
                raise

    def _request(
        self, instruction: str, *, query: bool = False, capture: bool = False
    ) -> float | int | str | list[int] | dict[str, Any]:
        if self._tracing:
            raise RuntimeError("trace callbacks cannot issue device instructions")
        if not self._connected or self._failed:
            error = VerdiError(
                "controller is disconnected or failed; after a failure use a new session"
            )
            error.instruction = instruction
            error.write_outcome = None if query else "not_sent"
            raise error
        request = encode_instruction(instruction)
        started = monotonic()
        record: dict[str, Any] = {
            "instruction": instruction,
            "request": request,
            "response": b"",
            "payload": None,
            "timestamp_utc": datetime.now(UTC).isoformat(),
            "duration_s": 0.0,
            "port": self._port,
            "model": self.model,
            "baudrate": self._baudrate,
            "timeout_s": self._timeout_s,
            "simulated": self.is_simulated,
            "write_attempted": True,
            "pending_bytes": 0,
            "outcome": "failed" if query else "unknown",
            "error": None,
        }
        failure: BaseException | None = None
        try:
            record["response"] = self._exchange(request)
            payload = decode_response(
                instruction,
                record["response"],
                query=query,
                allow_empty=capture,
            )
            record["payload"] = payload
            if capture:
                record["outcome"] = "captured"
                return record
            if not query:
                record["outcome"] = "acknowledged"
                return payload
            value = parse_value(
                instruction, payload, active_fault_clear_reply=self._active_fault_clear_reply
            )
            if instruction in ("?D1SS", "?LBOSS") and (
                (self.model == "V6" and value == 5) or (self.model == "V2" and value == 6)
            ):
                raise VerdiError(
                    f"{instruction}: servo code {value} is not documented for {self.model}"
                )
            record["outcome"] = "ok"
            return value
        except BaseException as exc:
            failure = exc
            if not record["response"]:
                record["response"] = getattr(exc, "raw_response", b"")
            record["write_attempted"] = getattr(exc, "write_attempted", True)
            record["pending_bytes"] = getattr(exc, "pending_bytes", 0)
            record["error"] = f"{type(exc).__name__}: {exc}"
            if isinstance(exc, DeviceError):
                record["outcome"] = "rejected"
            else:
                self._failed = True
                record["outcome"] = "failed"
                if not query:
                    record["outcome"] = "unknown" if record["write_attempted"] else "not_sent"
            raise
        finally:
            record["duration_s"] = monotonic() - started
            if isinstance(failure, VerdiError):
                self._error_context(failure, record)
            if self._trace is not None:
                self._tracing = True
                try:
                    self._trace(dict(record))
                except BaseException as trace_error:
                    self._failed = True
                    if failure is not None:
                        failure.add_note(f"transaction trace failed: {trace_error}")
                    elif isinstance(trace_error, Exception):
                        error = VerdiError(f"transaction trace failed: {trace_error}")
                        self._error_context(error, record)
                        raise error from trace_error
                    else:
                        raise
                finally:
                    self._tracing = False

    @staticmethod
    def _error_context(error: VerdiError, record: dict[str, Any]) -> None:
        error.instruction = record["instruction"]
        error.request = record["request"]
        error.raw_response = record["response"]
        error.duration_s = record["duration_s"]
        error.write_outcome = None if record["instruction"].startswith("?") else record["outcome"]

    def read(self, query: str) -> float | int | str | list[int]:
        """Read one documented short query; unknown strings never reach the wire."""
        if not isinstance(query, str) or query not in QUERIES:
            raise ValueError(f"unknown query: {query!r}")
        with self._lock:
            return cast(float | int | str | list[int], self._request(query, query=True))

    def capture(self, query: str) -> dict[str, Any]:
        """Capture a documented query without interpreting its value; read-only sessions only.

        Framing and device errors are still enforced. Empty payloads are evidence,
        never an assertion that the instrument is clear or ready.
        """
        if not isinstance(query, str) or query not in QUERIES:
            raise ValueError(f"unknown query: {query!r}")
        with self._lock:
            if self._allow_writes:
                raise PermissionError("capture requires a read-only controller")
            return cast(dict[str, Any], self._request(query, query=True, capture=True))

    def read_faults(self, *, history: bool = False) -> list[int]:
        if type(history) is not bool:
            raise ValueError("history must be a bool")
        return cast(list[int], self.read("?FH" if history else "?F"))

    def read_power_w(self) -> float:
        return cast(float, self.read("?P"))

    def read_laser_state(self) -> int:
        """Manual codes: 0 standby, 1 on, 2 fault."""
        return cast(int, self.read("?L"))

    def status(self) -> dict[str, Any]:
        """JSON-ready dictionary from 14 sequential reads, serialized against writes."""
        with self._lock:
            started = monotonic()
            sample = {
                "model": self.model,
                "sampled_at": datetime.now(UTC).isoformat(),
                "simulated": self.is_simulated,
                "laser_state": self.read_laser_state(),
                "keyswitch_on": bool(self.read("?K")),
                "shutter_open": bool(self.read("?S")),
                "power_w": self.read_power_w(),
                "set_power_w": self.read("?SP"),
                "diode_current_a": self.read("?D1C"),
                "diode_temp_c": self.read("?D1T"),
                "heatsink_temp_c": self.read("?D1HST"),
                "baseplate_temp_c": self.read("?BT"),
                "lbo_temp_c": self.read("?LBOT"),
                "lbo_servo": self.read("?LBOSS"),
                "etalon_temp_c": self.read("?ET"),
                "vanadate_temp_c": self.read("?VT"),
                "faults": self.read_faults(),
            }
            sample["duration_s"] = monotonic() - started
            return sample

    def read_diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {
                "software_version": self.read("?SV"),
                "head_hours": self.read("?HH"),
                "power_supply_hours": self.read("?PSH"),
                "diode_hours": self.read("?D1H"),
                "fault_history": self.read_faults(history=True),
            }

    def _command(self, instruction: str) -> None:
        with self._lock:
            if not self._allow_writes:
                raise PermissionError("writes disabled; pass allow_writes=True explicitly")
            self._request(instruction)

    def set_power_w(self, power_w: float) -> None:
        """Set light regulation, rounded to four decimals; no implicit laser enable."""
        value = finite_range(power_w, 0, self._power_limit_w, "power_w")
        # Check the serialized value too: rounding must not exceed a site ceiling.
        encoded = f"{value:.4f}"
        if float(encoded) > self._power_limit_w:
            raise ValueError("rounded setpoint exceeds power_limit_w")
        self._command(f"P={encoded}")

    def stop(self) -> None:
        """LASER=0 overrides an ON keyswitch (Table 5-3)."""
        self._command("L=0")

    def start(self) -> None:
        """LASER=1 also resets faults and clears fault history. Explicit action only.

        The hardware keyswitch must be ON. This API is not an interlock or a
        substitute for an approved beam path and laboratory operating procedure.
        """
        self._command("L=1")

    def set_shutter(self, *, open: bool) -> None:
        """Operate the Verdi safety shutter; never use as an experiment modulator."""
        if type(open) is not bool:
            raise ValueError("open must be a bool")
        self._command(f"S={int(open)}")

    def set_echo(self, *, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a bool")
        self._command(f"E={int(enabled)}")

    def set_prompt(self, *, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("enabled must be a bool")
        self._command(f"PROMPT={int(not enabled)}")

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        try:
            self.disconnect()
        except BaseException as cleanup_error:
            if exc is None:
                raise
            exc.add_note(f"disconnect also failed: {cleanup_error}")

    def _open(self) -> None:
        if self._stream is not None:
            return
        import serial

        stream = serial.Serial(
            port=None,
            baudrate=self._baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=self._timeout_s,
            write_timeout=self._timeout_s,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        # Retain the handle even when open/cleanup fails, so disconnect can be retried.
        self._stream = stream
        try:
            stream.dtr = False
            stream.rts = False
            stream.port = self._port
            stream.open()
        except BaseException as exc:
            try:
                self._close()
            except BaseException as cleanup_error:
                exc.add_note(f"serial cleanup also failed: {cleanup_error}")
            if isinstance(exc, (OSError, ValueError)):
                raise VerdiError(f"could not open serial connection: {exc}") from exc
            raise

    def _exchange(self, request: bytes) -> bytes:
        if self._stream is None:
            raise VerdiError("serial connection is not open")
        response = bytearray()
        write_attempted = False
        pending_bytes = 0
        try:
            pending_bytes = self._stream.in_waiting
            if pending_bytes:
                raise VerdiError(f"unexpected buffered input before request: {pending_bytes} bytes")
            deadline = monotonic() + self._timeout_s
            self._stream.write_timeout = self._timeout_s
            write_attempted = True
            if self._stream.write(request) != len(request):
                raise VerdiError("partial write; command outcome is unknown")
            while len(response) < 4096:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise VerdiError(f"reply timed out after {len(response)} bytes")
                self._stream.timeout = remaining
                chunk = self._stream.read(1)
                response.extend(chunk)
                if not chunk or monotonic() > deadline:
                    raise VerdiError(f"reply timed out after {len(response)} bytes")
                if response.endswith(b"\r\n"):
                    pending_bytes = self._stream.in_waiting
                    if pending_bytes:
                        raise VerdiError(
                            f"unexpected trailing input after reply: {pending_bytes} bytes"
                        )
                    return bytes(response)
            raise VerdiError("reply exceeds 4096 byte limit")
        except BaseException as exc:
            failure = (
                VerdiError(f"serial I/O failed: {exc}; outcome may be unknown")
                if isinstance(exc, OSError)
                else exc
            )
            failure.__dict__.update(
                raw_response=bytes(response),
                write_attempted=write_attempted,
                pending_bytes=pending_bytes,
            )
            if failure is exc:
                raise
            raise failure from exc

    def _close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError as exc:
                raise VerdiError(f"serial close failed: {exc}") from exc
            self._stream = None
