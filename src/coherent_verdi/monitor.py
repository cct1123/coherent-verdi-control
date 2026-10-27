"""Caller-scheduled telemetry and the bounded GUI request queue.

This module owns cached samples and action evidence, with no Dash dependency.
Only poll_once touches the controller; connection lifetime belongs to the caller.
"""

from collections import OrderedDict, deque
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from itertools import islice
from math import isfinite
from threading import Event, Lock
from time import monotonic
from typing import TYPE_CHECKING, Any, NamedTuple, cast
from uuid import uuid4

from .controller import (
    DIAGNOSTICS,
    STATUS_FIELDS,
    VerdiController,
    VerdiError,
    finite_range,
    json_ready,
    normalize_query,
    status_value,
    transaction_evidence,
    validate_power_w,
)

if TYPE_CHECKING:
    from .gui import GuiSession


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
    "baudrate": Action("Change baud rate", "B=", "?B"),
    "echo_on": Action("Echo ON", "E=1"),
    "echo_off": Action("Echo OFF", "E=0"),
    "prompt_on": Action("Prompt ON", "PROMPT=0"),
    "prompt_off": Action("Prompt OFF", "PROMPT=1"),
}
OPERATE = ("power", "start", "standby", "shutter_open", "shutter_close")
MENU_ACTIONS = {"menu_up", "menu_down", "menu_select", "exit_screen", "knob_down"}
MENU_DISABLED_REASON = (
    "Menu navigation is disabled: the current menu and selection cannot be read over RS-232."
)
SERVICE_ACTIONS = {
    name: spec.label
    for name, spec in ACTIONS.items()
    if name not in OPERATE and name not in MENU_ACTIONS
}
KNOWN_ACTIONS = {*ACTIONS, "read", "capture", "diagnostics", "polling", "interval"}
URGENT_ACTIONS = {"standby", "shutter_close"}
ORDINARY_WRITES = ACTIONS.keys() - URGENT_ACTIONS
# Dash button id -> queued action; the service button sends the selected action.
_SAME_NAMES = "start standby shutter-open shutter-close service read capture diagnostics"
BUTTONS = {
    "apply-power": "power",
    "pause-polling": "polling",
    "resume-polling": "polling",
    "apply-interval": "interval",
} | {name: name.replace("-", "_") for name in _SAME_NAMES.split()}
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
CHANNELS = set(BUTTONS)
ACTIVE = ("queued", "running")
# Bound memory and how long one drain can postpone the overview.
MAX_PENDING = 16
MAX_RECORDS = 128
MAX_CLIENTS = 64
MAX_QUEUE_AGE_S = 10


def _utc() -> str:
    return datetime.now(UTC).isoformat()


class RequestQueue:
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
        generation: int | None = None,
    ) -> str:
        """Admit one explicit user action, with per-browser/channel deduplication."""
        if isinstance(action, str) and action in MENU_ACTIONS:
            raise PermissionError(MENU_DISABLED_REASON)
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
            if generation is not None and (
                type(generation) is not int or generation != self.monitor.generation
            ):
                raise PermissionError("connection changed; wait for the view to refresh")
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
            if action == "power":
                value = validate_power_w(value, self.controller.power_limit_w)
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
            self._polling = False
            for item in self._queued():
                item["state"] = "cancelled"
        self.wake.set()

    def _query(self, query: str, *, capture: bool = False) -> Any:
        value = self.controller.get_capture(query) if capture else self.controller.get_value(query)
        transaction = transaction_evidence(self.controller.last_transaction)
        with self._lock:
            self._queries[query] = {
                "value": transaction_evidence(cast(dict[str, Any], value)) if capture else value,
                "captured": capture,
                "sampled_at": _utc(),
                "transaction": transaction,
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
            self.controller.set_value(spec.command)
        transaction = self.controller.last_transaction
        record["transaction"] = transaction_evidence(transaction)
        if self.monitor.session is not None and transaction is not None:
            self.monitor.session.remember_link_settings(transaction["instruction"])
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
                if record["value"] and self.monitor.session is not None:
                    self.monitor.session.require_monitoring()
                self._polling = record["value"]
                record["state"] = "applied"
            elif action == "interval":
                self.monitor.interval_s = finite_range(record["value"], 0.1, 3600, "interval_s")
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
                attached = exc.transaction if isinstance(exc, VerdiError) else None
                latest = attached if attached is not None else self.controller.last_transaction
                if attached is not None or latest != before:
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
        polling: bool = True,
        interval_s: float = 1.0,
        history_size: int = 600,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.interval_s = finite_range(interval_s, 0.001, 86400, "interval_s")
        if type(history_size) is not int or not 1 <= history_size <= 100000:
            raise ValueError("history_size must be an integer in [1, 100000]")
        self.history_size = history_size
        self._clock = clock
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._started: float | None = None
        self._cycle_started: float | None = None
        self._version = 0
        self._generation = 0
        self._lock = Lock()
        self._runner = Lock()
        self.controls = RequestQueue(controller, self, clock=clock)
        self.controls._polling = polling
        self.session: GuiSession | None = None

    @property
    def controller(self) -> VerdiController:
        return self.controls.controller

    @property
    def generation(self) -> int:
        """Connection identity for rejecting submissions from an older browser view."""
        return self._generation

    def reset(self, controller: VerdiController, *, accepting: bool = False) -> None:
        """Replace a released connection and its caches on the acquisition worker.

        Keep browser click counters so an old submission cannot be replayed after
        reconnecting. Every new connection starts with monitoring paused.
        """
        with self._runner, self._lock, self.controls._lock:
            self.controls.controller = controller
            self.controls._accepting = accepting
            self.controls._polling = False
            self.controls._queries.clear()
            self.controls._records.clear()
            self._history.clear()
            self._started = None
            self._cycle_started = None
            self._version += 1
            self._generation += 1

    def poll_once(self) -> dict[str, Any]:
        """Run queued actions, then publish one complete overview; one caller at a time.

        Paused/interrupted returns contain no status and are not published. Between
        reads, urgent requests run first. An in-flight exchange always finishes
        before another begins; we never retry an uncertain transaction.
        """
        if not self._runner.acquire(blocking=False):
            raise RuntimeError("only one GUI acquisition caller is permitted")
        self._cycle_started = self._clock()
        controls = self.controls
        try:
            controls.wake.clear()
            controls._drain()
            started = self._clock()
            sample: dict[str, Any] = {"attempted_at": _utc(), "status": None, "error": None}
            status: dict[str, Any] = {
                "model": self.controller.model,
                "simulated": self.controller.is_simulated,
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
            # Age includes acquisition time. Publish a separate copy for cache readers.
            with self._lock:
                self._started = started
                self._history.append(deepcopy(sample))
                self._version += 1
            return sample
        finally:
            self._runner.release()

    def wait(self, stop: Event) -> None:
        """Keep start-to-start cadence; a browser request or close wakes us early."""
        if not stop.is_set():
            elapsed = (
                self._clock() - self._cycle_started
                if self.controls.polling and self._cycle_started is not None
                else 0
            )
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
            "model": self.controller.model,
            "simulated": self.controller.is_simulated,
            "health": health,
            "error": last["error"] if last else None,
            "status": status,
            "age_s": age,
        }
