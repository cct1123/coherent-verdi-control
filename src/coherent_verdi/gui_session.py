"""Bounded GUI request queue. Only the polling caller touches the controller."""

from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from math import isfinite
from threading import Event, Lock
from time import monotonic
from typing import TYPE_CHECKING, Any, NamedTuple, cast
from uuid import uuid4

from .catalogue import STATE_CODES, STATUS_FIELDS
from .controller import VerdiController, normalize_query, transaction_evidence

if TYPE_CHECKING:
    from .gui import Monitor


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
SERVICE_ACTIONS = {
    name: spec.label
    for name, spec in ACTIONS.items()
    if name not in ("power", "start", "standby", "shutter_open", "shutter_close")
}
WRITE_ACTIONS = ACTIONS.keys()
READ_ACTIONS = {"read", "capture", "diagnostics", "polling"}
URGENT_ACTIONS = {"standby", "shutter_close"}
# Bound memory and how long one drain can postpone the overview.
MAX_PENDING = 16
MAX_RECORDS = 128
MAX_CLIENTS = 64
MAX_QUEUE_AGE_S = 10


def display_value(query: str, value: Any) -> str:
    if query in STATE_CODES and type(value) is int:
        return f"{value} · {STATE_CODES[query].get(value, 'UNKNOWN')}"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "None reported"
    return str(value)


