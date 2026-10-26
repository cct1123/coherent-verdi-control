"""Caller-scheduled telemetry, a bounded GUI request queue and an optional Dash panel.

Only the single acquisition caller (Monitor.poll_once) touches the controller.
Browser callbacks submit requests or copy cached results and never wait for
serial I/O. Constructing a Monitor or its Dash view sends no device instructions
and starts no thread; the launcher owns the worker, connection and server.
"""

import json
from collections import OrderedDict, deque
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from itertools import islice
from math import isfinite
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from typing import Any, NamedTuple, cast
from uuid import uuid4

from .controller import (
    DIAGNOSTICS,
    QUERY_INFO,
    STATUS_FIELDS,
    VerdiController,
    finite_range,
    json_ready,
    normalize_query,
    status_value,
    transaction_evidence,
)


class Action(NamedTuple):
    """A GUI label and a documented command; None expected means use its operand."""

    label: str
    command: str
    query: str | None = None
    expected: int | None = None


ACTIONS = {
    "power": Action("Apply power", "P=", "?SP"),
    "start": Action("Start / reset faults", "L=1", "?L", 1),
    "standby": Action("Standby", "L=0", "?L", 0),
    "shutter_open": Action("Open shutter", "S=1", "?S", 1),
    "shutter_close": Action("Close shutter", "S=0", "?S", 0),
    "lbo_on": Action("LBO heater: heat", "LBOH=1", "?LBOH", 1),
    "lbo_off": Action("LBO heater: cool down", "LBOH=0", "?LBOH", 0),
    "optimize_lbo": Action("Initiate LBO optimization", "LBOOPT=1"),
    "flash": Action("FLASH / etalon recenter", "FL=1"),
    "chiller_on": Action("Coherent chiller ON", "CHILLER=ON"),
    "chiller_temperature": Action("Set chiller temperature / °C", "CHILLER="),
    "front_panel_lock": Action("Front-panel lock operand / integer", "LFP="),
    "exit_screen": Action("EXIT button", "EXIT=1"),
    "knob_down": Action("KNOB DOWN button", "KNOBDN=1"),
    "menu_down": Action("MENU DOWN button", "MENUDN=1"),
    "menu_select": Action("MENU SELECT button", "SELECT=1"),
    "menu_up": Action("MENU UP button", "MENUUP=1"),
    "baudrate": Action("Change baud rate", "B=", "?B"),
    "echo_on": Action("Echo ON", "E=1"),
    "echo_off": Action("Echo OFF", "E=0"),
    "prompt_on": Action("Prompt ON", "PROMPT=0"),
    "prompt_off": Action("Prompt OFF", "PROMPT=1"),
}
OPERATE = ("power", "start", "standby", "shutter_open", "shutter_close")
SERVICE_ACTIONS = {name: spec.label for name, spec in ACTIONS.items() if name not in OPERATE}
KNOWN_ACTIONS = {*ACTIONS, "read", "capture", "diagnostics", "polling"}
URGENT_ACTIONS = {"standby", "shutter_close"}
ORDINARY_WRITES = ACTIONS.keys() - URGENT_ACTIONS
# Dash button id -> queued action; the service button sends the selected action.
_SAME_NAMES = "start standby shutter-open shutter-close service read capture diagnostics"
BUTTONS = {"apply-power": "power", "pause-polling": "polling", "resume-polling": "polling"} | {
    name: name.replace("-", "_") for name in _SAME_NAMES.split()
}
# Front-panel replica keys; shutter_toggle may turn the SHUTTER OPEN key into an open.
PANEL_BUTTONS = {
    "panel-menu-up": "menu_up",
    "panel-menu-down": "menu_down",
    "panel-select": "menu_select",
    "panel-exit": "exit_screen",
    "panel-shutter": "shutter_close",
    "panel-level-1": "power",
    "panel-level-2": "power",
    "panel-apply-power": "power",
}
BUTTONS |= PANEL_BUTTONS
CHANNELS = {*BUTTONS, "polling"}
# Write buttons that also need a fresh overview; standby/close stay available.
FRESH_BUTTONS = ("apply-power", "start", "shutter-open", "service") + tuple(
    name for name in PANEL_BUTTONS if name != "panel-shutter"
)
LCD_WIDTH = 20
# Fieldsets the server (and the browser watchdog) disable together.
WRITE_GROUPS = ("write-controls", "front-panel", "service-controls")
# Bootstrap colour for each action record state.
STATE_TONES = {
    **dict.fromkeys(("verified", "read", "applied", "captured"), "success"),
    **dict.fromkeys(("queued", "running"), "info"),
    "acknowledged": "secondary",  # Accepted, but no documented readback.
    **dict.fromkeys(("mismatch", "cancelled"), "warning"),
    **dict.fromkeys(("readback_failed", "failed", "rejected"), "danger"),
}
ACTIVE = ("queued", "running")
# Bound memory and how long one drain can postpone the overview.
MAX_PENDING = 16
MAX_RECORDS = 128
MAX_CLIENTS = 64
MAX_QUEUE_AGE_S = 10


def _utc() -> str:
    return datetime.now(UTC).isoformat()


def display_value(query: str, value: Any) -> str:
    if isinstance(value, dict) and "bytes_hex" in value:
        return repr(bytes.fromhex(value["bytes_hex"]))
    labels = QUERY_INFO[query].labels if query in QUERY_INFO else ()
    if labels and type(value) is int:
        return f"{value} · {labels[value] if 0 <= value < len(labels) else 'UNKNOWN'}"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "None reported"
    return str(value)


def display_unit(query: str) -> str:
    """Physical unit for display; code, text and raw replies have none."""
    unit = QUERY_INFO[query].unit
    return "" if unit in ("code", "codes", "text", "raw") else unit


def _reading(query: str, value: Any) -> str:
    return f"{display_value(query, value)} {display_unit(query)}".rstrip()


