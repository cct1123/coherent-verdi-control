"""Manual Rev IB, section 5: framing, value parsing and passive serial connection."""

import math
import re
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from math import isfinite
from time import monotonic
from typing import Any, Protocol

from .errors import DeviceError, ProtocolError, TransportError

BAUDRATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600)


class Model(StrEnum):
    V2 = "V2"
    V5 = "V5"
    V6 = "V6"

    @property
    def rated_power_w(self) -> float:
        """Table 2-1 ratings; used as conservative software setpoint ceilings."""
        return {Model.V2: 2.0, Model.V5: 5.0, Model.V6: 6.0}[self]


class LaserState(IntEnum):
    STANDBY = 0
    ON = 1
    FAULT = 2


class ServoState(IntEnum):
    OPEN = 0
    LOCKED = 1
    SEEKING = 2
    FAULT = 3
    OPTIMIZING = 4
    CPEAKING = 5
    CPEAKING2 = 6


@dataclass(frozen=True)
class Fault:
    code: int
    description: str
    known: bool


def finite_range(value: float, low: float, high: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
    if not low <= value <= high or not isfinite(value):
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
    return float(value)


class Query(StrEnum):
    AVG_CURRENT_AND_DELTA = "?ACAD"
    BASEPLATE_TEMP = "?BT"
    BAUDRATE = "?B"
    CURRENT = "?C"
    DIODE_CURRENT = "?D1C"
    DIODE_HEATSINK_TEMP = "?D1HST"
    DIODE_HOURS = "?D1H"
    DIODE_PHOTOCELL = "?D1PC"
    DIODE_RATED_CURRENT_FACTOR = "?D1RCF"
    DIODE_RATED_CURRENT_MAX = "?D1RCM"
    DIODE_SERVO = "?D1SS"
    DIODE_SET_TEMP = "?D1ST"
    DIODE_TEMP_DRIVE = "?D1TD"
    DIODE_TEMP = "?D1T"
    DIODE_REFERENCE = "?D15V"
    DIODE_OPTIMIZER = "?DIOS"
    ETALON_DRIVE = "?ED"
    ETALON_SERVO = "?ESS"
    ETALON_SET_TEMP = "?EST"
    ETALON_TEMP = "?ET"
    FAULTS = "?F"
    FAULT_HISTORY = "?FH"
    HEAD_HOURS = "?HH"
    KEYSWITCH = "?K"
    LASER = "?L"
    LBO_DRIVE = "?LBOD"
    LBO_HEATER = "?LBOH"
    LBO_OPTIMIZER = "?LBOOS"
    LBO_SET_TEMP = "?LBOST"
    LBO_SERVO = "?LBOSS"
    LBO_TEMP = "?LBOT"
    POWER = "?P"
    LIGHT_SERVO = "?LRS"
    MODE = "?M"
    PS_HOURS = "?PSH"
    SET_POWER = "?SP"
    SHUTTER = "?S"
    SOFTWARE = "?SV"
    VANADATE_SET_TEMP = "?VST"
    VANADATE_TEMP = "?VT"
    VANADATE_DRIVE = "?VD"
    VANADATE_SERVO = "?VSS"


# Table 5-4 parsing groups. Page/unit documentation lives in docs/PROTOCOL.md.
_TEXT = {
    Query.AVG_CURRENT_AND_DELTA,
    Query.DIODE_PHOTOCELL,
    Query.DIODE_RATED_CURRENT_FACTOR,
    Query.DIODE_TEMP_DRIVE,
    Query.DIODE_REFERENCE,
    Query.ETALON_DRIVE,
    Query.LBO_DRIVE,
    Query.SOFTWARE,
    Query.VANADATE_DRIVE,
}
_CODES = {
    Query.BAUDRATE: BAUDRATES,
    Query.DIODE_SERVO: range(7),
    Query.LBO_SERVO: range(7),
    Query.ETALON_SERVO: range(4),
    Query.LIGHT_SERVO: range(4),
    Query.VANADATE_SERVO: range(4),
    Query.LASER: range(3),
    Query.DIODE_OPTIMIZER: range(2),
    Query.KEYSWITCH: range(2),
    Query.LBO_HEATER: range(2),
    Query.LBO_OPTIMIZER: range(2),
    Query.MODE: range(2),
    Query.SHUTTER: range(2),
}
_NONNEGATIVE = {
    Query.CURRENT,
    Query.DIODE_CURRENT,
    Query.DIODE_HOURS,
    Query.DIODE_RATED_CURRENT_MAX,
    Query.HEAD_HOURS,
    Query.POWER,
    Query.PS_HOURS,
    Query.SET_POWER,
}

FAULT_DESCRIPTIONS = {
    # Table 5-4 conflicts with Table 6-1 / Chart 5; preserve both labels.
    1: "Laser head interlock / emission lamp fault (manual labels conflict)",
    2: "External interlock fault",
    3: "Power supply cover interlock fault",
    4: "LBO temperature fault",
    5: "LBO not locked at set temperature",
    6: "Vanadate temperature fault",
    7: "Etalon temperature fault",
    8: "Diode 1 temperature fault",
    10: "Baseplate temperature fault",
    11: "Heatsink 1 temperature fault",
    16: "Diode 1 over current fault",
    18: "Over current fault",
    19: "Diode 1 under voltage fault",
    21: "Diode 1 over voltage fault",
    25: "Diode 1 EEPROM fault",
    27: "Laser head EEPROM fault",
    28: "Power supply EEPROM fault",
    29: "Power supply-head mismatch fault",
    30: "Battery requires service",  # Table 6-1, p.6-2; Chart 13, p.6-21.
    31: "Shutter state mismatch",
    40: "Head-diode mismatch fault",
    47: "Vanadate 2 temperature fault",
}

QueryResult = float | int | str | tuple[Fault, ...]
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)")


