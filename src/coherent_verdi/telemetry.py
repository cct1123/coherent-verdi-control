"""One bounded polling service shared by clients; clients never trigger polling."""

import logging
from collections import deque
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from types import TracebackType

from .controller import VerdiController
from .models import TelemetrySample, finite_range

logger = logging.getLogger(__name__)


class TelemetryService:
    """Owns its worker, not its controller. Sampling starts only on explicit start.

    No catch-up bursts: interval_s is a minimum gap after each complete sample.
    Failed samples are visible and never carry a stale status as a fresh success.
    """

    def __init__(
        self, controller: VerdiController, *, interval_s: float = 1.0, history_size: int = 600
    ) -> None:
        finite_range(interval_s, 0.001, 86400, "interval_s")
        if type(history_size) is not int or not 1 <= history_size <= 100000:
            raise ValueError("history_size must be an integer in [1, 100000]")
        self.controller = controller
        self.interval_s = interval_s
        self._history: deque[TelemetrySample] = deque(maxlen=history_size)
        self._history_lock = Lock()
        self._poll_lock = Lock()
        self._lifecycle_lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._sequence = 0

    @property
    def history(self) -> tuple[TelemetrySample, ...]:
        with self._history_lock:
            return tuple(self._history)

    @property
    def running(self) -> bool:
        with self._lifecycle_lock:
            return self._thread is not None and self._thread.is_alive()

    def poll_once(self) -> TelemetrySample:
        """Explicit synchronous sample for orchestration/tests, serialized with worker polls."""
        with self._poll_lock:
            at = datetime.now(UTC)
            try:
                status = self.controller.status()
                error = error_type = None
            except Exception as exc:
                # Background workers must publish programming errors as well as I/O
                # failures, rather than dying and leaving a plausible frozen dashboard.
                status = None
                error, error_type = str(exc), type(exc).__name__
                logger.warning("telemetry sample failed (%s): %s", error_type, error)
            with self._history_lock:
                self._sequence += 1
                sample = TelemetrySample(self._sequence, at, status, error, error_type)
                self._history.append(sample)
                return sample

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            if self._stop.wait(self.interval_s):
                break

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = Thread(target=self._run, name="verdi-telemetry", daemon=True)
            self._thread.start()

    def stop(self, *, timeout_s: float = 30.0) -> None:
        finite_range(timeout_s, 0.001, 900, "timeout_s")
        with self._lifecycle_lock:
            self._stop.set()
            if self._thread is not None:
                self._thread.join(timeout_s)
                if self._thread.is_alive():
                    raise TimeoutError(
                        "telemetry worker still sampling; controller must remain open"
                    )
                self._thread = None

    def __enter__(self) -> "TelemetryService":
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.stop()
