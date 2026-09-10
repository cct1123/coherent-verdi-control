"""Verdi operator manual Rev IB, section 5, Tables 5-1 through 5-4.

No discovery, I/O, mode negotiation or physical behavior lives in this module.
"""

import math
import re
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from .errors import DeviceError, ProtocolError
from .models import Fault


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


@dataclass(frozen=True)
class QuerySpec:
    page: str
    unit: str | None
    kind: str = "number"
    choices: tuple[int, ...] = ()


# Unspecified units and composite layouts deliberately remain raw text.
QUERY_SPECS = MappingProxyType(
    {
        Query.AVG_CURRENT_AND_DELTA: QuerySpec("5-6", None, "text"),
        Query.BASEPLATE_TEMP: QuerySpec("5-6", "degC"),
        Query.BAUDRATE: QuerySpec(
            "5-6", "baud", "enum", (1200, 2400, 4800, 9600, 19200, 38400, 57600)
        ),
        Query.CURRENT: QuerySpec("5-6", "A"),
        Query.DIODE_CURRENT: QuerySpec("5-6", "A"),
        Query.DIODE_HEATSINK_TEMP: QuerySpec("5-6", "degC"),
        Query.DIODE_HOURS: QuerySpec("5-6", "h"),
        Query.DIODE_PHOTOCELL: QuerySpec("5-6", None, "text"),
        Query.DIODE_RATED_CURRENT_FACTOR: QuerySpec("5-6", None, "text"),
        Query.DIODE_RATED_CURRENT_MAX: QuerySpec("5-6", "A"),
        Query.DIODE_SERVO: QuerySpec("5-7", None, "enum", tuple(range(7))),
        Query.DIODE_SET_TEMP: QuerySpec("5-7", "degC"),
        Query.DIODE_TEMP_DRIVE: QuerySpec("5-7", None, "text"),
        Query.DIODE_TEMP: QuerySpec("5-7", "degC"),
        Query.DIODE_REFERENCE: QuerySpec("5-7", None, "text"),
        Query.DIODE_OPTIMIZER: QuerySpec("5-7", None, "enum", (0, 1)),
        Query.ETALON_DRIVE: QuerySpec("5-7", None, "text"),
        Query.ETALON_SERVO: QuerySpec("5-7", None, "enum", (0, 1, 2, 3)),
        Query.ETALON_SET_TEMP: QuerySpec("5-7", "degC"),
        Query.ETALON_TEMP: QuerySpec("5-7", "degC"),
        Query.FAULTS: QuerySpec("5-8", None, "faults"),
        Query.FAULT_HISTORY: QuerySpec("5-8", None, "faults"),
        Query.HEAD_HOURS: QuerySpec("5-8", "h"),
        Query.KEYSWITCH: QuerySpec("5-8", None, "enum", (0, 1)),
        Query.LASER: QuerySpec("5-8", None, "enum", (0, 1, 2)),
        Query.LBO_DRIVE: QuerySpec("5-8", None, "text"),
        Query.LBO_HEATER: QuerySpec("5-8", None, "enum", (0, 1)),
        Query.LBO_OPTIMIZER: QuerySpec("5-8", None, "enum", (0, 1)),
        Query.LBO_SET_TEMP: QuerySpec("5-8", "degC"),
        Query.LBO_SERVO: QuerySpec("5-9", None, "enum", tuple(range(7))),
        Query.LBO_TEMP: QuerySpec("5-9", "degC"),
        Query.POWER: QuerySpec("5-9", "W"),
        Query.LIGHT_SERVO: QuerySpec("5-9", None, "enum", (0, 1, 2, 3)),
        Query.MODE: QuerySpec("5-9", None, "enum", (0, 1)),
        Query.PS_HOURS: QuerySpec("5-9", "h"),
        Query.SET_POWER: QuerySpec("5-9", "W"),
        Query.SHUTTER: QuerySpec("5-9", None, "enum", (0, 1)),
        Query.SOFTWARE: QuerySpec("5-9", None, "text"),
        Query.VANADATE_SET_TEMP: QuerySpec("5-9", "degC"),
        Query.VANADATE_TEMP: QuerySpec("5-9", "degC"),
        Query.VANADATE_DRIVE: QuerySpec("5-10", None, "text"),
        Query.VANADATE_SERVO: QuerySpec("5-10", None, "enum", (0, 1, 2, 3)),
    }
)

FAULT_DESCRIPTIONS = MappingProxyType(
    {
        1: "Laser head interlock fault",
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
        31: "Shutter state mismatch",
        40: "Head-diode mismatch fault",
        47: "Vanadate 2 temperature fault",
    }
)

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


def parse_faults(payload: str) -> tuple[Fault, ...]:
    # SYSTEM OK is explicit for ?FH; accepting it for ?F is a compatibility
    # assumption, documented in docs/PROTOCOL.md and subject to physical review.
    if payload == "SYSTEM OK":
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


def parse_value(query: Query, payload: str) -> QueryResult:
    spec = QUERY_SPECS[query]
    if spec.kind == "faults":
        return parse_faults(payload)
    if spec.kind == "text":
        return payload
    if spec.kind == "enum":
        if not re.fullmatch(r"[0-9]+", payload):
            raise ProtocolError(f"{query.value}: undocumented value {payload!r}")
        integer_value = _parse_integer(payload)
        if integer_value not in spec.choices:
            raise ProtocolError(f"{query.value}: undocumented value {payload!r}")
        return integer_value
    if not _NUMBER.fullmatch(payload):
        raise ProtocolError(f"{query.value}: expected decimal {spec.unit}, received {payload!r}")
    value = float(payload)
    if not math.isfinite(value) or (spec.unit in ("h", "A", "W") and value < 0):
        raise ProtocolError(f"{query.value}: invalid {spec.unit} value {payload!r}")
    return value
