"""Deterministic, warm protocol fixture; no physical timing or laser dynamics."""

import re
from math import isfinite

from .controller import BAUDRATES, VerdiController, finite_range

_REPLIES = {
    "?BT": "30.00",
    "?B": "19200",
    "?D1HST": "28.00",
    "?D1H": "42.0",
    "?D1PC": "0.0",
    "?D1RCF": "1.0",
    "?D1RCM": "30.0",
    "?D1SS": "1",
    "?D1ST": "25.00",
    "?D1TD": "0.0",
    "?D1T": "25.00",
    "?D15V": "5.0",
    "?DIOS": "1",
    "?ED": "0.0",
    "?ESS": "1",
    "?EST": "50.00",
    "?ET": "50.00",
    "?HH": "100.0",
    "?LBOD": "0.0",
    "?LBOH": "1",
    "?LBOOS": "1",
    "?LBOST": "148.00",
    "?LBOSS": "1",
    "?LBOT": "148.00",
    "?M": "1",
    "?PSH": "120.0",
    "?SV": "SIMULATOR",
    "?VST": "30.00",
    "?VT": "30.00",
    "?VD": "0.0",
    "?VSS": "1",
}


class SimulatedVerdi(VerdiController):
    is_simulated = True

    def __init__(
        self,
        model: str = "V5",
        *,
        allow_writes: bool = False,
        power_limit_w: float | None = None,
        echo: bool = False,
        prompt: bool = False,
    ) -> None:
        if type(echo) is not bool or type(prompt) is not bool:
            raise ValueError("echo and prompt must be bools")
        super().__init__(
            "SIMULATOR",
            model=model,
            allow_writes=allow_writes,
            power_limit_w=power_limit_w,
            prompt_enabled=prompt,
        )
        self._echo = echo
        self._prompt = prompt
        self._key = False
        self._laser = 0
        self._shutter = False
        self._power = 0.0
        self._faults: tuple[int, ...] = ()
        self._history: tuple[int, ...] = ()
        self._device_baudrate = 19200
        self._lbo_heater = True
        self._lbo_optimizations = 0
        self._front_panel_lock = 0
        self._panel_action: str | None = None
        self._flash_count = 0
        self._chiller_on = False
        self._chiller_temperature_c: float | None = None

    def set_key(self, on: bool) -> None:
        """Test fixture operation; there is no remote keyswitch command."""
        if type(on) is not bool:
            raise ValueError("on must be a bool")
        with self._lock:
            self._key = on
            if not on:
                self._laser = 0
                self._shutter = False

    def set_faults(self, *codes: int) -> None:
        """Test fixture operation; never synthesizes interlock bypass commands."""
        if any(type(c) is not int or c <= 0 for c in codes):
            raise ValueError("fault codes must be positive integers")
        with self._lock:
            self._faults = tuple(dict.fromkeys(codes))
            self._history = tuple(dict.fromkeys((*self._history, *codes)))
            if codes:
                self._laser = 2
                self._shutter = False

    def _query(self, instruction: str) -> str:
        diode_on = self._laser == 1 and not self._faults
        emitting = diode_on and self._shutter
        # Closed-shutter idle is not diode-off (Tables 4-1/4-3). Values are fixtures.
        current = ("12.0" if self._shutter else "1.0") if diode_on else "0.0"
        # Independent short-form replies for the controller; values are fixtures.
        values: dict[str, str] = {
            "?B": str(self._device_baudrate),
            "?ACAD": f"{current}&0.0",
            "?C": current,
            "?D1C": current,
            "?F": "&".join(map(str, self._faults)) or "SYSTEM OK",
            "?FH": "&".join(map(str, self._history)) or "SYSTEM OK",
            "?K": str(int(self._key)),
            "?L": str(int(self._laser)),
            "?LBOH": str(int(self._lbo_heater)),
            "?P": f"{self._power if emitting else 0:.3f}",
            "?LRS": "1" if emitting else "0",
            "?SP": f"{self._power:.4f}",
            "?S": str(int(self._shutter)),
        }
        return values.get(instruction, _REPLIES.get(instruction, f"Query Error: {instruction}"))

    def _apply(self, instruction: str) -> str:
        name, sep, operand = instruction.partition("=")
        if not sep:
            return f"Command Error: {instruction}"
        name, operand = name.strip(), operand.strip()
        if name == "B":
            if operand not in {str(rate) for rate in BAUDRATES}:
                return f"RANGE ERROR: {instruction}"
            self._device_baudrate = int(operand)
        elif name == "CHILLER":
            if operand == "ON":
                self._chiller_on = True
            elif _chiller_temperature(operand):
                self._chiller_temperature_c = float(operand)
            else:
                return f"RANGE ERROR: {instruction}"
        elif name == "LFP":
            if not re.fullmatch(r"[+-]?[0-9]{1,124}", operand):
                return f"RANGE ERROR: {instruction}"
            # Preserve the operand; Table 5-3 does not specify lock/unlock values.
            self._front_panel_lock = int(operand)
        elif name in ("EXIT", "FL", "KNOBDN", "LBOOPT", "MENUDN", "SELECT", "MENUUP"):
            if operand != "1":
                return f"RANGE ERROR: {instruction}"
            if name == "FL":
                self._flash_count += 1  # No transient optical model.
            elif name == "LBOOPT":
                self._lbo_optimizations += 1  # No convergence or completion model.
            else:
                self._panel_action = name  # No front-panel menu emulation.
        elif name == "P":
            if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", operand):
                return f"RANGE ERROR: {instruction}"
            try:
                self._power = finite_range(float(operand), 0, float(self.model[1:]), "power")
            except ValueError:
                return f"RANGE ERROR: {instruction}"
        elif name in ("L", "S", "E", "PROMPT", "LBOH"):
            if operand not in ("0", "1"):
                return f"RANGE ERROR: {instruction}"
            value = operand == "1"
            if name == "L":
                if value:
                    self._history = ()
                    if self._faults:
                        self._laser = 2
                    elif self._key:
                        self._laser = 1
                else:
                    self._laser = 0
                    self._shutter = False
            elif name == "S":
                # Conservative simulation policy; not a claim about rejected hardware writes.
                self._shutter = value and self._laser == 1 and self._key
            elif name == "E":
                self._echo = value
            elif name == "PROMPT":
                self._prompt = not value
            elif name == "LBOH":
                self._lbo_heater = value  # No heating/cooling or fault model.
        else:
            return f"Command Error: {instruction}"
        return ""

    def _simulate_response(self, request: bytes) -> bytes:
        with self._lock:
            if request.endswith(b"\r\n"):
                body = request[:-2]
            else:
                raise ValueError("simulator expects CR/LF termination")
            if not body or any(c < 32 or c > 126 or c == 59 for c in body):
                raise ValueError("simulator accepts one printable ASCII instruction at a time")
            instruction = body.decode("ascii")
            query = instruction.startswith("?")
            parts: list[str] = []
            if self._echo:
                parts.append(instruction)
            payload = self._query(instruction) if query else self._apply(instruction)
            if payload:
                parts.append(payload)
            self._prompt_enabled = self._prompt
            line = (" ".join(parts) + "\r\n").encode("ascii")
            return line + (b"Verdi>" if self._prompt else b"")

    def _open(self) -> None:
        pass  # Keep fixture state across an explicit reconnect.

    def _close(self) -> None:
        pass  # Disconnect never changes simulated laser state.


def _chiller_temperature(operand: str) -> bool:
    return bool(re.fullmatch(r"[+-]?[0-9]+\.[0-9]", operand)) and isfinite(float(operand))
