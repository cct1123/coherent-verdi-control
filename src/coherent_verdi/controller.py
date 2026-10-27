"""Synchronous Verdi driver: explicit serial lifecycle, manual protocol, plain results.

The catalogues below describe the protocol; they never open a port or send an
instruction. Add documented entries there, then independent simulator behavior
and tests.
"""

import os
import re
from datetime import UTC, datetime
from math import isfinite, ulp
from threading import RLock
from time import monotonic
from types import TracebackType
from typing import Any, NamedTuple, Self, cast
from weakref import WeakValueDictionary

BAUDRATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600)
_PORT_LOCK = RLock()
_PORT_OWNERS: WeakValueDictionary[str, "VerdiController"] = WeakValueDictionary()
# Observed before the first ?K reply after physical key ON (V2 firmware 6.05).
_KEY_ON_NOTICE = b"min current set\r\n"
# Seen before the power reply in lesson 07 (V2 firmware 6.05).
_LEVEL0_NOTICE = b"level0 set!\r\n"
_STATUS_NOTICES = (_KEY_ON_NOTICE, b"level1 set!\r\n", _LEVEL0_NOTICE)
_MAX_STATUS_NOTICES = 8  # Software bound, in addition to the 4096-byte response ceiling.


class Query(NamedTuple):
    """One Table 5-4 entry. Code labels bound valid integers, not physical readiness."""

    name: str
    unit: str
    kind: str = "number"  # number, nonnegative, text, faults, baud or code
    labels: tuple[str, ...] = ()


_SERVO = ("OPEN", "LOCKED", "SEEKING", "FAULT", "OPTIMIZING", "CPEAKING", "CPEAKING2")
_AVAILABLE = ("UNAVAILABLE", "AVAILABLE")
QUERY_INFO = {
    "?ACAD": Query("AVG CURRENT AND DELTA", "raw", "text"),
    "?BT": Query("BASEPLATE TEMP", "°C"),
    "?B": Query("BAUD RATE", "baud", "baud"),
    "?C": Query("CURRENT", "A", "nonnegative"),
    "?D1C": Query("DIODE1 CURRENT", "A", "nonnegative"),
    "?D1HST": Query("DIODE1 HEATSINK TEMP", "°C"),
    "?D1H": Query("DIODE1 HOURS", "h", "nonnegative"),
    "?D1PC": Query("DIODE1 PHOTOCELL", "raw", "text"),
    "?D1RCF": Query("DIODE1 RATED CURRENT FACTOR", "raw", "text"),
    "?D1RCM": Query("DIODE1 RATED CURRENT MAX", "A", "nonnegative"),
    "?D1SS": Query("DIODE1 SERVO STATUS", "code", "code", _SERVO),
    "?D1ST": Query("DIODE1 SET TEMP", "°C"),
    "?D1TD": Query("DIODE1 TEMP DRIVE", "raw", "text"),
    "?D1T": Query("DIODE1 TEMP", "°C"),
    "?D15V": Query("DIODE1 5VREF SENSE", "raw", "text"),
    "?DIOS": Query("DIODE OPTIMIZER STATUS", "code", "code", _AVAILABLE),
    "?ED": Query("ETALON DRIVE", "raw", "text"),
    "?ESS": Query("ETALON SERVO STATUS", "code", "code", _SERVO[:4]),
    "?EST": Query("ETALON SET TEMP", "°C"),
    "?ET": Query("ETALON TEMP", "°C"),
    "?F": Query("FAULTS", "codes", "faults"),
    "?FH": Query("FAULT HISTORY", "codes", "faults"),
    "?HH": Query("HEAD_HOURS", "h", "nonnegative"),
    "?K": Query("KEYSWITCH", "code", "code", ("OFF", "ON")),
    "?L": Query("LASER", "code", "code", ("STANDBY", "ON", "FAULT")),
    "?LBOD": Query("LBO DRIVE", "raw", "text"),
    "?LBOH": Query("LBO HEATER", "code", "code", ("COOL DOWN", "HEATING")),
    "?LBOOS": Query("LBO OPTIMIZER STATUS", "code", "code", _AVAILABLE),
    "?LBOST": Query("LBO SET TEMP", "°C"),
    "?LBOSS": Query("LBO SERVO STATUS", "code", "code", _SERVO),
    "?LBOT": Query("LBO TEMP", "°C"),
    "?P": Query("LIGHT", "W", "nonnegative"),
    "?LRS": Query("LIGHT REG STATUS", "code", "code", _SERVO[:4]),
    "?M": Query("MODE", "code", "code", ("CURRENT", "LIGHT")),
    "?PSH": Query("PS HOURS", "h", "nonnegative"),
    "?SP": Query("SET LIGHT", "W", "nonnegative"),
    "?S": Query("SHUTTER", "code", "code", ("CLOSED", "OPEN")),
    "?SV": Query("SOFTWARE", "text", "text"),
    "?VST": Query("VANADATE SET TEMP", "°C"),
    "?VT": Query("VANADATE TEMP", "°C"),
    "?VD": Query("VANADATE DRIVE", "raw", "text"),
    "?VSS": Query("VANADATE SERVO STATUS", "code", "code", _SERVO[:4]),
}
QUERIES = frozenset(QUERY_INFO)
QUERY_NAMES = {spec.name: query for query, spec in QUERY_INFO.items()}


