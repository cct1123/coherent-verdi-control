"""Synchronous Verdi driver: explicit serial lifecycle, manual protocol, plain results.

The catalogue below describes the protocol; it never opens a port or sends an
instruction. Add a documented query there, then its independent simulator reply
and test.
"""

import os
import re
from datetime import UTC, datetime
from math import isfinite
from threading import RLock
from time import monotonic
from types import TracebackType
from typing import Any, NamedTuple, Self, cast
from weakref import WeakValueDictionary

BAUDRATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600)
_PORT_LOCK = RLock()
_PORT_OWNERS: WeakValueDictionary[str, "VerdiController"] = WeakValueDictionary()


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

    Extra lines are errors, not discarded data; this prevents silent reply mixing.
    Raw capture returns bytes. Other reads return ASCII text when possible and
    preserve non-ASCII payloads as bytes without guessing a character encoding.
    """
    prompts = _reply_prompts(model)
    # Firmware 6.05 on the captured V2 emits an unterminated terminal prompt
    # after the reply. Keep it in wire evidence, outside the CR/LF data frame.
    for prompt in prompts:
        if wire.endswith(b"\r\n" + prompt):
            wire = wire[: -len(prompt)]
            break
    if not wire.endswith(b"\r\n") or b"\r" in wire[:-2] or b"\n" in wire[:-2]:
        raise VerdiError(f"{instruction}: expected exactly one CR/LF-terminated reply")
    payload = wire[:-2].strip(b" ")
    for prompt in prompts:
        if payload.startswith(prompt):
            payload = payload[len(prompt) :].lstrip(b" ")
            break
    # Echo uses the instruction exactly as transmitted (Table 5-1).
    echo = instruction.encode("ascii")
    if payload.startswith(echo):
        payload = payload[len(echo) :].lstrip(b" ")
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
    query: str, payload: str | bytes, *, active_fault_clear_reply: str | None = None
) -> float | int | str | bytes | list[int]:
    spec = QUERY_INFO[query]
    if spec.kind == "text":
        return payload
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("ascii")
        except UnicodeDecodeError as exc:
            raise VerdiError(f"{query}: invalid {spec.kind} payload {payload!r}") from exc
    if spec.kind == "faults":
        return parse_faults(
            payload, clear_reply=active_fault_clear_reply if query == "?F" else "SYSTEM OK"
        )
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
        active_fault_clear_reply: str | None = None,
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

    def _request(
        self, instruction: str, *, capture: bool = False
    ) -> float | int | str | bytes | list[int]:
        with self._lock:
            if not self._connected or self._failed:
                raise VerdiError("controller is disconnected or failed; use a new session")
            # Interpretation is opt-in at this higher-level boundary. Transport stays bytes.
            response = self.command(encode_instruction(instruction)[:-2])
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
            except VerdiError as exc:
                record["error"] = f"{type(exc).__name__}: {exc}"
                record["outcome"] = "rejected" if isinstance(exc, DeviceError) else "failed"
                if not isinstance(exc, DeviceError):
                    self._failed = True
                exc.transaction = dict(record)
                raise

    def get_value(self, query: str) -> float | int | str | bytes | list[int]:
        """Explicitly normalize, decode and interpret a documented query."""
        query = normalize_query(query)
        return self._request(query)

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
                    if not response.endswith(b"\r\n"):
                        if len(response) == 4096:
                            raise VerdiError("reply exceeds 4096 byte limit")
                        raise VerdiError(f"reply timed out or incomplete: {response!r}")
                    expects_prompt = self._prompt_enabled
                    if instruction == b"PROMPT=1":
                        expects_prompt = False
                    elif instruction == b"PROMPT=0":
                        expects_prompt = True
                    if expects_prompt:
                        if len(response) == 4096:
                            raise VerdiError("reply exceeds 4096 byte limit")
                        prompt = bytes(self._stream.read_until(b">", size=4096 - len(response)))
                        response += prompt
                        if prompt not in _reply_prompts(self.model):
                            if len(response) == 4096:
                                raise VerdiError("reply exceeds 4096 byte limit")
                            raise VerdiError(f"prompt timed out or unexpected: {prompt!r}")
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

    def get(self, query: bytes) -> bytes:
        """Return byte payload only; preserve the full wire reply in last_transaction."""
        self._validate_bytes(query)
        if not query.startswith(b"?"):
            raise ValueError("get requires a query starting with ?")
        with self._lock:
            payload = self.command(query)
            for prompt in _reply_prompts(self.model):
                if payload.endswith(b"\r\n" + prompt):
                    payload = payload[: -len(prompt)]
                    break
            payload = payload.removesuffix(b"\r\n")
            for prompt in _reply_prompts(self.model):
                if payload.startswith(prompt):
                    payload = payload[len(prompt) :].lstrip(b" ")
                    break
            if payload.startswith(query):
                payload = payload[len(query) :].lstrip(b" ")
            if self._last_transaction is not None:
                self._last_transaction["payload"] = payload
            return payload

    def set(self, instruction: bytes) -> bytes:
        """Send a byte setting and wait for its unchanged reply and prompt."""
        self._validate_bytes(instruction)
        if instruction.startswith(b"?"):
            raise ValueError("set requires a setting instruction")
        return self.command(instruction)

    def _validate_command_bytes(self, instruction: bytes) -> None:
        name, separator, operand = instruction.partition(b"=")
        if not separator:
            raise ValueError("command requires NAME=value bytes")
        if name == b"P":
            if not re.fullmatch(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", operand):
                raise ValueError("power operand must be decimal watts")
            finite_range(float(operand), 0, self._power_limit_w, "power_w")
        elif name in (b"L", b"S", b"E", b"PROMPT", b"LBOH"):
            if operand not in (b"0", b"1"):
                raise ValueError("command operand must be 0 or 1")
        elif name in (b"EXIT", b"FL", b"KNOBDN", b"LBOOPT", b"MENUDN", b"SELECT", b"MENUUP"):
            if operand != b"1":
                raise ValueError("button command operand must be 1")
        elif name == b"LFP":
            if not re.fullmatch(rb"[+-]?[0-9]+", operand):
                raise ValueError("panel-lock operand must be an integer")
        elif name == b"CHILLER":
            if operand != b"ON" and (
                not re.fullmatch(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", operand)
                or not isfinite(float(operand))
            ):
                raise ValueError("chiller operand must be ON or a finite decimal")
        elif name == b"B":
            if not operand.isdigit() or int(operand) not in BAUDRATES:
                raise ValueError("baudrate is not listed in manual Table 5-2")
        else:
            raise ValueError("unknown canonical command")

    def capture(self, query: str) -> dict[str, Any]:
        """Capture a documented query without interpreting its value; read-only sessions only.

        Payloads remain bytes. Framing and device errors are still enforced.
        Empty payloads are evidence,
        never an assertion that the instrument is clear or ready.
        """
        query = normalize_query(query)
        with self._lock:
            if self._allow_writes:
                raise PermissionError("capture requires a read-only controller")
            self._request(query, capture=True)
            assert self._last_transaction is not None
            return dict(self._last_transaction)

    def read_faults(self, *, history: bool = False) -> list[int]:
        return cast(list[int], self.get_value("?FH" if _require_bool(history, "history") else "?F"))

    def read_power_w(self) -> float:
        return cast(float, self.get_value("?P"))

    def read_laser_state(self) -> int:
        """Manual codes: 0 standby, 1 on, 2 fault."""
        return cast(int, self.get_value("?L"))

    def status(self) -> dict[str, Any]:
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

    def read_diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {name: self.get_value(query) for name, query in DIAGNOSTICS.items()}

    def set_power_w(self, power_w: float) -> None:
        """Set light regulation, rounded to four decimals; no implicit laser enable."""
        value = finite_range(power_w, 0, self._power_limit_w, "power_w")
        # Check the serialized value too: rounding must not exceed a site ceiling.
        encoded = f"{value:.4f}"
        if float(encoded) > self._power_limit_w:
            raise ValueError("rounded setpoint exceeds power_limit_w")
        self._request(f"P={encoded}")

    def stop(self) -> None:
        """LASER=0 overrides an ON keyswitch (Table 5-3)."""
        self._request("L=0")

    def start(self) -> None:
        """LASER=1 also resets faults and clears fault history. Explicit action only.

        The hardware keyswitch must be ON. This API is not an interlock or a
        substitute for an approved beam path and laboratory operating procedure.
        """
        self._request("L=1")

    def set_shutter(self, *, open: bool) -> None:
        """Operate the Verdi safety shutter; never use as an experiment modulator."""
        self._request(f"S={int(_require_bool(open, 'open'))}")

    def set_echo(self, *, enabled: bool) -> None:
        self._request(f"E={int(_require_bool(enabled, 'enabled'))}")

    def set_prompt(self, *, enabled: bool) -> None:
        self._request(f"PROMPT={int(not _require_bool(enabled, 'enabled'))}")

    def set_baudrate(self, baudrate: int) -> None:
        """Send B at the old baud, acknowledge there, then reconfigure the host.

        The manual does not specify acknowledgment baud/timing. A firmware that
        switches before replying may time out; never retry that uncertain change.
        """
        if type(baudrate) is not int or baudrate not in BAUDRATES:
            raise ValueError("baudrate is not listed in manual Table 5-2")
        with self._lock:
            self._request(f"B={baudrate}")
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

    def chiller_on(self) -> None:
        """CHILLER=ON; only for the Coherent chiller, part 1037271."""
        self._request("CHILLER=ON")

    def set_chiller_temperature_c(self, temperature_c: float) -> None:
        """CHILLER=XX.X; device enforces its undocumented temperature range."""
        # A loose numeric bound; the wire limit below rejects most of this range anyway.
        instruction = f"CHILLER={finite_range(temperature_c, -1e300, 1e300, 'temperature_c'):.1f}"
        self._request(instruction)

    def exit_screen(self) -> None:
        self._request("EXIT=1")

    def flash(self) -> None:
        """Drop below lasing threshold to allow the etalon to recenter."""
        self._request("FL=1")

    def knob_down(self) -> None:
        self._request("KNOBDN=1")

    def set_lbo_heater(self, *, enabled: bool) -> None:
        self._request(f"LBOH={int(_require_bool(enabled, 'enabled'))}")

    def optimize_lbo(self) -> None:
        """Initiate optimization; acknowledgment does not establish completion."""
        self._request("LBOOPT=1")

    def set_front_panel_lock(self, value: int) -> None:
        """LFP=n; the manual does not define n's range or unlock mapping."""
        if type(value) is not int or not -(10**123) < value < 10**124:
            raise ValueError("front panel lock value must be an integer fitting one instruction")
        self._request(f"LFP={value}")

    def menu_down(self) -> None:
        self._request("MENUDN=1")

    def menu_select(self) -> None:
        self._request("SELECT=1")

    def menu_up(self) -> None:
        self._request("MENUUP=1")

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