def encode_instruction(instruction: str) -> bytes:
    if not instruction or len(instruction) > 128:
        raise ValueError("instruction must contain 1..128 printable ASCII characters")
    if any(not 32 <= ord(c) <= 126 or c == ";" for c in instruction):
        raise ValueError("only one printable ASCII instruction is allowed")
    return instruction.encode("ascii") + b"\r\n"


def decode_response(instruction: str, wire: bytes, *, query: bool) -> str:
    """Accept the four single-line echo/prompt layouts in Table 5-1.

    Extra lines are errors, not discarded data; this prevents silent reply mixing.
    """
    if not wire.endswith(b"\r\n") or b"\r" in wire[:-2] or b"\n" in wire[:-2]:
        raise ProtocolError(f"{instruction}: expected exactly one CR/LF-terminated reply")
    try:
        payload = wire[:-2].decode("ascii")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"{instruction}: non-ASCII reply") from exc
    if any(not 32 <= ord(c) <= 126 for c in payload):
        raise ProtocolError(f"{instruction}: control character in reply")
    payload = payload.strip(" ")
    if payload.startswith("Verdi>"):
        payload = payload[len("Verdi>") :].lstrip()
    # Echo uses the instruction exactly as transmitted (Table 5-1).
    if payload.startswith(instruction):
        payload = payload[len(instruction) :].lstrip()
    if payload.startswith(("RANGE ERROR:", "Command Error:", "Query Error:")):
        raise DeviceError(instruction, payload)
    if query and not payload:
        raise ProtocolError(f"{instruction}: empty query response")
    if not query and payload:
        raise ProtocolError(f"{instruction}: unexpected command acknowledgment {payload!r}")
    return payload


def parse_faults(payload: str, *, clear_reply: str | None = "SYSTEM OK") -> tuple[Fault, ...]:
    # The default clear text is documented for history only (Table 5-4).
    if payload == clear_reply:
        return ()
    if not re.fullmatch(r"[1-9][0-9]*(?:\s*&\s*[1-9][0-9]*)*", payload):
        raise ProtocolError(f"invalid fault list {payload!r}")
    codes = tuple(_parse_integer(part) for part in payload.split("&"))
    return tuple(
        Fault(c, FAULT_DESCRIPTIONS.get(c, "Unknown fault code"), c in FAULT_DESCRIPTIONS)
        for c in codes
    )


