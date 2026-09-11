"""Optional synchronous sampling, bounded cache and JSON output. No worker threads."""

import json
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from typing import Any

from .controller import Status, VerdiController
from .protocol import finite_range


@dataclass(frozen=True)
class Sample:
    sequence: int
    attempted_at: datetime
    status: Status | None
    error: str | None


class Monitor:
    """Caller schedules poll_once() and owns connection/shutdown. GUI reads snapshot().

    Samples are sequential. Failures replace the current reading with a gap.
    Use a new monitor for a new controller to keep sources and sessions separate.
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
        self._controller = controller
        self._clock = clock
        self._started: float | None = None
        self._history: deque[Sample] = deque(maxlen=history_size)
        self._cache_lock = Lock()
        self._poll_lock = Lock()
        self._sequence = 0

    def poll_once(self) -> Sample:
        """Acquire synchronously; publish errors without retrying or changing state."""
        with self._poll_lock:
            started, at = self._clock(), datetime.now(UTC)
            try:
                status, error = self._controller.status(), None
            except Exception as exc:
                status, error = None, f"{type(exc).__name__}: {exc}".rstrip()
            with self._cache_lock:
                self._sequence += 1
                sample = Sample(self._sequence, at, status, error)
                self._started = started
                self._history.append(sample)
                return sample

    def snapshot(self) -> dict[str, Any]:
        """Copy cached data without waiting for device I/O. Age includes sample duration."""
        with self._cache_lock:
            history = tuple(self._history)
            status = history[-1].status if history else None
            return {
                "model": self._controller.model,
                "history": history,
                "simulated": self._controller.is_simulated,
                "age_s": max(0.0, self._clock() - self._started)
                if status is not None and self._started is not None
                else None,
                "interval_s": self.interval_s,
            }


def to_json(value: object, *, indent: int | None = 2) -> str:
    """Serialize samples/status with explicit units, UTC timestamps and finite numbers."""

    def default(item: Any) -> Any:
        if is_dataclass(item) and not isinstance(item, type):
            return asdict(item)
        if isinstance(item, datetime):
            return item.isoformat()
        raise TypeError(f"cannot serialize {type(item).__name__}")

    return json.dumps(value, default=default, indent=indent, allow_nan=False)
