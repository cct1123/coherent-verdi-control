"""Immutable public models. Units are included in field names."""

from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum, StrEnum
from math import isfinite

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
class ControllerConfig:
    model: Model
    allow_writes: bool = False
    power_limit_w: float | None = None
    active_fault_clear_reply: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.model, Model):
            raise ValueError("model must be Model.V2, Model.V5, or Model.V6")
        if type(self.allow_writes) is not bool:
            raise ValueError("allow_writes must be a bool")
        if self.power_limit_w is not None:
            finite_range(self.power_limit_w, 0, self.model.rated_power_w, "power_limit_w")
        reply = self.active_fault_clear_reply
        if reply is not None and (
            not isinstance(reply, str)
            or not 1 <= len(reply) <= 128
            or reply != reply.strip(" ")
            or any(not 32 <= ord(c) <= 126 or c == "&" for c in reply)
            or (reply.isdecimal() and int(reply) > 0)
        ):
            raise ValueError(
                "active_fault_clear_reply must be verified ASCII text or '0', not a fault code"
            )

    @property
    def effective_power_limit_w(self) -> float:
        return self.model.rated_power_w if self.power_limit_w is None else self.power_limit_w


@dataclass(frozen=True)
class SerialConfig:
    port: str
    baudrate: int = 19200
    timeout_s: float = 1.0
    max_response_bytes: int = 4096

    def __post_init__(self) -> None:
        if not isinstance(self.port, str) or not self.port.strip() or "://" in self.port:
            raise ValueError("an explicit native port name is required; discovery/URLs unsupported")
        if type(self.baudrate) is not int or self.baudrate not in BAUDRATES:
            raise ValueError("baudrate is not listed in manual Table 5-2")
        finite_range(self.timeout_s, 0.001, 60.0, "timeout_s")
        if type(self.max_response_bytes) is not int or not 16 <= self.max_response_bytes <= 65536:
            raise ValueError("max_response_bytes must be an integer from 16 to 65536")


def finite_range(value: float, low: float, high: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
    if not low <= value <= high or not isfinite(value):
        raise ValueError(f"{name} must be a finite number in [{low}, {high}]")
    return float(value)


@dataclass(frozen=True)
class Fault:
    code: int
    description: str
    known: bool


@dataclass(frozen=True)
class Status:
    """Sequential query sample, not a simultaneous or safety-certified measurement."""

    model: Model
    sampled_at: datetime
    duration_s: float
    laser_state: LaserState
    keyswitch_on: bool
    shutter_open: bool
    power_w: float
    set_power_w: float
    diode_current_a: float
    diode_temp_c: float
    heatsink_temp_c: float
    baseplate_temp_c: float
    lbo_temp_c: float
    lbo_servo: ServoState
    etalon_temp_c: float
    vanadate_temp_c: float
    faults: tuple[Fault, ...]
    simulated: bool = False


@dataclass(frozen=True)
class Diagnostics:
    software_version: str
    head_hours: float
    power_supply_hours: float
    diode_hours: float
    fault_history: tuple[Fault, ...]


@dataclass(frozen=True)
class TelemetrySample:
    sequence: int
    attempted_at: datetime
    status: Status | None
    error: str | None
    error_type: str | None


@dataclass(frozen=True)
class TelemetrySnapshot:
    """Immutable cached view; age uses the service's monotonic clock."""

    model: Model
    history: tuple[TelemetrySample, ...]
    simulated: bool | None
    age_s: float | None
    interval_s: float