def _parse_integer(payload: str) -> int:
    try:
        return int(payload)
    except ValueError as exc:
        # Python bounds decimal conversion independently of the configured wire
        # response limit. Malformed/unrepresentable data must still invalidate
        # the controller session through the normal ProtocolError path.
        raise ProtocolError("integer reply exceeds the supported conversion limit") from exc


def parse_value(
    query: Query, payload: str, *, active_fault_clear_reply: str | None = None
) -> QueryResult:
    if query in (Query.FAULTS, Query.FAULT_HISTORY):
        return parse_faults(
            payload, clear_reply=active_fault_clear_reply if query == Query.FAULTS else "SYSTEM OK"
        )
    if query in _TEXT:
        return payload
    if query in _CODES:
        if not re.fullmatch(r"[0-9]+", payload):
            raise ProtocolError(f"{query.value}: undocumented value {payload!r}")
        integer_value = _parse_integer(payload)
        if integer_value not in _CODES[query]:
            raise ProtocolError(f"{query.value}: undocumented value {payload!r}")
        return integer_value
    if not _NUMBER.fullmatch(payload):
        raise ProtocolError(f"{query.value}: expected decimal number, received {payload!r}")
    value = float(payload)
    if not math.isfinite(value) or (query in _NONNEGATIVE and value < 0):
        raise ProtocolError(f"{query.value}: invalid numeric value {payload!r}")
    return value


class Connection(Protocol):
    """Minimal backend contract; one controller exclusively uses each connection."""

    is_simulated: bool

    def connect(self) -> None: ...
    def exchange(self, request: bytes) -> bytes: ...
    def disconnect(self) -> None: ...


class SerialConnection:
    """No I/O until connect(). The controller serializes calls and handles failed sessions."""

    is_simulated = False

    def __init__(self, port: str, *, baudrate: int = 19200, timeout_s: float = 1.0) -> None:
        if not isinstance(port, str) or not port.strip() or "://" in port:
            raise ValueError("an explicit native port name is required; no discovery or URLs")
        if type(baudrate) is not int or baudrate not in BAUDRATES:
            raise ValueError("baudrate is not listed in manual Table 5-2")
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = finite_range(timeout_s, 0.001, 60.0, "timeout_s")
        self._stream: Any = None

    def connect(self) -> None:
        if self._stream is not None:
            return
        import serial

        stream = serial.Serial(
            port=None,
            baudrate=self.baudrate,
            bytesize=8,
            parity="N",
            stopbits=1,
            timeout=self.timeout_s,
            write_timeout=self.timeout_s,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )
        # Retain the handle even when open/cleanup fails, so disconnect can be retried.
        self._stream = stream
        try:
            stream.dtr = False
            stream.rts = False
            stream.port = self.port
            stream.open()
        except BaseException as exc:
            try:
                self.disconnect()
            except BaseException as cleanup_error:
                exc.add_note(f"serial cleanup also failed: {cleanup_error}")
            if isinstance(exc, (OSError, ValueError)):
                raise TransportError(f"could not open serial connection: {exc}") from exc
            raise

    def exchange(self, request: bytes) -> bytes:
        if self._stream is None:
            raise TransportError("serial connection is not open")
        try:
            deadline = monotonic() + self.timeout_s
            self._stream.write_timeout = self.timeout_s
            if self._stream.write(request) != len(request):
                raise TransportError("partial write; command outcome is unknown")
            response = bytearray()
            while len(response) < 4096:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise TransportError(f"reply timed out after {len(response)} bytes")
                self._stream.timeout = remaining
                chunk = self._stream.read(1)
                if not chunk or monotonic() > deadline:
                    raise TransportError(f"reply timed out after {len(response)} bytes")
                response.extend(chunk)
                if response.endswith(b"\r\n"):
                    return bytes(response)
            raise TransportError("reply exceeds 4096 byte limit")
        except OSError as exc:
            raise TransportError(f"serial I/O failed: {exc}; outcome may be unknown") from exc

    def disconnect(self) -> None:
        if self._stream is not None:
            try:
                self._stream.close()
            except OSError as exc:
                raise TransportError(f"serial close failed: {exc}") from exc
            self._stream = None
