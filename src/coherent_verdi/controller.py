"""Synchronous controller, suitable for one shared owner in a research stack."""

from datetime import UTC, datetime
from threading import RLock
from time import monotonic
from types import TracebackType
from typing import cast

from .errors import ConnectionUnusable, ProtocolError, WritesDisabled
from .models import (
    ControllerConfig,
    Diagnostics,
    Fault,
    LaserState,
    ServoState,
    Status,
    finite_range,
)
from .protocol import Query, QueryResult, decode_response, encode_instruction, parse_value
from .transport import Transport


class VerdiController:
    """Owns a transport; construction, replacement and close send no commands.

    One lock covers transactions and compound samples, so reads and commands cannot
    consume one another's responses. Samples are sequential, never simultaneous.
    Use one controller per connection and stop telemetry before closing it.
    """

    def __init__(self, transport: Transport, config: ControllerConfig) -> None:
        self._transport = transport
        self._config = config
        self._lock = RLock()
        self._closed = False
        self._failed = False

    @property
    def config(self) -> ControllerConfig:
        return self._config

    @property
    def is_simulated(self) -> bool:
        with self._lock:
            return self._transport.is_simulated

    def _exchange(self, instruction: str, *, query: bool) -> str:
        if self._closed or self._failed:
            raise ConnectionUnusable(
                "controller is closed or needs an explicit transport replacement"
            )
        try:
            return decode_response(
                instruction, self._transport.exchange(encode_instruction(instruction)), query=query
            )
        except ProtocolError:
            self._failed = True
            raise

    def query(self, query: Query) -> QueryResult:
        """Run a catalogued read. Unknown representations remain raw text in the catalog."""
        if not isinstance(query, Query):
            raise ValueError("query must be a Query enum member")
        with self._lock:
            payload = self._exchange(query.value, query=True)
            try:
                return parse_value(query, payload)
            except ProtocolError:
                self._failed = True
                raise

    def _number(self, query: Query) -> float:
        return float(cast(float, self.query(query)))

    def _integer(self, query: Query) -> int:
        return cast(int, self.query(query))

    def faults(self, *, history: bool = False) -> tuple[Fault, ...]:
        return cast(tuple[Fault, ...], self.query(Query.FAULT_HISTORY if history else Query.FAULTS))

    def power_w(self) -> float:
        return self._number(Query.POWER)

    def laser_state(self) -> LaserState:
        return LaserState(self._integer(Query.LASER))

    def status(self) -> Status:
        with self._lock:
            started = monotonic()
            timestamp = datetime.now(UTC)
            state = self.laser_state()
            key = bool(self._integer(Query.KEYSWITCH))
            shutter = bool(self._integer(Query.SHUTTER))
            power = self.power_w()
            set_power = self._number(Query.SET_POWER)
            current = self._number(Query.DIODE_CURRENT)
            diode = self._number(Query.DIODE_TEMP)
            heatsink = self._number(Query.DIODE_HEATSINK_TEMP)
            baseplate = self._number(Query.BASEPLATE_TEMP)
            lbo = self._number(Query.LBO_TEMP)
            lbo_servo = ServoState(self._integer(Query.LBO_SERVO))
            etalon = self._number(Query.ETALON_TEMP)
            vanadate = self._number(Query.VANADATE_TEMP)
            faults = self.faults()
            return Status(
                self.config.model,
                timestamp,
                monotonic() - started,
                state,
                key,
                shutter,
                power,
                set_power,
                current,
                diode,
                heatsink,
                baseplate,
                lbo,
                lbo_servo,
                etalon,
                vanadate,
                faults,
            )

    def diagnostics(self) -> Diagnostics:
        with self._lock:
            return Diagnostics(
                cast(str, self.query(Query.SOFTWARE)),
                self._number(Query.HEAD_HOURS),
                self._number(Query.PS_HOURS),
                self._number(Query.DIODE_HOURS),
                self.faults(history=True),
            )

    def _command(self, instruction: str) -> None:
        with self._lock:
            if not self.config.allow_writes:
                raise WritesDisabled("create ControllerConfig with allow_writes=True explicitly")
            self._exchange(instruction, query=False)

    def set_power_w(self, power_w: float) -> None:
        """Set light regulation, rounded to four decimals; no implicit laser enable."""
        value = finite_range(power_w, 0, self.config.effective_power_limit_w, "power_w")
        # Check the serialized value too: rounding must not exceed a site ceiling.
        encoded = f"{value:.4f}"
        if float(encoded) > self.config.effective_power_limit_w:
            raise ValueError("rounded setpoint exceeds power_limit_w")
        self._command(f"P={encoded}")

    def standby(self) -> None:
        """LASER=0 overrides an ON keyswitch (Table 5-3)."""
        self._command("L=0")

    def enable_laser(self) -> None:
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

    def replace_transport(self, transport: Transport) -> None:
        """Explicit recovery using a caller-prepared fresh transport; no state replay.

        Caller must establish that old pending responses cannot contaminate the new
        session. Closing/reopening a physical port alone does not prove this.
        """
        with self._lock:
            if self._closed:
                raise ConnectionUnusable("cannot replace transport on a closed controller")
            if transport is self._transport:
                raise ValueError("replacement must be a different transport")
            self._transport.close()
            self._transport = transport
            self._failed = False

    def close(self) -> None:
        """Release communication resources; does not change laser/shutter/heater state."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._transport.close()

    def __enter__(self) -> "VerdiController":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