class Command(NamedTuple):
    """One Table 5-3 write. Labels describe binary operands, not readback."""

    name: str
    unit: str
    kind: str = "button"  # button, binary, power, integer, chiller or baud
    labels: tuple[str, ...] = ()


COMMAND_INFO = {
    "B": Command("BAUDRATE", "baud", "baud"),
    "CHILLER": Command("CHILLER", "°C", "chiller"),
    "E": Command("ECHO", "code", "binary", ("OFF", "ON")),
    "EXIT": Command("EXIT SCREEN", ""),
    "FL": Command("FLASH", ""),
    "KNOBDN": Command("KNOB DOWN", ""),
    "L": Command("LASER", "code", "binary", ("STANDBY", "ON / RESET FAULTS")),
    "LBOH": Command("LBO HEATER", "code", "binary", ("COOL DOWN", "HEATING")),
    "LBOOPT": Command("LBO OPTIMIZE", ""),
    "P": Command("LIGHT", "W", "power"),
    "LFP": Command("LOCK FRONT PANEL", "integer", "integer"),
    "MENUDN": Command("MENU DOWN", ""),
    "SELECT": Command("MENU SELECT", ""),
    "MENUUP": Command("MENU UP", ""),
    "PROMPT": Command("PROMPT", "code", "binary", ("ON", "OFF")),
    "S": Command("SHUTTER", "code", "binary", ("CLOSED", "OPEN")),
}
# Keep byte validation free of per-instruction encoding or decoding.
_COMMAND_BYTES = {name.encode("ascii"): spec for name, spec in COMMAND_INFO.items()}

# Acquisition order, shared so CLI and GUI status samples have the same fields.
STATUS_FIELDS = (
    ("laser_state", "?L"),
    ("keyswitch_on", "?K"),
    ("shutter_open", "?S"),
    ("power_w", "?P"),
    ("set_power_w", "?SP"),
    ("diode_current_a", "?D1C"),
    ("diode_temp_c", "?D1T"),
    ("heatsink_temp_c", "?D1HST"),
    ("baseplate_temp_c", "?BT"),
    ("lbo_temp_c", "?LBOT"),
    ("lbo_servo", "?LBOSS"),
    ("etalon_temp_c", "?ET"),
    ("vanadate_temp_c", "?VT"),
    ("faults", "?F"),
)
DIAGNOSTICS = {
    "software_version": "?SV",
    "head_hours": "?HH",
    "power_supply_hours": "?PSH",
    "diode_hours": "?D1H",
    "fault_history": "?FH",
}


def status_value(field: str, value: Any) -> Any:
    return bool(value) if field in ("keyswitch_on", "shutter_open") else value


