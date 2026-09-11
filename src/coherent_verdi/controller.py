"""Synchronous Verdi API. No threads, logging, GUI imports or automatic commands."""

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from time import monotonic
from types import TracebackType
from typing import cast

from .errors import DeviceError, ProtocolError, TransportError
from .protocol import (
    Connection,
    Fault,
    LaserState,
    Model,
    Query,
    QueryResult,
    SerialConnection,
    ServoState,
    decode_response,
    encode_instruction,
    finite_range,
    parse_value,
)


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


class VerdiController:
    """One controller per connection. Construction sends nothing; connect is passive.

    Pass an explicit port or an unshared backend, e.g. SimulatedTransport().
    A context manager connects and disconnects; neither changes laser state.
    """

    def __init__(
        self,
        port: str | Connection,
        *,
        model: Model | str = Model.V5,
        baudrate: int = 19200,
        timeout_s: float = 1.0,
        allow_writes: bool = False,
        power_limit_w: float | None = None,
        active_fault_clear_reply: str | None = None,
    ) -> None:
        self._model = Model(model)
        if type(allow_writes) is not bool:
            raise ValueError("allow_writes must be a bool")
        self._allow_writes = allow_writes
        self._power_limit_w = (
            self.model.rated_power_w
            if power_limit_w is None
            else finite_range(power_limit_w, 0, self.model.rated_power_w, "power_limit_w")
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
        self._connection = (
            SerialConnection(port, baudrate=baudrate, timeout_s=timeout_s)
            if isinstance(port, str)
            else port
        )
        if not all(
            callable(getattr(self._connection, name, None))
            for name in ("connect", "exchange", "disconnect")
        ):
            raise ValueError("port must be a native port name or a connection backend")
        self._connected = False
        self._failed = False
        self._lock = RLock()

    @property
    def model(self) -> Model:
        return self._model

    @property
    def is_simulated(self) -> bool:
        return self._connection.is_simulated

    def connect(self) -> None:
        """Open without discovery, queries, flushing or configuration commands.

        After uncertain I/O, retire this controller. Establish a clean physical
        session before constructing another; reopening alone cannot prove that.
        """
        with self._lock:
            if self._failed:
                raise TransportError(
                    "failed session; establish a clean connection and use a new controller"
                )
            if not self._connected:
                try:
                    self._connection.connect()
                except BaseException:
                    self._failed = True
                    raise
                self._connected = True

    def disconnect(self) -> None:
        """Release the connection, sending no commands. This does not stop the laser.

        Failed cleanup can be retried. A failed session never becomes reusable.
        """
        with self._lock:
            self._connected = False
            try:
                self._connection.disconnect()
            except BaseException:
                self._failed = True
                raise

    def _exchange(self, instruction: str, query: Query | None = None) -> QueryResult:
        if not self._connected or self._failed:
            raise TransportError(
                "controller is disconnected or failed; after a failure use a new session"
            )
        try:
            payload = decode_response(
                instruction,
                self._connection.exchange(encode_instruction(instruction)),
                query=query is not None,
            )
            if query is None:
                return payload
            clear_reply = self._active_fault_clear_reply
            if clear_reply is None and self._connection.is_simulated:
                clear_reply = "SYSTEM OK"  # Explicit simulator convention, not firmware evidence.
            value = parse_value(query, payload, active_fault_clear_reply=clear_reply)
            if query in (Query.DIODE_SERVO, Query.LBO_SERVO) and (
                (self.model == Model.V6 and value == 5) or (self.model == Model.V2 and value == 6)
            ):
                raise ProtocolError(
                    f"{query}: servo code {value} is not documented for {self.model}"
                )
            return value
        except DeviceError:
            raise  # Complete documented rejection: the reply has been consumed.
        except BaseException:
            self._failed = True
            raise

    def read(self, query: Query | str) -> QueryResult:
        """Run a catalogued read. Unknown representations remain raw text in the catalog."""
        query = Query(query)  # Reject unknown commands before touching the connection.
        with self._lock:
            return self._exchange(query.value, query)

    def read_faults(self, *, history: bool = False) -> tuple[Fault, ...]:
        if type(history) is not bool:
            raise ValueError("history must be a bool")
        return cast(tuple[Fault, ...], self.read(Query.FAULT_HISTORY if history else Query.FAULTS))

    def read_power_w(self) -> float:
        return cast(float, self.read(Query.POWER))

    def read_laser_state(self) -> LaserState:
        return LaserState(cast(int, self.read(Query.LASER)))

    def status(self) -> Status:
        with self._lock:
            started = monotonic()
            return Status(
                model=self.model,
                sampled_at=datetime.now(UTC),
                laser_state=self.read_laser_state(),
                keyswitch_on=bool(self.read(Query.KEYSWITCH)),
                shutter_open=bool(self.read(Query.SHUTTER)),
                power_w=self.read_power_w(),
                set_power_w=cast(float, self.read(Query.SET_POWER)),
                diode_current_a=cast(float, self.read(Query.DIODE_CURRENT)),
                diode_temp_c=cast(float, self.read(Query.DIODE_TEMP)),
                heatsink_temp_c=cast(float, self.read(Query.DIODE_HEATSINK_TEMP)),
                baseplate_temp_c=cast(float, self.read(Query.BASEPLATE_TEMP)),
                lbo_temp_c=cast(float, self.read(Query.LBO_TEMP)),
                lbo_servo=ServoState(cast(int, self.read(Query.LBO_SERVO))),
                etalon_temp_c=cast(float, self.read(Query.ETALON_TEMP)),
                vanadate_temp_c=cast(float, self.read(Query.VANADATE_TEMP)),
                faults=self.read_faults(),
                simulated=self._connection.is_simulated,
                duration_s=monotonic() - started,
            )

    def read_diagnostics(self) -> Diagnostics:
        with self._lock:
            return Diagnostics(
                cast(str, self.read(Query.SOFTWARE)),
                cast(float, self.read(Query.HEAD_HOURS)),
                cast(float, self.read(Query.PS_HOURS)),
                cast(float, self.read(Query.DIODE_HOURS)),
                self.read_faults(history=True),
            )

    def _command(self, instruction: str) -> None:
        with self._lock:
            if not self._allow_writes:
                raise PermissionError("writes disabled; pass allow_writes=True explicitly")
            self._exchange(instruction)

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

    def __enter__(self) -> "VerdiController":
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
