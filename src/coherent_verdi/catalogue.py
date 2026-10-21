"""Manual names, units and status fields shared by the driver and GUI.

Add a documented query here, then add its independent simulator reply and test.
This file describes the protocol; it never opens a port or sends an instruction.
"""

from typing import NamedTuple

BAUDRATES = (1200, 2400, 4800, 9600, 19200, 38400, 57600)


class Query(NamedTuple):
    """One Table 5-4 entry; choices constrain integer codes, not physical readiness."""

    name: str
    unit: str
    kind: str = "number"
    choices: tuple[int, ...] | range = ()


QUERY_INFO = {
    "?ACAD": Query("AVG CURRENT AND DELTA", "raw", "text"),
    "?BT": Query("BASEPLATE TEMP", "°C"),
    "?B": Query("BAUD RATE", "baud", "code", BAUDRATES),
    "?C": Query("CURRENT", "A", "nonnegative"),
    "?D1C": Query("DIODE1 CURRENT", "A", "nonnegative"),
    "?D1HST": Query("DIODE1 HEATSINK TEMP", "°C"),
    "?D1H": Query("DIODE1 HOURS", "h", "nonnegative"),
    "?D1PC": Query("DIODE1 PHOTOCELL", "raw", "text"),
    "?D1RCF": Query("DIODE1 RATED CURRENT FACTOR", "raw", "text"),
    "?D1RCM": Query("DIODE1 RATED CURRENT MAX", "A", "nonnegative"),
    "?D1SS": Query("DIODE1 SERVO STATUS", "code", "code", range(0, 7)),
    "?D1ST": Query("DIODE1 SET TEMP", "°C"),
    "?D1TD": Query("DIODE1 TEMP DRIVE", "raw", "text"),
    "?D1T": Query("DIODE1 TEMP", "°C"),
    "?D15V": Query("DIODE1 5VREF SENSE", "raw", "text"),
    "?DIOS": Query("DIODE OPTIMIZER STATUS", "code", "code", range(0, 2)),
    "?ED": Query("ETALON DRIVE", "raw", "text"),
    "?ESS": Query("ETALON SERVO STATUS", "code", "code", range(0, 4)),
    "?EST": Query("ETALON SET TEMP", "°C"),
    "?ET": Query("ETALON TEMP", "°C"),
    "?F": Query("FAULTS", "codes", "faults"),
    "?FH": Query("FAULT HISTORY", "codes", "faults"),
    "?HH": Query("HEAD_HOURS", "h", "nonnegative"),
    "?K": Query("KEYSWITCH", "code", "code", range(0, 2)),
    "?L": Query("LASER", "code", "code", range(0, 3)),
    "?LBOD": Query("LBO DRIVE", "raw", "text"),
    "?LBOH": Query("LBO HEATER", "code", "code", range(0, 2)),
    "?LBOOS": Query("LBO OPTIMIZER STATUS", "code", "code", range(0, 2)),
    "?LBOST": Query("LBO SET TEMP", "°C"),
    "?LBOSS": Query("LBO SERVO STATUS", "code", "code", range(0, 7)),
    "?LBOT": Query("LBO TEMP", "°C"),
    "?P": Query("LIGHT", "W", "nonnegative"),
    "?LRS": Query("LIGHT REG STATUS", "code", "code", range(0, 4)),
    "?M": Query("MODE", "code", "code", range(0, 2)),
    "?PSH": Query("PS HOURS", "h", "nonnegative"),
    "?SP": Query("SET LIGHT", "W", "nonnegative"),
    "?S": Query("SHUTTER", "code", "code", range(0, 2)),
    "?SV": Query("SOFTWARE", "text", "text"),
    "?VST": Query("VANADATE SET TEMP", "°C"),
    "?VT": Query("VANADATE TEMP", "°C"),
    "?VD": Query("VANADATE DRIVE", "raw", "text"),
    "?VSS": Query("VANADATE SERVO STATUS", "code", "code", range(0, 4)),
}

QUERIES = frozenset(QUERY_INFO)
QUERY_NAMES = {spec.name: query for query, spec in QUERY_INFO.items()}

# Preserve acquisition order so CLI and GUI status samples have the same fields.
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

# Labels explain the numeric codes; only the driver decides which are valid.
SERVO_CODES = {
    0: "OPEN",
    1: "LOCKED",
    2: "SEEKING",
    3: "FAULT",
    4: "OPTIMIZING",
    5: "CPEAKING",
    6: "CPEAKING2",
}
STATE_CODES = {
    "?L": {0: "STANDBY", 1: "ON", 2: "FAULT"},
    "?K": {0: "OFF", 1: "ON"},
    "?S": {0: "CLOSED", 1: "OPEN"},
    "?M": {0: "CURRENT", 1: "LIGHT"},
    "?LBOH": {0: "COOL DOWN", 1: "HEATING"},
    "?DIOS": {0: "UNAVAILABLE", 1: "AVAILABLE"},
    "?LBOOS": {0: "UNAVAILABLE", 1: "AVAILABLE"},
    **{query: SERVO_CODES for query in ("?D1SS", "?LBOSS", "?ESS", "?VSS", "?LRS")},
}