class ControlSession:
    """Shared queue and action evidence; construction starts no worker or I/O.

    Action records are the only queue state: queued/running records are pending,
    in submission order. Browser callbacks only submit requests or copy
    snapshots, including while device I/O is blocked.
    """

    def __init__(
        self,
        controller: VerdiController,
        monitor: "Monitor",
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.controller = controller
        self.monitor = monitor
        self._clock = clock
        self._lock = Lock()
        self.wake = Event()
        self._clients: OrderedDict[str, dict[str, int]] = OrderedDict()
        self._records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._accepting = True
        self._polling = True
        self._writes = 0  # Executed write actions, including those nested in diagnostics.
        self._queries: dict[str, Any] = {}

    @property
    def polling(self) -> bool:
        return self._polling and self._accepting

    def new_client(self) -> str:
        """Register a browser with independent click counters; oldest registrations expire."""
        token = uuid4().hex
        with self._lock:
            self._clients[token] = {}
            if len(self._clients) > MAX_CLIENTS:
                self._clients.popitem(last=False)
        return token

    def set_commissioning(self) -> None:
        """Before starting the worker: no automatic queries, read-only capture."""
        if self.controller.allow_writes:
            raise ValueError("commissioning requires a read-only controller")
        self._polling = False

    def _queued(self) -> list[dict[str, Any]]:
        return [item for item in self._records.values() if item["state"] == "queued"]

    def _pending(self, *, writes: bool = False) -> bool:
        return any(
            item["state"] in ACTIVE and (not writes or item["action"] in ACTIONS)
            for item in self._records.values()
        )

    def submit(
        self,
        client: str,
        channel: str,
        sequence: int,
        action: str,
        value: Any = None,
        *,
        confirmed: bool = False,
    ) -> str:
        """Admit one explicit user action, with per-browser/channel deduplication."""
        if not isinstance(action, str) or action not in KNOWN_ACTIONS:
            raise ValueError("unknown GUI action")
        if not isinstance(channel, str) or channel not in CHANNELS:
            raise ValueError("unknown GUI channel")
        if type(sequence) is not int or not 1 <= sequence <= 2**53:
            raise ValueError("invalid action sequence")
        if type(confirmed) is not bool:
            raise ValueError("confirmation must be a bool")
        # Keep queued browser payloads bounded and immutable.
        if value is not None and type(value) not in (str, int, float, bool):
            raise ValueError("invalid action value")
        if isinstance(value, str) and len(value) > 128:
            raise ValueError("action value is too long")
        if type(value) in (int, float) and (not -1e100 <= value <= 1e100 or not isfinite(value)):
            raise ValueError("action value must be a finite bounded number")
        if not isinstance(client, str) or len(client) != 32:
            raise ValueError("invalid browser session")
        request_id = f"{client}:{channel}:{sequence}"
        write, urgent = action in ACTIONS, action in URGENT_ACTIONS
        with self._lock:
            if client not in self._clients:
                raise ValueError("browser session expired; reload the page")
            if request_id in self._records:
                return request_id
            if sequence <= self._clients[client].get(channel, 0):
                raise ValueError("old action already handled; submit a new action")
            self._clients[client][channel] = sequence
            if not self._accepting:
                raise PermissionError("GUI session is closing")
            if self.controller.failed:
                raise PermissionError("controller session failed; use a new session")
            if write and not self.controller.allow_writes:
                raise PermissionError("writes disabled; launch gui --allow-writes explicitly")
            if write and not urgent and self._pending(writes=True):
                raise PermissionError("another write is pending; wait for its result")
            if action == "capture" and self.controller.allow_writes:
                raise PermissionError("capture requires a read-only session")
            queued = self._queued()
            # Standby/close never wait behind, or run before, an older ordinary write.
            # An exchange already in progress cannot be undone.
            cancel = [item for item in queued if urgent and item["action"] in ORDINARY_WRITES]
            if len(queued) >= MAX_PENDING:
                ordinary = [i for i in queued if i["action"] not in URGENT_ACTIONS]
                if not urgent or not ordinary:
                    raise PermissionError("request queue is full")
                cancel.append(ordinary[-1])
            for item in cancel:
                item.update(state="cancelled", error=f"superseded by {action}")
            self._records[request_id] = {
                "id": request_id,
                "action": action,
                "value": value,
                "confirmed": confirmed,
                "state": "queued",
                "error": None,
                "submitted_at": _utc(),
                "queued_at": self._clock(),
                "result": None,
                "transaction": None,
                "readback": None,
            }
            # Evict the oldest finished records; pending ones are bounded separately.
            finished = [key for key, item in self._records.items() if item["state"] not in ACTIVE]
            for key in finished[: max(0, len(self._records) - MAX_RECORDS)]:
                del self._records[key]
        self.wake.set()
        return request_id

    def snapshot(self) -> dict[str, Any]:
        """Copy bounded query/action evidence; safe while the acquisition caller blocks."""
        with self._lock:
            snapshot = deepcopy(
                {
                    "allow_writes": self.controller.allow_writes,
                    "power_limit_w": self.controller.power_limit_w,
                    "failed": self.controller.failed,
                    "accepting": self._accepting,
                    "polling": self._polling,
                    "write_pending": self._pending(writes=True),
                    "pending": self._pending(),
                    "queries": self._queries,
                    "actions": list(self._records.values())[-20:],
                }
            )
            return cast(dict[str, Any], json_ready(snapshot))

    def close(self) -> None:
        """Reject new work and cancel queued actions; no cleanup device commands."""
        with self._lock:
            self._accepting = False
            for item in self._queued():
                item["state"] = "cancelled"
        self.wake.set()

    def _query(self, query: str, *, capture: bool = False) -> Any:
        value = self.controller.capture(query) if capture else self.controller.get_value(query)
        with self._lock:
            self._queries[query] = {
                "value": transaction_evidence(cast(dict[str, Any], value)) if capture else value,
                "captured": capture,
                "sampled_at": _utc(),
                "transaction": transaction_evidence(self.controller.last_transaction),
            }
        return value

    def _write(self, record: dict[str, Any]) -> None:
        """Use the public API for validation; read back the serialized operand."""
        action, value = record["action"], record["value"]
        spec = ACTIONS[action]
        if not self.controller.allow_writes:
            raise PermissionError("writes disabled")
        if action not in URGENT_ACTIONS and self.monitor.latest()["health"] != "LIVE":
            raise PermissionError("a fresh overview sample is required for this write")
        if action in ("start", "shutter_open") and not record["confirmed"]:
            raise PermissionError("confirm beam path, cooling and interlock readiness")
        if (
            action != "power"
            and spec.command.endswith("=")
            and (not isinstance(value, str) or not value.strip())
        ):
            raise ValueError("enter a decimal temperature, integer lock value, or baud rate")
        if action == "power":
            self.controller.set_power_w(value)
        elif action == "baudrate":
            self.controller.set_baudrate(int(value))
        elif action == "chiller_temperature":
            self.controller.set_chiller_temperature_c(float(value))
        elif action == "front_panel_lock":
            self.controller.set_front_panel_lock(int(value))
        else:
            methods: dict[str, Callable[[], None]] = {
                "start": self.controller.start,
                "standby": self.controller.stop,
                "shutter_open": lambda: self.controller.set_shutter(open=True),
                "shutter_close": lambda: self.controller.set_shutter(open=False),
                "lbo_on": lambda: self.controller.set_lbo_heater(enabled=True),
                "lbo_off": lambda: self.controller.set_lbo_heater(enabled=False),
                "echo_on": lambda: self.controller.set_echo(enabled=True),
                "echo_off": lambda: self.controller.set_echo(enabled=False),
                "prompt_on": lambda: self.controller.set_prompt(enabled=True),
                "prompt_off": lambda: self.controller.set_prompt(enabled=False),
            }
            method = methods.get(action)
            if method is not None:
                method()
            else:
                getattr(self.controller, action)()
        record["transaction"] = transaction_evidence(self.controller.last_transaction)
        record["state"] = "acknowledged"
        if spec.query is not None:
            expected: float | None = spec.expected
            if expected is None:
                # The serialized operand: an integer baud rate or decimal watts.
                operand = record["transaction"]["instruction"].split("=")[1]
                expected = int(operand) if operand.isdigit() else float(operand)
            actual = self._query(spec.query)
            record["readback"] = {
                "query": spec.query,
                "expected": expected,
                "actual": actual,
                "matches": actual == expected,
                "transaction": transaction_evidence(self.controller.last_transaction),
            }
            record["state"] = "verified" if actual == expected else "mismatch"

    def _execute(self, record: dict[str, Any]) -> None:
        action = record["action"]
        before = self.controller.last_transaction
        try:
            if self._clock() - record["queued_at"] > MAX_QUEUE_AGE_S:
                raise PermissionError("queued action expired; submit again explicitly")
            if self.controller.failed:
                raise PermissionError("controller session failed; request cancelled")
            if action in ACTIONS:
                self._write(record)
            elif action == "polling":
                if type(record["value"]) is not bool:
                    raise ValueError("polling value must be a bool")
                self._polling = record["value"]
                record["state"] = "applied"
            elif action == "diagnostics":
                record["result"] = {}
                for query in DIAGNOSTICS.values():
                    self._drain(urgent_only=True)
                    if not self._accepting:
                        raise PermissionError("GUI session is closing")
                    record["result"][query] = self._query(query)
            else:
                capture = action == "capture"
                value = self._query(normalize_query(record["value"]), capture=capture)
                record["result"] = transaction_evidence(value) if capture else value
            if action in ("read", "capture", "diagnostics"):
                record["transaction"] = transaction_evidence(self.controller.last_transaction)
                record["state"] = "captured" if action == "capture" else "read"
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            if record["transaction"] is not None:  # An acknowledged write's readback failed.
                record["state"] = "readback_failed"
                record["readback"] = {
                    "error": record["error"],
                    "transaction": transaction_evidence(self.controller.last_transaction),
                }
            else:
                if (latest := self.controller.last_transaction) != before:
                    record["transaction"] = transaction_evidence(latest)
                # Exception type alone cannot tell us whether a write reached the
                # laser. Even ValueError can originate in the adapter after a write.
                transaction = record["transaction"]
                rejected = (
                    isinstance(exc, (PermissionError, ValueError))
                    if transaction is None
                    else transaction["outcome"] == "rejected"
                )
                record["state"] = "rejected" if rejected else "failed"
        finally:
            if record["state"] == "running":  # Interrupted by a BaseException.
                record["state"] = "failed"
            with self._lock:
                record["finished_at"] = _utc()
                self._records[record["id"]] = record

    def _drain(self, *, urgent_only: bool = False) -> bool:
        """Execute bounded queued work, urgent first; report whether any write ran."""
        writes = self._writes
        for _ in range(MAX_PENDING):
            with self._lock:
                queued = self._queued()
                if not queued or not self._accepting:
                    break
                urgent = [item for item in queued if item["action"] in URGENT_ACTIONS]
                if urgent_only and not urgent:
                    break
                original = (urgent or queued)[0]
                original["state"] = "running"
                record = dict(original)  # Readers never observe a partly updated result.
            self._execute(record)
            # Count attempted exchanges only; a write refused before I/O changes nothing.
            self._writes += record["action"] in ACTIONS and record["transaction"] is not None
        return self._writes != writes


class Monitor:
    """Own the cache and request queue, but never the connection or a thread.

    The launcher calls poll_once and wait on one worker. Browser callbacks use
    latest, power_history and controls; none of these wait for serial I/O.
    """

    def __init__(
        self,
        controller: VerdiController,
        *,
        interval_s: float = 1.0,
        history_size: int = 600,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.interval_s = finite_range(interval_s, 0.001, 86400, "interval_s")
        if type(history_size) is not int or not 1 <= history_size <= 100000:
            raise ValueError("history_size must be an integer in [1, 100000]")
        self.history_size = history_size
        self._controller = controller
        self._clock = clock
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._started: float | None = None
        self._cycle_started: float | None = None
        self._version = 0
        self._lock = Lock()
        self._runner = Lock()
        self.controls = ControlSession(controller, self, clock=clock)

    def poll_once(self) -> dict[str, Any]:
        """Run queued actions, then publish one complete overview; one caller at a time.

        Paused/interrupted returns contain no status and are not published. Between
        reads, urgent requests run first. An in-flight exchange always finishes
        before another begins; we never retry an uncertain transaction.
        """
        self._cycle_started = self._clock()
        if not self._runner.acquire(blocking=False):
            raise RuntimeError("only one GUI acquisition caller is permitted")
        controls = self.controls
        try:
            controls.wake.clear()
            controls._drain()
            started = self._clock()
            sample: dict[str, Any] = {"attempted_at": _utc(), "status": None, "error": None}
            status: dict[str, Any] = {
                "model": self._controller.model,
                "simulated": self._controller.is_simulated,
                "sampled_at": sample["attempted_at"],
            }
            try:
                for field, query in STATUS_FIELDS:
                    if controls._drain():
                        # A write may change earlier fields. Discard this partial sample;
                        # never publish a mixture of before/after command readings.
                        controls.wake.set()
                        return sample | {"interrupted": True}
                    if not controls.polling:
                        return sample | {"paused": True}
                    status[field] = status_value(field, controls._query(query))
                status["duration_s"] = self._clock() - started
                sample["status"] = status
            except Exception as exc:
                sample["error"] = f"{type(exc).__name__}: {exc}".rstrip()
            return self.record(sample, started)
        finally:
            self._runner.release()

    def record(self, sample: dict[str, Any], started: float) -> dict[str, Any]:
        """Publish a complete sample; callers retain their own mutable copy.

        started is the monotonic acquisition start, so age includes slow I/O and
        publication delays. UTC timestamps are display labels only.
        """
        with self._lock:
            self._started = started
            self._history.append(deepcopy(sample))
            self._version += 1
        return sample

    def wait(self, stop: Event) -> None:
        """Keep start-to-start cadence; a browser request or close wakes us early."""
        if not stop.is_set():
            elapsed = 0 if self._cycle_started is None else self._clock() - self._cycle_started
            self.controls.wake.wait(max(0, self.interval_s - elapsed))

    def close(self) -> None:
        """Stop queue admission and wake the worker; the launcher joins and disconnects."""
        self.controls.close()

    def latest(self) -> dict[str, Any]:
        """Copy one sample and compute freshness using monotonic, not wall-clock time."""
        with self._lock:
            last = deepcopy(self._history[-1]) if self._history else None
            started = self._started
        return self._describe(last, started)

    def power_history(self, after: int = 0) -> tuple[int, list[tuple[str, Any, Any]]]:
        """Return bounded plot points newer than a browser's sample counter.

        A new/reloaded browser requests the retained history. Later refreshes send
        only new points. Failed samples produce gaps; counters never depend on UTC.
        """
        with self._lock:
            count = min(len(self._history), max(0, self._version - after))
            return self._version, [
                (item["attempted_at"], s["power_w"] if s else None, s["set_power_w"] if s else None)
                for item in list(islice(reversed(self._history), count))[::-1]
                for s in (item["status"],)
            ]

    def snapshot(self) -> dict[str, Any]:
        """Copy the complete bounded history for callers that need an export."""
        with self._lock:
            history = deepcopy(list(self._history))
            started = self._started
        return self._describe(history[-1] if history else None, started) | {"history": history}

    def _describe(self, last: dict[str, Any] | None, started: float | None) -> dict[str, Any]:
        status = last["status"] if last else None
        age = max(0.0, self._clock() - started) if started is not None and status else None
        if last is None:
            health = "NO DATA"
        elif status is None:
            health = "ERROR"
        elif age is not None and age > max(5.0, 3 * self.interval_s + 2 * status["duration_s"]):
            health = "STALE"
        else:
            health = "LIVE"
        return {
            "model": self._controller.model,
            "simulated": self._controller.is_simulated,
            "health": health,
            "error": last["error"] if last else None,
            "status": status,
            "age_s": age,
        }


# Overview rows: label, element id, text without a sample, and a status formatter.
# The configured model (None) is shown with or without a sample.
READINGS: list[tuple[str, str, str, Callable[[dict[str, Any]], str] | None]] = [
    ("Measured power / W", "power", "—", lambda s: f"{s['power_w']:.3f}"),
    ("Setpoint / W", "setpoint", "—", lambda s: f"{s['set_power_w']:.4f}"),
    ("Laser", "laser", "UNKNOWN", lambda s: QUERY_INFO["?L"].labels[s["laser_state"]]),
    ("Safety shutter", "shutter", "UNKNOWN", lambda s: "OPEN" if s["shutter_open"] else "CLOSED"),
    ("Configured model", "model", "", None),
    ("Keyswitch", "keyswitch", "UNKNOWN", lambda s: "ON" if s["keyswitch_on"] else "OFF"),
    ("Diode current / A", "current", "—", lambda s: f"{s['diode_current_a']:.1f}"),
    ("LBO servo", "servo", "—", lambda s: display_value("?LBOSS", s["lbo_servo"])),
    ("Reported faults", "faults", "Unknown", lambda s: display_value("?F", s["faults"])),
] + [
    (f"{label} / °C", field, "—", lambda s, field=field: f"{s[field]:.2f}")
    for label, field in (
        ("Diode 1", "diode_temp_c"),
        ("Heatsink", "heatsink_temp_c"),
        ("Baseplate", "baseplate_temp_c"),
        ("LBO", "lbo_temp_c"),
        ("Etalon", "etalon_temp_c"),
        ("Vanadate", "vanadate_temp_c"),
    )
]


def describe_action(item: dict[str, Any]) -> str:
    """One-line operator summary; the full record is shown as transaction evidence."""
    readback, result = item["readback"], item["result"]
    if item["error"]:
        return str(item["error"])
    if readback and "actual" in readback:
        query = readback["query"]
        expected = display_value(query, readback["expected"])
        return f"Requested {expected}; read back {_reading(query, readback['actual'])}"
    if item["action"] == "read" and item["state"] == "read":
        query = item["transaction"]["instruction"]
        return f"{query}: {_reading(query, result)}"
    if item["state"] == "acknowledged":
        return "Acknowledged. No documented readback confirms this action or its completion."
    if item["state"] == "captured":
        if result["payload"] is None and "payload_hex" in result:
            return f"Captured bytes: {bytes.fromhex(result['payload_hex'])!r}"
        return f"Captured payload: {result['payload']!r}"
    if item["action"] == "diagnostics" and result:
        return " · ".join(f"{QUERY_INFO[q].name}: {_reading(q, v)}" for q, v in result.items())
    return str(item["state"])


def action_label(action: str) -> str:
    """Operator-facing name; queue records keep the stable action key."""
    if action in ACTIONS:
        return ACTIONS[action].label
    return {"read": "Read query", "capture": "Raw capture", "polling": "Overview polling"}.get(
        action, action.capitalize()
    )


def lcd_lines(data: dict[str, Any]) -> tuple[str, str]:
    """Synthesize the two-line display from Monitor.latest(); the laser's LCD is not readable."""
    status = data["status"]
    light = "-.---" if status is None else f"{status['power_w']:.3f}"
    first = f"LIGHT{light:>13} W"
    if status is None:
        second = "COMM ERROR" if data["health"] == "ERROR" else data["health"]
    elif data["health"] == "STALE":
        second = "STALE SAMPLE"
    elif status["faults"]:
        second = "FAULT " + ",".join(map(str, status["faults"]))
    else:
        laser = QUERY_INFO["?L"].labels[status["laser_state"]]
        second = f"{laser:<8}SET{status['set_power_w']:>8.4f}W"
    return first[:LCD_WIDTH].ljust(LCD_WIDTH), second[:LCD_WIDTH].ljust(LCD_WIDTH)


def panel_lamps(data: dict[str, Any]) -> dict[str, str]:
    """Indicator classes; anything not backed by a sample is 'unknown', never 'off'."""
    status = data["status"]

    def lamp(lit: bool | None) -> str:
        return "led unknown" if lit is None else "led on" if lit else "led"

    return {
        # Inferred from serial replies; the protocol has no AC-power query.
        "ac": lamp(True if data["health"] == "LIVE" else None),
        "emission": lamp(None if status is None else status["laser_state"] == 1),
        "shutter": lamp(None if status is None else status["shutter_open"]),
        "key": "unknown" if status is None else "on" if status["keyswitch_on"] else "off",
        "shown": "unknown" if status is None else "open" if status["shutter_open"] else "closed",
    }


def shutter_toggle(shown: Any, data: dict[str, Any]) -> str:
    """Open only when the browser showed CLOSED and the latest live sample agrees."""
    status = data["status"]
    closed = data["health"] == "LIVE" and status is not None and not status["shutter_open"]
    return "shutter_open" if shown == "closed" and closed else "shutter_close"


def create_app(monitor: Monitor) -> Any:
    """Build the view. The caller owns polling, connection lifetime and the server."""
    import dash_bootstrap_components as dbc
    from dash import Dash, Input, Output, State, ctx, dcc, html, no_update

    controls = monitor.controls
    settings = controls.snapshot()
    writable = settings["allow_writes"]
    app = Dash(__name__, assets_folder=str(Path(__file__).with_name("assets")))
    app.title = "Verdi control"
    source = "SIMULATOR" if monitor.latest()["simulated"] else "PHYSICAL / UNVALIDATED"

    def attrs(**names: Any) -> dict[str, Any]:
        """Dash accepts aria-*/data-* props only as keyword strings."""
        return {name.replace("_", "-"): value for name, value in names.items()}

    def button(
        label: str,
        identifier: str,
        *,
        tone: str = "secondary",
        solid: bool = False,
        disabled: bool = False,
    ) -> Any:
        return dbc.Button(
            label,
            id=identifier,
            n_clicks=0,
            disabled=disabled,
            color=tone,
            outline=not solid,
            size="sm",
        )

    def row(*buttons: Any) -> Any:
        return html.Div(list(buttons), className="button-row")

    def card(title: str, *children: Any, subtitle: str = "") -> Any:
        heading: list[Any] = [html.H2(title, className="card-heading")]
        if subtitle:
            heading.append(html.P(subtitle, className="card-subtitle"))
        return dbc.Card(dbc.CardBody([html.Header(heading), *children]), className="surface")

    def field(text: str, identifier: str) -> Any:
        return dbc.Label(text, html_for=identifier, className="field-label")

    def dropdown(identifier: str, options: dict[str, str], value: str) -> Any:
        choices = [{"label": label, "value": key} for key, label in options.items()]
        return dcc.Dropdown(id=identifier, options=choices, value=value, clearable=False)

    def table(head: tuple[str, ...], rows: list[list[Any]]) -> Any:
        header = [html.Thead(html.Tr([html.Th(text) for text in head]))] if head else []
        body = html.Tbody([html.Tr(cells) for cells in rows])
        return dbc.Table([*header, body], size="sm", hover=True, className="data-table")

    def locked(identifier: str, children: list[Any]) -> Any:
        """A write group that the server and the watchdog can both disable."""
        return html.Fieldset(
            children,
            id=identifier,
            disabled=not writable,
            className="write-group",
            **attrs(data_server_disabled=str(not writable).lower()),
        )

    traces: list[dict[str, Any]] = [
        {
            "x": [],
            "y": [],
            "name": name,
            "mode": "lines",
            "connectgaps": False,
            "line": {"color": color, "width": 2, "dash": dash, "shape": "hv"},
        }
        for name, color, dash in (("Measured", "#12b76a", "solid"), ("Setpoint", "#98a2b3", "dot"))
    ]
    axis = {"gridcolor": "#eef0f3", "zeroline": False, "linecolor": "#e4e7ec"}
    figure_layout = {
        "uirevision": "power",
        "height": 260,
        "margin": {"l": 44, "r": 8, "t": 8, "b": 32},
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "Inter, system-ui, sans-serif", "size": 11, "color": "#667085"},
        "legend": {"orientation": "h", "x": 0, "y": 1.12},
        "xaxis": axis,
        "yaxis": axis | {"title": {"text": "W"}, "rangemode": "tozero"},
    }
    ready = [{"label": "Beam path, cooling and interlocks checked", "value": "ready"}]
    limit = settings["power_limit_w"]
    operate = locked(
        "write-controls",
        [
            html.Legend("Remote operation", className="visually-hidden"),
            dbc.Checklist(
                id="operator-ready", options=ready, value=[], switch=True, className="ready"
            ),
            html.Div("Laser", className="group-label"),
            row(
                button("Start / reset faults", "start", tone="primary"),
                button("Standby", "standby", tone="danger", solid=True),
            ),
            html.Div("Shutter", className="group-label"),
            row(
                button("Open", "shutter-open", tone="primary"),
                button("Close", "shutter-close", tone="danger", solid=True),
            ),
            field("Target power", "target-power"),
            dbc.InputGroup(
                [
                    dbc.Input(
                        id="target-power", type="number", min=0, max=limit, step=0.0001, value=0
                    ),
                    dbc.InputGroupText("W"),
                    button("Apply", "apply-power", tone="primary", solid=True),
                ],
                size="sm",
            ),
            dbc.FormText(
                "Start and Open need the readiness switch. Start resets faults and clears "
                "fault history; read diagnostics first."
            ),
        ],
    )
    service = locked(
        "service-controls",
        [
            html.Legend("Service commands", className="visually-hidden"),
            field("Command", "service-action"),
            dropdown("service-action", SERVICE_ACTIONS, "lbo_on"),
            field("Operand (when needed)", "service-value"),
            dbc.InputGroup(
                [
                    dbc.Input(
                        id="service-value",
                        type="text",
                        value="",
                        placeholder="°C, baud rate, or LFP integer",
                    ),
                    button("Send", "service", tone="primary"),
                ],
                size="sm",
            ),
            dbc.FormText(
                "Chiller: Coherent part 1037271 only; temperature range unspecified. "
                "Panel-lock values and baud acknowledgment timing need verification. "
                "FLASH and optimization report initiation, not completion. "
                "Echo/prompt have no readback."
            ),
        ],
    )

    def legend(text: str) -> Any:
        return html.Span(text, className="legend")

    def led(identifier: str) -> Any:
        return html.Span(id=identifier, className="led unknown")

    def key(identifier: str, label: str, title: str, *face: Any) -> Any:
        return html.Button(
            list(face),
            id=identifier,
            n_clicks=0,
            className="panel-key",
            title=title,
            **attrs(aria_label=label),
        )

    def pushbutton(identifier: str, label: str, title: str, *face: Any) -> Any:
        face_key = key(identifier, label, title, *face)
        return html.Div([legend(label), face_key], className="pushbutton")

    def level(number: int) -> Any:
        return html.Div(
            [
                pushbutton(
                    f"panel-level-{number}",
                    f"POWER LEVEL {number}",
                    f"Apply preset {number}; presets are stored in this browser, not the laser",
                    led(f"panel-level-{number}-led"),
                ),
                html.Label(
                    f"Power level {number} preset / W",
                    htmlFor=f"panel-level-{number}-value",
                    className="visually-hidden",
                ),
                dcc.Input(
                    id=f"panel-level-{number}-value",
                    type="number",
                    min=0,
                    max=limit,
                    step=0.0001,
                    placeholder="W",
                    persistence=True,
                    persistence_type="local",
                    className="preset",
                ),
            ],
            className="level",
        )

    menu = "Presses the laser's own {}; its menu screen is not readable over RS-232"
    panel = html.Fieldset(
        [
            html.Legend("Verdi front panel", className="visually-hidden"),
            html.Div(
                [
                    html.Span("COHERENT", className="brand"),
                    html.Span(className="rule"),
                    html.Span(f"VERDI {monitor.latest()['model']}", className="model"),
                ],
                className="panel-logo",
                **attrs(aria_hidden="true"),
            ),
            html.Div(
                [
                    html.Div(
                        [legend("AC ON"), led("panel-ac")],
                        className="lamp",
                        title="Lit while the laser answers serial queries (no AC-power query)",
                    ),
                    html.Div(
                        [
                            html.Span("STANDBY", className="legend standby"),
                            html.Span("ON", className="legend on"),
                            html.Div(
                                html.Span(className="blade"),
                                id="panel-key",
                                className="keyswitch unknown",
                                role="img",
                                title="Key switch (?K) · read-only: turn the physical key",
                            ),
                        ],
                        className="keyswitch-plate",
                    ),
                ],
                className="panel-power",
            ),
            html.Div(
                [legend("LASER EMISSION"), led("panel-emission")],
                className="lamp panel-emission",
                title="Lit while ?L reports ON",
            ),
            html.Div(
                id="panel-display",
                className="lcd",
                title="Synthesized from RS-232 queries, not a copy of the laser's display",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            legend("MENU UP"),
                            key("panel-menu-up", "MENU UP", menu.format("MENU UP"), "▲"),
                            key("panel-menu-down", "MENU DOWN", menu.format("MENU DOWN"), "▼"),
                            legend("MENU DOWN"),
                        ],
                        className="menu-arrows",
                    ),
                    pushbutton("panel-select", "MENU SELECT", menu.format("MENU SELECT")),
                    pushbutton("panel-exit", "MENU EXIT", menu.format("MENU EXIT")),
                    pushbutton(
                        "panel-shutter",
                        "SHUTTER OPEN",
                        "Toggle the shutter. Opening needs the readiness confirmation below "
                        "and agreement with the latest live sample; otherwise this closes it.",
                        led("panel-shutter-led"),
                    ),
                ],
                className="panel-buttons",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            legend("DISPLAY CONTRAST"),
                            html.Span(
                                id="panel-contrast",
                                className="trimmer",
                                role="button",
                                tabIndex="0",
                                title="Cycle the virtual display contrast (this browser only)",
                                **attrs(aria_label="Display contrast"),
                            ),
                        ],
                        className="contrast",
                    ),
                    html.Div(
                        [
                            legend("POWER ADJUST"),
                            html.Div(
                                html.Span(className="notch"),
                                id="panel-knob",
                                className="knob",
                                role="slider",
                                tabIndex="0",
                                title="Drag, scroll or use arrow keys (Shift ×10) to edit "
                                "the target; SET POWER sends it",
                                **attrs(
                                    aria_label="Power adjust: target power / W",
                                    aria_valuemin=0,
                                    aria_valuemax=limit,
                                    aria_valuenow=0,
                                    data_max=limit,
                                ),
                            ),
                            html.Span(id="panel-target", className="knob-readout"),
                            html.Button(
                                "SET POWER", id="panel-apply-power", n_clicks=0, className="set"
                            ),
                        ],
                        className="adjust",
                    ),
                ],
                className="panel-adjust",
            ),
            html.Div([level(1), level(2)], className="panel-levels"),
        ],
        id="front-panel",
        className="front-panel stale",
        disabled=not writable,
        **attrs(data_server_disabled=str(not writable).lower()),
    )
    panel_note = html.P(
        "Panel replica. The display is synthesized from queries; MENU keys press the laser's "
        "own buttons, whose menu screen cannot be read back. POWER ADJUST only edits the "
        "target, and POWER LEVEL presets live in this browser. The key switch is read-only.",
        className="panel-note",
    )

    queries = {
        q: f"{q} · {spec.name}" + (f" / {display_unit(q)}" if display_unit(q) else "")
        for q, spec in QUERY_INFO.items()
    }
    diagnostics = card(
        "Queries and diagnostics",
        field("Documented query", "query-choice"),
        dropdown("query-choice", queries, "?SV"),
        row(
            button("Read", "read", tone="primary"),
            button("Capture raw", "capture", disabled=writable),
            button("Diagnostics + fault history", "diagnostics"),
        ),
        dbc.FormText(
            "Capture keeps payload/wire evidence uninterpreted and needs a read-only session. "
            "For a first connection, launch gui --commission to start with polling paused."
        ),
        html.Div(
            [
                html.Div(id="polling-state", className="muted"),
                row(
                    button("Pause overview", "pause-polling"),
                    button("Resume overview", "resume-polling"),
                ),
            ],
            className="polling",
        ),
        html.Div(id="query-results"),
    )
    header = html.Header(
        [
            html.Div(
                [
                    html.H1("Verdi control", className="app-title"),
                    html.Span(f"Coherent Verdi {monitor.latest()['model']}", className="muted"),
                ],
                className="app-brand",
            ),
            html.Div(
                [
                    dbc.Badge(source, id="source", className="chip"),
                    dbc.Badge(
                        f"Writes enabled · ≤ {limit:g} W"
                        if writable
                        else "Read-only · launch with --allow-writes",
                        id="permission-label",
                        className="chip chip-armed" if writable else "chip",
                    ),
                    html.Span("NO DATA", id="header-health", className="health-pill nodata"),
                ],
                className="app-status",
            ),
        ],
        className="app-header",
    )
    remote = card(
        "Remote operation",
        operate,
        html.Div(
            [
                html.Div(id="submission", role="status", className="submission"),
                html.Div(id="latest-action", className="latest-action"),
            ],
            className="feedback",
        ),
        subtitle="Interlocked controls the physical panel does not have",
    )
    graph = dcc.Graph(
        id="power-graph",
        figure={"data": traces, "layout": figure_layout},
        config={"displayModeBar": False, "responsive": True},
    )
    activity = card(
        "Activity",
        html.Div(id="action-results"),
        subtitle="Shared across browser tabs. Acknowledged means protocol acceptance; verified "
        "means the documented query matches. Neither proves physical execution.",
    )

    def layout() -> Any:
        # Inputs live outside refreshed results so an unsent edit survives polling.
        return html.Main(
            dbc.Container(
                [
                    header,
                    html.Div(id="connection-warning", role="alert"),
                    dcc.Store(id="browser-session", data=controls.new_client()),
                    dcc.Store(id="panel-setpoint"),
                    dcc.Store(id="history-cursor", data=0),
                    dcc.Store(id="action-request"),
                    dbc.Row(
                        [
                            dbc.Col(
                                html.Section([panel, panel_note], className="panel-wrap"), xl=8
                            ),
                            dbc.Col(remote, xl=4),
                        ],
                        className="g-4",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(card("Live readings", html.Section(id="sample")), lg=5),
                            dbc.Col(card("Power history", graph), lg=7),
                        ],
                        className="g-4",
                    ),
                    dbc.Row(
                        [
                            dbc.Col(diagnostics, lg=7),
                            dbc.Col(
                                card(
                                    "Service commands",
                                    service,
                                    subtitle="Documented RS-232 commands without a panel key",
                                ),
                                lg=5,
                            ),
                        ],
                        className="g-4",
                    ),
                    dbc.Row(dbc.Col(activity), className="g-4"),
                    html.Footer(
                        "Reported state is not a safety guarantee · standby is not full shutdown",
                        className="app-footer",
                    ),
                    dcc.Interval(id="refresh", interval=1000),
                    dcc.Interval(id="action-refresh", interval=200, disabled=True),
                    html.Span(id="server-heartbeat", hidden=True),
                ],
                fluid="xxl",
            ),
            id="dashboard",
        )

    app.layout = layout

    @app.callback(
        Output("sample", "children"),
        Output("server-heartbeat", "children"),
        Output("power-graph", "extendData"),
        Output("history-cursor", "data"),
        Output("front-panel", "className"),
        Output("panel-display", "children"),
        [Output(f"panel-{name}", "className") for name in ("ac", "emission", "shutter-led", "key")],
        Output("panel-shutter", "data-shown"),
        Output("panel-setpoint", "data"),
        Output("header-health", "children"),
        Output("header-health", "className"),
        Input("refresh", "n_intervals"),
        State("history-cursor", "data"),
    )
    def refresh(tick: int, cursor: Any) -> tuple[Any, ...]:
        data = monitor.latest()
        status = data["status"]
        lamps = panel_lamps(data)
        version, points = monitor.power_history(
            cursor if type(cursor) is int and cursor >= 0 else 0
        )
        plot = {
            "x": [[point[0] for point in points]] * 2,
            "y": [[point[index] for point in points] for index in (1, 2)],
        }
        readings = [
            [
                html.Th(label),
                html.Td(
                    data["model"] if show is None else show(status) if status else missing,
                    id=identifier,
                ),
            ]
            for label, identifier, missing, show in READINGS
        ]
        age = "No current sample" if data["age_s"] is None else f"Sample age {data['age_s']:.1f} s"
        health = data["health"]
        pill = health if data["age_s"] is None else f"{health} · {data['age_s']:.1f} s"
        return (
            [
                html.P(
                    [html.Strong(health, id="health"), " · ", age], className="sample-age muted"
                ),
                html.Div(data["error"] or "", id="error", role="alert"),
                table((), readings),
            ],
            tick,
            (plot, [0, 1], monitor.history_size) if points else no_update,
            version,
            "front-panel" if data["health"] == "LIVE" else "front-panel stale",
            [html.Div(line) for line in lcd_lines(data)],
            lamps["ac"],
            lamps["emission"],
            lamps["shutter"],
            f"keyswitch {lamps['key']}",
            lamps["shown"],
            status["set_power_w"] if status else None,
            pill,
            "health-pill " + health.lower().replace(" ", ""),
        )

    @app.callback(
        Output("submission", "children"),
        Output("action-request", "data"),
        inputs={
            "clicks": {name: Input(name, "n_clicks") for name in BUTTONS},
            "client": State("browser-session", "data"),
            "power": State("target-power", "value"),
            "ready": State("operator-ready", "value"),
            "service": State("service-action", "value"),
            "operand": State("service-value", "value"),
            "query": State("query-choice", "value"),
            "level_1": State("panel-level-1-value", "value"),
            "level_2": State("panel-level-2-value", "value"),
            "shown": State("panel-shutter", "data-shown"),
        },
        prevent_initial_call=True,
    )
    def submit(
        clicks: dict[str, int],
        client: str,
        power: Any,
        ready: Any,
        service: str,
        operand: str,
        query: str,
        level_1: Any,
        level_2: Any,
        shown: Any,
    ) -> tuple[str, Any]:
        """Translate one explicit click into a queued request; never perform I/O."""
        trigger = ctx.triggered_id
        if trigger not in BUTTONS:
            return "", no_update
        action = service if trigger == "service" else BUTTONS[trigger]
        if trigger == "panel-shutter":
            action = shutter_toggle(shown, monitor.latest())
        values = {
            "service": operand,
            "apply-power": power,
            "panel-apply-power": power,
            "panel-level-1": level_1,
            "panel-level-2": level_2,
            "read": query,
            "capture": query,
        }
        value = trigger == "resume-polling" if action == "polling" else values.get(trigger)
        if trigger.startswith("panel-level-") and value is None:
            return "Enter this POWER LEVEL preset (W) below its key first", no_update
        confirmed = isinstance(ready, list) and "ready" in ready
        try:
            request_id = controls.submit(
                client, trigger, clicks[trigger], action, value, confirmed=confirmed
            )
            return f"Queued: {action_label(action)}", request_id
        except (ValueError, PermissionError) as exc:
            return str(exc), no_update

    @app.callback(
        Output("query-results", "children"),
        Output("action-results", "children"),
        Output("latest-action", "children"),
        [Output(name, "disabled") for name in WRITE_GROUPS],
        [Output(name, "data-server-disabled") for name in WRITE_GROUPS],
        Output("polling-state", "children"),
        [Output(name, "disabled") for name in FRESH_BUTTONS],
        Output("action-refresh", "disabled"),
        Input("refresh", "n_intervals"),
        Input("action-request", "data"),
        Input("action-refresh", "n_intervals"),
    )
    def refresh_controls(tick: int, request: Any, action_tick: int) -> tuple[Any, ...]:
        data = controls.snapshot()
        disabled = not data["allow_writes"] or data["failed"] or not data["accepting"]
        require_fresh = disabled or data["write_pending"] or monitor.latest()["health"] != "LIVE"
        queries = [
            [
                html.Td(query, className="mono"),
                html.Td(QUERY_INFO[query].name),
                html.Td(
                    "Raw capture (see evidence)"
                    if item["captured"]
                    else display_value(query, item["value"])
                ),
                html.Td(display_unit(query), className="muted"),
                html.Td(item["sampled_at"][11:23], title=item["sampled_at"], className="muted"),
            ]
            for query, item in data["queries"].items()
        ]

        def badge(item: dict[str, Any]) -> Any:
            tone = STATE_TONES.get(item["state"], "secondary")
            return dbc.Badge(item["state"], color=tone, className="state")

        results = [
            html.Details(
                [
                    html.Summary(
                        [
                            badge(item),
                            html.Span(action_label(item["action"]), className="action-name"),
                            html.Span(
                                item.get("finished_at", item["submitted_at"])[11:19],
                                className="muted",
                            ),
                        ]
                    ),
                    html.P(describe_action(item)),
                    html.Details(
                        [
                            html.Summary("Transaction evidence"),
                            html.Pre(json.dumps(item, indent=2, allow_nan=False)),
                        ],
                        className="evidence",
                    ),
                ],
                open=index == 0,
                className="activity-item",
            )
            for index, item in enumerate(reversed(data["actions"]))
        ]
        latest = data["actions"][-1] if data["actions"] else None
        return (
            table(("Query", "Name", "Value", "Unit", "UTC"), queries)
            if queries
            else html.P("No query results yet.", className="muted empty"),
            results or html.P("No actions yet.", className="muted empty"),
            [badge(latest), " ", action_label(latest["action"]), " · ", describe_action(latest)]
            if latest
            else "",
            *([disabled] * len(WRITE_GROUPS)),
            *([str(disabled).lower()] * len(WRITE_GROUPS)),
            "Overview polling active"
            if data["polling"]
            else "Overview polling paused · query results have individual acquisition times",
            *([require_fresh] * len(FRESH_BUTTONS)),
            not data["pending"],
        )

    # Browser-only presentation; registered after the server callbacks (see conftest).
    clientside: Any = app.clientside_callback  # Untyped in Dash.
    clientside(
        "function (value) { const max = "
        + json.dumps(limit)
        + """;
            const ok = typeof value === "number" && isFinite(value);
            const fraction = ok && max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
            return [
                {"--level": fraction},
                ok ? value : 0,
                ok ? "TARGET " + value.toFixed(4) + " W" : "TARGET —",
            ];
        }
        """,
        Output("panel-knob", "style"),
        Output("panel-knob", "aria-valuenow"),
        Output("panel-target", "children"),
        Input("target-power", "value"),
    )
    clientside(
        """
        function (setpoint, first, second) {
            // Lit while the reported setpoint matches the preset at the wire's 4 decimals.
            return [first, second].map(function (preset) {
                if (typeof preset !== "number" || typeof setpoint !== "number") return "led";
                return Math.abs(setpoint - preset) < 5e-5 ? "led on" : "led";
            });
        }
        """,
        Output("panel-level-1-led", "className"),
        Output("panel-level-2-led", "className"),
        Input("panel-setpoint", "data"),
        Input("panel-level-1-value", "value"),
        Input("panel-level-2-value", "value"),
    )

    return app