def transaction_evidence(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a JSON-ready copy, or None when no exchange was attempted."""
    if record is None:
        return None
    result = dict(record)
    if isinstance(result.get("instruction"), bytes):
        result["instruction_hex"] = result["instruction"].hex()
        result["instruction"] = result["instruction"].decode("ascii")
    result["request_hex"] = result.pop("request").hex()
    result["response_hex"] = result.pop("response").hex()
    if isinstance(payload := result.get("payload"), bytes):
        result["payload_hex"] = payload.hex()
        try:
            result["payload"] = payload.decode("ascii")
        except UnicodeDecodeError:
            result["payload"] = None
    return result


def json_ready(value: Any) -> Any:
    """Represent byte values losslessly at JSON-only client boundaries."""
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value


def finite_range(value: float, low: float, high: float, name: str) -> float:
    """Validate a numeric setting before I/O; booleans are not numbers here."""
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not low <= value <= high
        or not isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
    return float(value)


def validate_power_w(power_w: float, limit_w: float) -> float:
    """Validate a 0.01 W target without I/O; also shared by GUI queue admission."""
    value = finite_range(power_w, 0, limit_w, "power_w")
    stepped = round(value, 2)
    # Allow binary float arithmetic noise, not sub-step power requests.
    if abs(value - stepped) > 2 * ulp(value):
        raise ValueError("power_w must be in 0.01 W increments")
    if stepped > limit_w:
        raise ValueError("rounded setpoint exceeds power_limit_w")
    return stepped


def _require_bool(value: Any, name: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{name} must be a bool")
    return value


class VerdiError(Exception):
    """Communication or reply failure. Retire the session; never replay a command."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message)
        self.transaction: dict[str, Any] | None = None


class DeviceError(VerdiError):
    """Complete documented device rejection; the connection remains usable."""

    def __init__(self, instruction: str, response: str) -> None:
        super().__init__(f"{instruction}: {response}")
        self.instruction = instruction
        self.response = response


_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")


def normalize_query(query: str) -> str:
    """Accept Table 5-4 short names and PRINT/? long-name aliases."""
    error = ValueError(f"unknown query: {query!r}")
    if not isinstance(query, str):
        raise error
    try:
        encode_instruction(query)
    except ValueError as exc:
        raise error from exc
    query = query.strip(" ")
    if query.startswith("PRINT "):
        name = query[6:].strip(" ")
    elif query.startswith("?"):
        name = query[1:]
    else:
        raise error
    short = QUERY_NAMES.get(name, "?" + name)
    if short not in QUERIES:
        raise error
    return short


def encode_instruction(instruction: str) -> bytes:
    if not instruction or len(instruction) > 128:
        raise ValueError("instruction must contain 1..128 printable ASCII characters")
    if any(not 32 <= ord(c) <= 126 or c == ";" for c in instruction):
        raise ValueError("only one printable ASCII instruction is allowed")
    return instruction.encode("ascii") + b"\r\n"


def _reply_prompts(model: str | None) -> tuple[bytes, ...]:
    prompts = (b"Verdi>",)
    models = {"V2": b"Verdi V-2>", "V5": b"Verdi V-5>", "V6": b"Verdi V-6>"}
    return prompts if model is None else prompts + (models[model],)


def _response_payload(
    instruction: bytes, wire: bytes, model: str | None, *, strict: bool = False
) -> bytes:
    """Remove bounded exact leading notices, then the normal response framing."""
    for _ in range(_MAX_STATUS_NOTICES):
        line, separator, remainder = wire.partition(b"\r\n")
        if line + separator not in _STATUS_NOTICES:
            break
        wire = remainder
    if strict and wire.startswith(_STATUS_NOTICES):
        raise VerdiError(f"more than {_MAX_STATUS_NOTICES} status notices before reply")
    prompts = _reply_prompts(model)
    for prompt in prompts:
        if wire.endswith(b"\r\n" + prompt):
            wire = wire[: -len(prompt)]
            break
    if strict and (not wire.endswith(b"\r\n") or b"\r" in wire[:-2] or b"\n" in wire[:-2]):
        raise VerdiError(f"{instruction!r}: expected exactly one CR/LF-terminated reply")
    payload = wire.removesuffix(b"\r\n")
    if strict:
        payload = payload.strip(b" ")
    for prompt in prompts:
        if payload.startswith(prompt):
            payload = payload[len(prompt) :].lstrip(b" ")
            break
    if payload.startswith(instruction):
        payload = payload[len(instruction) :].lstrip(b" ")
    return payload


def decode_response(
    instruction: str,
    wire: bytes,
    *,
    query: bool,
    allow_empty: bool = False,
    model: str | None = None,
    raw: bool = False,
) -> str | bytes:
    """Accept Table 5-1 layouts and the captured standalone terminal prompt.

    Up to eight exact leading firmware notices are accepted before the reply.
    Other extra lines are errors; this prevents silent reply mixing.
    Raw capture returns bytes. Other reads return ASCII text when possible and
    preserve non-ASCII payloads as bytes without guessing a character encoding.
    """
    echo = instruction.encode("ascii")
    payload = _response_payload(echo, wire, model, strict=True)
    if payload.startswith(b"Query Error:"):
        rejected = payload[len(b"Query Error:") :].strip(b" ")
        if rejected.startswith(b"?") and rejected != echo:
            raise VerdiError(
                f"{instruction}: device rejected a different query {rejected!r}; "
                "request/reply alignment is uncertain"
            )
    if payload.startswith((b"RANGE ERROR:", b"Command Error:", b"Query Error:")):
        raise DeviceError(instruction, payload.decode("ascii", errors="backslashreplace"))
    if query and not payload and not allow_empty:
        raise VerdiError(f"{instruction}: empty query response")
    if not query and payload:
        raise VerdiError(f"{instruction}: unexpected command acknowledgment {payload!r}")
    if raw:
        return payload
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError:
        return payload
    if any(not 32 <= ord(c) <= 126 for c in text):
        raise VerdiError(f"{instruction}: control character in reply")
    return text


def parse_faults(payload: str) -> list[int]:
    if payload == "SYSTEM OK":
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


def parse_value(query: str, payload: str | bytes) -> float | int | str | bytes | list[int]:
    spec = QUERY_INFO[query]
    if spec.kind == "text":
        return payload
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("ascii")
        except UnicodeDecodeError as exc:
            raise VerdiError(f"{query}: invalid {spec.kind} payload {payload!r}") from exc
    if spec.kind == "faults":
        return parse_faults(payload)
    if spec.kind in ("code", "baud"):
        valid = BAUDRATES if spec.kind == "baud" else range(len(spec.labels))
        code = _parse_integer(payload) if re.fullmatch(r"[0-9]+", payload) else -1
        if code not in valid:
            raise VerdiError(f"{query}: undocumented value {payload!r}")
        return code
    if not _NUMBER.fullmatch(payload):
        raise VerdiError(f"{query}: expected decimal number, received {payload!r}")
    value = float(payload)
    if not isfinite(value) or (spec.kind == "nonnegative" and value < 0):
        raise VerdiError(f"{query}: invalid numeric value {payload!r}")
    return value


class VerdiController:
    """One controller per connection. Construction sends nothing; connect is passive.

    Pass an explicit native port. Use SimulatedVerdi for hardware-free development.
    A context manager connects and disconnects; neither changes laser state.
    """

    is_simulated = False

    def __init__(
        self,
        port: str,
        *,
        model: str = "V5",
        baudrate: int = 19200,
        timeout_s: float = 1.0,
        allow_writes: bool = False,
        power_limit_w: float | None = None,
        prompt_enabled: bool = True,
    ) -> None:
        if model not in ("V2", "V5", "V6"):
            raise ValueError("model must be V2, V5 or V6")
        self._model = model
        self._prompt_enabled = _require_bool(prompt_enabled, "prompt_enabled")
        self._allow_writes = _require_bool(allow_writes, "allow_writes")
        rated = float(model[1:])
        self._power_limit_w = (
            rated
            if power_limit_w is None
            else finite_range(power_limit_w, 0, rated, "power_limit_w")
        )
        if not isinstance(port, str) or not port.strip() or "://" in port:
            raise ValueError("an explicit native port name is required; no discovery or URLs")
        if type(baudrate) is not int or baudrate not in BAUDRATES:
            raise ValueError("baudrate is not listed in manual Table 5-2")
        self._port = port
        self._port_key = port.removeprefix("\\\\.\\").casefold() if os.name == "nt" else port
        self._baudrate = baudrate
        self._timeout_s = finite_range(timeout_s, 0.001, 60.0, "timeout_s")
        self._stream: Any = None
        self._connected = False
        self._failed = False
        self._lock = RLock()
        self._last_transaction: dict[str, Any] | None = None

    @property
    def model(self) -> str:
        return self._model

    @property
    def allow_writes(self) -> bool:
        return self._allow_writes

    @property
    def power_limit_w(self) -> float:
        return self._power_limit_w

    @property
    def failed(self) -> bool:
        """Failure latch, readable without waiting for a device transaction."""
        return self._failed

    @property
    def last_transaction(self) -> dict[str, Any] | None:
        """Copy of the latest attempted exchange, including failed/partial replies."""
        with self._lock:
            return dict(self._last_transaction) if self._last_transaction is not None else None

    def connect(self, *, override: bool = True) -> bool:
        """Open the serial port and return True; raise if opening fails.

        True reports local port opening, not a successful instrument exchange.
        No discovery, queries or device configuration commands are sent.

        By default, close an older controller-owned handle for the same port in
        this Python process, waiting for its transaction to finish first. A port
        held by another kernel, application or raw Serial object cannot be stolen.

        The Windows pySerial backend purges host RX/TX buffers during open;
        this does not clear an unfinished instruction held by the device.

        After uncertain I/O, retire this controller. Establish a clean physical
        session before constructing another; reopening alone cannot prove that.
        """
        _require_bool(override, "override")
        with _PORT_LOCK, self._lock:
            if self._failed:
                raise VerdiError(
                    "failed session; establish a clean connection and use a new controller"
                )
            if not self._connected:
                if not self.is_simulated:
                    previous = _PORT_OWNERS.get(self._port_key)
                    if previous is not None and previous is not self:
                        if not override:
                            raise VerdiError(
                                f"port {self._port!r} already belongs to another controller; "
                                "use override=True to close that local connection"
                            )
                        previous.disconnect()
                try:
                    self._open()
                except BaseException:
                    self._failed = True
                    raise
                self._connected = True
                if not self.is_simulated:
                    _PORT_OWNERS[self._port_key] = self
            return self._connected

    def disconnect(self) -> None:
        """Release the connection, sending no commands. This does not stop the laser.

        Failed cleanup can be retried. A failed session never becomes reusable.
        """
        with _PORT_LOCK, self._lock:
            self._connected = False
            try:
                self._close()
            except BaseException:
                self._failed = True
                raise
            if not self.is_simulated and _PORT_OWNERS.get(self._port_key) is self:
                del _PORT_OWNERS[self._port_key]

    def purge_buffers(self) -> None:
        """Discard host TX, then RX; never reset device state or retry an exchange."""
        with self._lock:
            if not self._connected:
                raise VerdiError("controller is disconnected; connect before purging buffers")
            if self.is_simulated:
                return  # The simulator has no serial queues.
            try:
                if self._stream is None:
                    raise VerdiError("serial connection is not open")
                self._stream.reset_output_buffer()
                self._stream.reset_input_buffer()
            except BaseException as exc:
                self._failed = True
                if isinstance(exc, OSError):
                    raise VerdiError(f"serial buffer purge failed: {exc}") from exc
                raise

    # Byte exchange: one transaction, with no replay.

    def command(self, instruction: bytes) -> bytes:
        """Send one byte instruction and return its full CR/LF reply and prompt.

        This is the only serial transaction function. No text conversion, RX
        polling, per-byte timeout adjustment, purge or replay is performed.
        Non-query instructions require write permission and command validation.
        """
        self._validate_bytes(instruction)
        query = instruction.startswith(b"?")
        if not query:
            self._validate_command_bytes(instruction)
            if not self._allow_writes:
                raise PermissionError("writes disabled; pass allow_writes=True explicitly")
        with self._lock:
            if not self._connected or self._failed:
                raise VerdiError("controller is disconnected or failed; use a new session")
            request = instruction + b"\r\n"
            record: dict[str, Any] = {
                "instruction": instruction,
                "request": request,
                "response": b"",
                "payload": None,
                "outcome": "failed" if query else "unknown",
                "error": None,
            }
            self._last_transaction = record
            response = b""
            failure: BaseException | None = None
            try:
                from .simulator import SimulatedVerdi

                if isinstance(self, SimulatedVerdi):
                    response = self._simulate_response(request)
                else:
                    self._stream.timeout = self._timeout_s
                    self._stream.write_timeout = self._timeout_s
                    if self._stream.write(request) != len(request):
                        raise VerdiError("partial write; command outcome is unknown")
                    response = bytes(self._stream.read_until(b"\r\n", size=4096))
                    reply = response
                    notice_count = 0
                    while reply in _STATUS_NOTICES:
                        # Preserve each notice and require a separate reply. Both
                        # the line count and total byte limit bound these reads.
                        if notice_count == _MAX_STATUS_NOTICES:
                            raise VerdiError(
                                f"more than {_MAX_STATUS_NOTICES} status notices before reply"
                            )
                        notice_count += 1
                        if len(response) == 4096:
                            raise VerdiError("reply exceeds 4096 byte limit")
                        reply = bytes(self._stream.read_until(b"\r\n", size=4096 - len(response)))
                        response += reply
                    if not reply.endswith(b"\r\n"):
                        if len(response) == 4096:
                            raise VerdiError("reply exceeds 4096 byte limit")
                        raise VerdiError(f"reply timed out or incomplete: {response!r}")
                    expects_prompt = self._prompt_enabled
                    if instruction in (b"PROMPT=0", b"PROMPT=1"):
                        # A rejected change retains the old mode and its reply framing.
                        acknowledgment = _response_payload(instruction, response, self.model)
                        if not acknowledgment.strip(b" "):
                            expects_prompt = instruction == b"PROMPT=0"
                    if expects_prompt:
                        if len(response) == 4096:
                            raise VerdiError("reply exceeds 4096 byte limit")
                        prompt = bytes(self._stream.read_until(b">", size=4096 - len(response)))
                        response += prompt
                        if prompt not in _reply_prompts(self.model):
                            if len(response) == 4096:
                                raise VerdiError("reply exceeds 4096 byte limit")
                            raise VerdiError(
                                f"prompt timed out or unexpected: {prompt!r}; "
                                f"full response: {response!r}"
                            )
                    self._prompt_enabled = expects_prompt
                record["outcome"] = "received"
                return response
            except BaseException as exc:
                self._failed = True
                failure = (
                    VerdiError(f"serial I/O failed: {exc}") if isinstance(exc, OSError) else exc
                )
                record["error"] = f"{type(failure).__name__}: {failure}"
                if failure is exc:
                    raise
                raise failure from exc
            finally:
                record["response"] = response
                if isinstance(failure, VerdiError):
                    failure.transaction = dict(record)

    @staticmethod
    def _validate_bytes(instruction: bytes) -> None:
        if not isinstance(instruction, bytes):
            raise TypeError("instruction must be bytes; no automatic encoding is performed")
        if not 1 <= len(instruction) <= 128 or any(
            c < 32 or c > 126 or c == 59 for c in instruction
        ):
            raise ValueError("supply one printable instruction without CR/LF or semicolon")

    def read(self, query: bytes) -> bytes:
        """Return byte payload only; preserve the full wire reply in last_transaction."""
        self._validate_bytes(query)
        if not query.startswith(b"?"):
            raise ValueError("read requires a query starting with ?")
        with self._lock:
            payload = _response_payload(query, self.command(query), self.model)
            if self._last_transaction is not None:
                self._last_transaction["payload"] = payload
            return payload

    def write(self, instruction: bytes) -> bytes:
        """Send a byte setting and wait for its unchanged reply and prompt."""
        self._validate_bytes(instruction)
        if instruction.startswith(b"?"):
            raise ValueError("write requires a setting instruction")
        return self.command(instruction)

    def _validate_command_bytes(self, instruction: bytes) -> None:
        name, separator, operand = instruction.partition(b"=")
        if not separator:
            raise ValueError("command requires NAME=value bytes")
        spec = _COMMAND_BYTES.get(name)
        if spec is None:
            raise ValueError("unknown canonical command")
        if spec.kind == "power":
            if not re.fullmatch(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", operand):
                raise ValueError("power operand must be decimal watts")
            finite_range(float(operand), 0, self._power_limit_w, "power_w")
        elif spec.kind == "binary":
            if operand not in (b"0", b"1"):
                raise ValueError("command operand must be 0 or 1")
        elif spec.kind == "button":
            if operand != b"1":
                raise ValueError("button command operand must be 1")
        elif spec.kind == "integer":
            if not re.fullmatch(rb"[+-]?[0-9]+", operand):
                raise ValueError("panel-lock operand must be an integer")
        elif spec.kind == "chiller":
            if operand != b"ON" and (
                not re.fullmatch(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", operand)
                or not isfinite(float(operand))
            ):
                raise ValueError("chiller operand must be ON or a finite decimal")
        elif spec.kind == "baud":
            if not operand.isdigit() or int(operand) not in BAUDRATES:
                raise ValueError("baudrate is not listed in manual Table 5-2")
        else:
            raise ValueError(f"unknown command kind: {spec.kind}")

    # Typed API: read/write own every exchange; interpretation stays under the same lock.

    def _interpret_reply(
        self, instruction: str, response: bytes, *, capture: bool = False
    ) -> float | int | str | bytes | list[int]:
        """Interpret one completed exchange while the caller holds the transaction lock."""
        with self._lock:
            record = self._last_transaction
            assert record is not None
            query = instruction.startswith("?")
            try:
                payload = decode_response(
                    instruction,
                    response,
                    query=query,
                    allow_empty=capture,
                    model=self.model,
                    raw=capture,
                )
                record["payload"] = payload
                if capture or not query:
                    record["outcome"] = "captured" if capture else "acknowledged"
                    return payload
                value = parse_value(instruction, payload)
                if instruction in ("?D1SS", "?LBOSS") and (
                    (self.model == "V6" and value == 5) or (self.model == "V2" and value == 6)
                ):
                    raise VerdiError(
                        f"{instruction}: servo code {value} is not documented for {self.model}"
                    )
                record["outcome"] = "ok"
                return value
            except VerdiError as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                record["outcome"] = "rejected" if isinstance(exc, DeviceError) else "failed"
                if not isinstance(exc, DeviceError):
                    self._failed = True
                exc.transaction = dict(record)
                raise

    def get_value(self, query: str) -> float | int | str | bytes | list[int]:
        """Normalize a documented query, call read(), then validate and interpret its reply."""
        query = normalize_query(query)
        with self._lock:
            self.read(query.encode("ascii"))
            assert self._last_transaction is not None
            return self._interpret_reply(query, self._last_transaction["response"])

    def set_value(self, instruction: str) -> None:
        """Send a canonical text setting through write() and validate its acknowledgment."""
        if not isinstance(instruction, str):
            raise TypeError("setting instruction must be str; use write() for bytes")
        request = encode_instruction(instruction)[:-2]
        with self._lock:
            response = self.write(request)
            self._interpret_reply(instruction, response)

    def get_capture(self, query: str) -> dict[str, Any]:
        """Capture a documented query without interpreting its value; read-only sessions only.

        Payloads remain bytes. Framing and device errors are still enforced.
        Empty payloads are evidence,
        never an assertion that the instrument is clear or ready.
        """
        query = normalize_query(query)
        with self._lock:
            if self._allow_writes:
                raise PermissionError("capture requires a read-only controller")
            self.read(query.encode("ascii"))
            assert self._last_transaction is not None
            self._interpret_reply(query, self._last_transaction["response"], capture=True)
            return dict(self._last_transaction)

    # Named queries.

    def get_faults(self, *, history: bool = False) -> list[int]:
        return cast(list[int], self.get_value("?FH" if _require_bool(history, "history") else "?F"))

    def get_power_w(self) -> float:
        return cast(float, self.get_value("?P"))

    def get_laser_state(self) -> int:
        """Manual codes: 0 standby, 1 on, 2 fault."""
        return cast(int, self.get_value("?L"))

    def get_status(self) -> dict[str, Any]:
        """JSON-ready dictionary from 14 sequential reads, serialized against writes."""
        with self._lock:
            started = monotonic()
            sample: dict[str, Any] = {
                "model": self.model,
                "sampled_at": datetime.now(UTC).isoformat(),
                "simulated": self.is_simulated,
            }
            for field, query in STATUS_FIELDS:
                sample[field] = status_value(field, self.get_value(query))
            sample["duration_s"] = monotonic() - started
            return sample

    def get_diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {name: self.get_value(query) for name, query in DIAGNOSTICS.items()}

    # Named settings: power and emission.

    def set_power_w(self, power_w: float) -> None:
        """Set light regulation in 0.01 W increments; no implicit laser enable."""
        value = validate_power_w(power_w, self._power_limit_w)
        self.set_value(f"P={value:.4f}")

    def set_laser_state(self, state: int) -> None:
        """0: standby, overriding key ON; 1: enable/reset faults and fault history.

        Enabling requires the physical key ON. Query state 2 (fault) is not settable.
        """
        if type(state) is not int or state not in (0, 1):
            raise ValueError("laser state must be integer 0 (standby) or 1 (enable/reset faults)")
        self.set_value(f"L={state}")

    def set_shutter(self, *, open: bool) -> None:
        """Operate the Verdi safety shutter; never use as an experiment modulator."""
        self.set_value(f"S={int(_require_bool(open, 'open'))}")

    # Thermal and optical operations.

    def set_lbo_heater(self, *, enabled: bool) -> None:
        self.set_value(f"LBOH={int(_require_bool(enabled, 'enabled'))}")

    def set_lbo_optimization(self) -> None:
        """Initiate optimization; acknowledgment does not establish completion."""
        self.set_value("LBOOPT=1")

    def set_flash(self) -> None:
        """Drop below lasing threshold to allow the etalon to recenter."""
        self.set_value("FL=1")

    # Coherent chiller settings.

    def set_chiller_on(self) -> None:
        """CHILLER=ON; only for the Coherent chiller, part 1037271."""
        self.set_value("CHILLER=ON")

    def set_chiller_temperature_c(self, temperature_c: float) -> None:
        """CHILLER=XX.X; device enforces its undocumented temperature range."""
        # A loose numeric bound; the wire limit below rejects most of this range anyway.
        instruction = f"CHILLER={finite_range(temperature_c, -1e300, 1e300, 'temperature_c'):.1f}"
        self.set_value(instruction)

    # Physical front-panel controls.

    def set_front_panel_lock(self, value: int) -> None:
        """LFP=n; the manual does not define n's range or unlock mapping."""
        if type(value) is not int or not -(10**123) < value < 10**124:
            raise ValueError("front panel lock value must be an integer fitting one instruction")
        self.set_value(f"LFP={value}")

    def set_menu_up(self) -> None:
        self.set_value("MENUUP=1")

    def set_menu_down(self) -> None:
        self.set_value("MENUDN=1")

    def set_menu_select(self) -> None:
        self.set_value("SELECT=1")

    def set_exit_screen(self) -> None:
        self.set_value("EXIT=1")

    def set_knob_down(self) -> None:
        self.set_value("KNOBDN=1")

    # Serial link settings.

    def set_baudrate(self, baudrate: int) -> None:
        """Send B at the old baud, acknowledge there, then reconfigure the host.

        The manual does not specify acknowledgment baud/timing. A firmware that
        switches before replying may time out; never retry that uncertain change.
        """
        if type(baudrate) is not int or baudrate not in BAUDRATES:
            raise ValueError("baudrate is not listed in manual Table 5-2")
        with self._lock:
            self.set_value(f"B={baudrate}")
            try:
                if self._stream is not None:
                    self._stream.baudrate = baudrate
                self._baudrate = baudrate
            except BaseException as exc:
                self._failed = True
                failure = (
                    VerdiError(f"host baud reconfiguration failed: {exc}")
                    if isinstance(exc, (OSError, ValueError))
                    else exc
                )
                assert self._last_transaction is not None
                self._last_transaction["error"] = f"{type(failure).__name__}: {failure}"
                if isinstance(failure, VerdiError):
                    failure.transaction = dict(self._last_transaction)
                if failure is exc:
                    raise
                raise failure from exc

    def set_echo(self, *, enabled: bool) -> None:
        self.set_value(f"E={int(_require_bool(enabled, 'enabled'))}")

    def set_prompt(self, *, enabled: bool) -> None:
        self.set_value(f"PROMPT={int(not _require_bool(enabled, 'enabled'))}")

    # Context management and serial adapter.

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
                if (
                    getattr(exc, "errno", None) == 13
                    or getattr(exc, "winerror", None) == 5
                    or "Access is denied" in str(exc)
                ):
                    raise VerdiError(
                        f"could not open serial connection: {exc}. "
                        "Close the raw serial connection, other notebook kernel or application "
                        "holding this port; override only replaces controller-owned connections "
                        "in this Python process"
                    ) from exc
                raise VerdiError(f"could not open serial connection: {exc}") from exc
            raise

    def _close(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError as exc:
                raise VerdiError(f"serial close failed: {exc}") from exc
            self._stream = None
