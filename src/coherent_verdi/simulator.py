"""Deterministic fake protocol peer. Numeric values/dynamics are test fixtures.

The manual defines messages and state meanings, not a numerical laser plant.
See docs/SIMULATOR.md for every deliberate simplification and uncertain reply.
"""

from collections import deque
from collections.abc import Callable
from threading import RLock
from time import monotonic

from .errors import ConnectionUnusable, ResponseTimeout
from .models import LaserState, Model, finite_range


class SimulatedTransport:
    is_simulated = True

    def __init__(
        self,
        model: Model = Model.V5,
        *,
        clock: Callable[[], float] = monotonic,
        warmup_s: float = 0.0,
        echo: bool = False,
        prompt: bool = False,
    ) -> None:
        if not isinstance(model, Model):
            raise ValueError("model must be a Model enum")
        finite_range(warmup_s, 0, 86400, "warmup_s")
        self.model = model
        self._clock = clock
        self._started = clock()
        self._warmup_s = warmup_s
        self._echo = echo
        self._prompt = prompt
        self._closed = False
        self._lock = RLock()
        self._key = False
        self._laser = LaserState.STANDBY
        self._shutter = False
        self._power = 0.0
        self._faults: tuple[int, ...] = ()
        self._history: tuple[int, ...] = ()
        self._injections: deque[tuple[bytes | Exception, bool]] = deque()
        self._requests: deque[bytes] = deque(maxlen=4096)

    @property
    def requests(self) -> tuple[bytes, ...]:
        with self._lock:
            return tuple(self._requests)

    def set_key(self, on: bool) -> None:
        """Test fixture operation; there is no remote keyswitch command."""
        if type(on) is not bool:
            raise ValueError("on must be a bool")
        with self._lock:
            self._key = on
            if not on:
                self._laser = LaserState.STANDBY
                self._shutter = False

    def set_faults(self, *codes: int) -> None:
        """Test fixture operation; never synthesizes interlock bypass commands."""
        if any(type(c) is not int or c <= 0 for c in codes):
            raise ValueError("fault codes must be positive integers")
        with self._lock:
            self._faults = tuple(dict.fromkeys(codes))
            self._history = tuple(dict.fromkeys((*self._history, *codes)))
            if codes:
                self._laser = LaserState.FAULT
                self._shutter = False

    def inject(self, response: bytes | Exception, *, after_apply: bool = False) -> None:
        """Override next reply, optionally after applying its request to fake state."""
        with self._lock:
            self._injections.append((response, after_apply))

    def inject_timeout(self, *, after_apply: bool = False) -> None:
        """Model a lost request or an applied command whose acknowledgment is lost."""
        self.inject(ResponseTimeout("simulated response timeout"), after_apply=after_apply)

    def _ready(self) -> bool:
        return self._clock() - self._started >= self._warmup_s

    def _query(self, instruction: str) -> str:
        elapsed = max(0.0, self._clock() - self._started)
        ready = self._ready()
        emitting = self._laser == LaserState.ON and self._shutter and ready and not self._faults
        fraction = 1.0 if not self._warmup_s else min(1.0, elapsed / self._warmup_s)
        # Independent literal query mapping deliberately does not import QUERY_SPECS.
        values: dict[str, str] = {
            "?ACAD": "0.0&0.0",
            "?BT": "30.00",
            "?B": "19200",
            "?C": "0.0",
            "?D1C": "12.0" if emitting else "0.0",
            "?D1HST": "28.00",
            "?D1H": "42.0",
            "?D1PC": "0.0",
            "?D1RCF": "1.0",
            "?D1RCM": "30.0",
            "?D1SS": "1" if ready else "2",
            "?D1ST": "25.00",
            "?D1TD": "0.0",
            "?D1T": "25.00",
            "?D15V": "5.0",
            "?DIOS": "1" if ready else "0",
            "?ED": "0.0",
            "?ESS": "1" if ready else "2",
            "?EST": "50.00",
            "?ET": "50.00",
            "?F": "&".join(map(str, self._faults)) or "SYSTEM OK",
            "?FH": "&".join(map(str, self._history)) or "SYSTEM OK",
            "?HH": "100.0",
            "?K": str(int(self._key)),
            "?L": str(int(self._laser)),
            "?LBOD": "0.0",
            "?LBOH": "1",
            "?LBOOS": "1" if ready else "0",
            "?LBOST": "148.00",
            "?LBOSS": "1" if ready else "2",
            "?LBOT": f"{25 + 123 * fraction:.2f}",
            "?P": f"{self._power if emitting else 0:.3f}",
            "?LRS": "1" if emitting else "0",
            "?M": "1",
            "?PSH": "120.0",
            "?SP": f"{self._power:.4f}",
            "?S": str(int(self._shutter)),
            "?SV": "SIMULATOR-0.1",
            "?VST": "30.00",
            "?VT": "30.00",
            "?VD": "0.0",
            "?VSS": "1",
        }
        values["?C"] = values["?D1C"]
        return values.get(instruction, f"Query Error: {instruction}")

    def _command(self, instruction: str) -> str:
        name, sep, operand = instruction.partition("=")
        if not sep:
            return f"Command Error: {instruction}"
        name, operand = name.strip(), operand.strip()
        if name in ("P", "POWER", "LIGHT"):
            try:
                self._power = finite_range(float(operand), 0, self.model.rated_power_w, "power")
            except ValueError:
                return f"RANGE ERROR: {instruction}"
        elif name in ("L", "LASER", "S", "SHUTTER", "E", "ECHO", "PROMPT"):
            if operand not in ("0", "1"):
                return f"RANGE ERROR: {instruction}"
            value = operand == "1"
            if name in ("L", "LASER"):
                if value:
                    self._history = ()
                    if self._faults:
                        self._laser = LaserState.FAULT
                    elif self._key:
                        self._laser = LaserState.ON
                else:
                    self._laser = LaserState.STANDBY
                    self._shutter = False
            elif name in ("S", "SHUTTER"):
                # Conservative simulation policy; not a claim about rejected hardware writes.
                self._shutter = value and self._laser == LaserState.ON and self._key
            elif name in ("E", "ECHO"):
                self._echo = value
            elif name == "PROMPT":
                self._prompt = not value
        else:
            return f"Command Error: {instruction}"
        return ""

    def exchange(self, request: bytes) -> bytes:
        with self._lock:
            if self._closed:
                raise ConnectionUnusable("simulator connection is closed")
            self._requests.append(request)
            if not request.endswith(b"\r\n"):
                raise ValueError("simulator expects CR/LF framing")
            instruction = request[:-2].decode("ascii")
            if self._injections:
                result, after_apply = self._injections.popleft()
                if after_apply:
                    if instruction.startswith("?"):
                        self._query(instruction)
                    else:
                        self._command(instruction)
                if isinstance(result, Exception):
                    raise result
                return result
            prefix = "Verdi> " if self._prompt else ""
            prefix += instruction + " " if self._echo else ""
            payload = (
                self._query(instruction)
                if instruction.startswith("?")
                else self._command(instruction)
            )
            return (prefix + payload + "\r\n").encode("ascii")

    def close(self) -> None:
        with self._lock:
            self._closed = True