class ControlSession:
    """Shared queue and action evidence; construction starts no worker or I/O.

    One caller invokes poll_once (normally through Monitor). Browser callbacks
    only submit requests or copy snapshots, including while device I/O is blocked.
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
        self._runner = Lock()
        self.wake = Event()
        self._clients: OrderedDict[str, dict[str, int]] = OrderedDict()
        self._records: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._pending: list[str] = []
        self._pending_writes: set[str] = set()
        self._accepting = True
        self._polling = True
        self._queries: dict[str, Any] = {}

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
        with self._lock:
            self._polling = False

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
        if not isinstance(action, str) or action not in WRITE_ACTIONS | READ_ACTIONS:
            raise ValueError("unknown GUI action")
        if not isinstance(channel, str) or channel not in {
            "read",
            "capture",
            "diagnostics",
            "apply-power",
            "start",
            "standby",
            "shutter-open",
            "shutter-close",
            "service",
            "polling",
            "pause-polling",
            "resume-polling",
        }:
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
        write = action in WRITE_ACTIONS
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
            urgent = action in URGENT_ACTIONS
            if write and self._pending_writes and not urgent:
                raise PermissionError("another write is pending; wait for its result")
            if action == "capture" and self.controller.allow_writes:
                raise PermissionError("capture requires a read-only session")
            if len(self._pending) >= MAX_PENDING:
                displaced = next(
                    (
                        key
                        for key in reversed(self._pending)
                        if self._records[key]["action"] not in URGENT_ACTIONS
                    ),
                    None,
                )
                if not urgent or displaced is None:
                    raise PermissionError("request queue is full")
                self._records[displaced].update(state="cancelled", error=f"superseded by {action}")
                self._pending.remove(displaced)
                self._pending_writes.discard(displaced)
            if urgent:
                # Never execute an older queued enable/setpoint after an operator's
                # later standby/close request. An exchange in progress cannot be undone.
                for key in list(self._pending):
                    old = self._records[key]
                    if old["action"] in WRITE_ACTIONS and old["action"] not in URGENT_ACTIONS:
                        old.update(state="cancelled", error=f"superseded by {action}")
                        self._pending.remove(key)
                        self._pending_writes.discard(key)
            record = {
                "id": request_id,
                "action": action,
                "value": value,
                "confirmed": confirmed,
                "state": "queued",
                "error": None,
                "submitted_at": datetime.now(UTC).isoformat(),
                "queued_at": self._clock(),
                "result": None,
                "transaction": None,
                "readback": None,
            }
            self._records[request_id] = record
            self._pending.append(request_id)
            if write:
                self._pending_writes.add(request_id)
            while len(self._records) > MAX_RECORDS:
                self._records.popitem(last=False)
        self.wake.set()
        return request_id

    def snapshot(self) -> dict[str, Any]:
        """Copy bounded query/action evidence; safe while the acquisition caller blocks."""
        with self._lock:
            return deepcopy(
                {
                    "allow_writes": self.controller.allow_writes,
                    "power_limit_w": self.controller.power_limit_w,
                    "failed": self.controller.failed,
                    "accepting": self._accepting,
                    "polling": self._polling,
                    "write_pending": bool(self._pending_writes),
                    "pending": bool(self._pending)
                    or any(item["state"] == "running" for item in self._records.values()),
                    "queries": self._queries,
                    "actions": list(self._records.values())[-20:],
                }
            )

    def close(self) -> None:
        """Reject new work and cancel queued actions; no cleanup device commands."""
        with self._lock:
            self._accepting = False
            for request_id in self._pending:
                self._records[request_id]["state"] = "cancelled"
                self._pending_writes.discard(request_id)
            self._pending.clear()
        self.wake.set()

    def _query(self, query: str, *, capture: bool = False) -> Any:
        value = self.controller.capture(query) if capture else self.controller.read(query)
        with self._lock:
            self._queries[query] = {
                "value": transaction_evidence(cast(dict[str, Any], value)) if capture else value,
                "captured": capture,
                "sampled_at": datetime.now(UTC).isoformat(),
                "transaction": transaction_evidence(self.controller.last_transaction),
            }
        return value

    def _write(self, action: str, value: Any) -> tuple[str | None, Any]:
        """Use the public API for validation; retain the actual serialized setpoint."""
        spec = ACTIONS[action]
        if action == "power":
            self.controller.set_power_w(value)
        else:
            instruction = spec.command
            if instruction.endswith("="):
                if not isinstance(value, str):
                    raise ValueError(
                        "enter a decimal temperature, integer lock value, or baud rate"
                    )
                instruction += value
            self.controller.command(instruction)
        expected = spec.expected
        if spec.query is not None and expected is None:
            record = self.controller.last_transaction
            assert record is not None
            return spec.query, float(record["instruction"].split("=")[1])
        return spec.query, expected

    def _execute(self, record: dict[str, Any]) -> None:
        action = record["action"]
        write = action in WRITE_ACTIONS
        before = self.controller.last_transaction
        try:
            if self._clock() - record["queued_at"] > MAX_QUEUE_AGE_S:
                raise PermissionError("queued action expired; submit again explicitly")
            if self.controller.failed:
                raise PermissionError("controller session failed; request cancelled")
            if write:
                if not self.controller.allow_writes:
                    raise PermissionError("writes disabled")
                if action not in URGENT_ACTIONS and self.monitor.latest()["health"] != "LIVE":
                    raise PermissionError("a fresh overview sample is required for this write")
                if action in ("start", "shutter_open") and not record["confirmed"]:
                    raise PermissionError("confirm beam path, cooling and interlock readiness")
                query, expected = self._write(action, record["value"])
                record["transaction"] = transaction_evidence(self.controller.last_transaction)
                record["state"] = "acknowledged"
                if query is not None:
                    actual = self._query(query)
                    record["readback"] = {
                        "query": query,
                        "expected": expected,
                        "actual": actual,
                        "matches": actual == expected,
                        "transaction": transaction_evidence(self.controller.last_transaction),
                    }
                    record["state"] = "verified" if actual == expected else "mismatch"
            elif action in ("read", "capture"):
                query = normalize_query(record["value"])
                value = self._query(query, capture=action == "capture")
                record["result"] = transaction_evidence(value) if action == "capture" else value
                record["transaction"] = transaction_evidence(self.controller.last_transaction)
                record["state"] = "captured" if action == "capture" else "read"
            elif action == "diagnostics":
                record["result"] = {}
                for query in ("?SV", "?HH", "?PSH", "?D1H", "?FH"):
                    self._drain(urgent_only=True)
                    with self._lock:
                        if not self._accepting:
                            raise PermissionError("GUI session is closing")
                    record["result"][query] = self._query(query)
                record["transaction"] = transaction_evidence(self.controller.last_transaction)
                record["state"] = "read"
            else:
                if type(record["value"]) is not bool:
                    raise ValueError("polling value must be a bool")
                with self._lock:
                    self._polling = record["value"]
                record["state"] = "applied"
        except Exception as exc:
            record["error"] = f"{type(exc).__name__}: {exc}"
            if record["transaction"] is not None:
                record["state"] = "readback_failed"
                record["readback"] = {
                    "error": record["error"],
                    "transaction": transaction_evidence(self.controller.last_transaction),
                }
            else:
                latest = self.controller.last_transaction
                if latest != before:
                    record["transaction"] = transaction_evidence(latest)
                # Exception type alone cannot tell us whether a write reached the
                # laser. Even ValueError can originate in the adapter after a write.
                transaction = record["transaction"]
                local_rejection = transaction is None and isinstance(
                    exc, (PermissionError, ValueError)
                )
                device_rejection = transaction is not None and transaction["outcome"] == "rejected"
                record["state"] = "rejected" if local_rejection or device_rejection else "failed"
        finally:
            with self._lock:
                record["finished_at"] = datetime.now(UTC).isoformat()
                self._records[record["id"]] = record
                if write:
                    self._pending_writes.discard(record["id"])

    def _drain(self, *, urgent_only: bool = False) -> bool:
        """Execute bounded queued work; indicate whether a write interrupted a sample."""
        wrote = False
        for _ in range(MAX_PENDING):
            with self._lock:
                if not self._pending or not self._accepting:
                    break
                index = next(
                    (
                        i
                        for i, key in enumerate(self._pending)
                        if self._records[key]["action"] in URGENT_ACTIONS
                    ),
                    -1,
                )
                if index < 0:
                    if urgent_only:
                        break
                    index = 0
                original = self._records[self._pending.pop(index)]
                original["state"] = "running"
                record = dict(original)
            self._execute(record)
            wrote |= record["action"] in WRITE_ACTIONS
        return wrote

    def poll_once(self) -> dict[str, Any]:
        """Drain requests and publish one complete overview, with one caller at a time.

        paused/interrupted returns contain no current status and are not published.
        Between reads, urgent requests run first. An in-flight exchange always
        finishes before another begins; we never retry an uncertain transaction.
        """
        if not self._runner.acquire(blocking=False):
            raise RuntimeError("only one GUI acquisition caller is permitted")
        try:
            self.wake.clear()
            self._drain()
            started = self._clock()
            sample: dict[str, Any] = {
                "attempted_at": datetime.now(UTC).isoformat(),
                "status": None,
                "error": None,
            }
            with self._lock:
                polling = self._polling and self._accepting
            if not polling:
                return sample | {"paused": True}
            status: dict[str, Any] = {
                "model": self.controller.model,
                "simulated": self.controller.is_simulated,
                "sampled_at": sample["attempted_at"],
            }
            try:
                for field, query in STATUS_FIELDS:
                    if self._drain():
                        # A write may change earlier fields. Discard this partial sample;
                        # never publish a mixture of before/after command readings.
                        self.wake.set()
                        return sample | {"interrupted": True}
                    with self._lock:
                        if not self._accepting or not self._polling:
                            return sample | {"paused": True}
                    value = self._query(query)
                    status[field] = (
                        bool(value) if field in ("keyswitch_on", "shutter_open") else value
                    )
                status["duration_s"] = self._clock() - started
                sample.update(status=status, error=None)
            except Exception as exc:
                sample.update(status=None, error=f"{type(exc).__name__}: {exc}".rstrip())
            return self.monitor.record(sample, started)
        finally:
            self._runner.release()
