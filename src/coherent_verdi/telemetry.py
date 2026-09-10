"""One bounded polling service shared by clients; clients never trigger polling."""

import logging
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, Lock, Thread
from time import monotonic
from types import TracebackType

from .controller import VerdiController
from .models import TelemetrySample, TelemetrySnapshot, finite_range

logger = logging.getLogger(__name__)


class TelemetryService:
    """Owns its worker, not its controller. Sampling starts only on explicit start.

    No catch-up bursts: interval_s is a minimum gap after each complete sample.
    Failed samples are visible and never carry a stale status as a fresh success.
    """

    def __init__(
        self,
        controller: VerdiController,
        *,
        interval_s: float = 1.0,
        history_size: int = 600,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        finite_range(interval_s, 0.001, 86400, "interval_s")
        if type(history_size) is not int or not 1 <= history_size <= 100000:
            raise ValueError("history_size must be an integer in [1, 100000]")
        self._controller = controller
        self._clock = clock
        self._latest_started: float | None = None
        self._last_source: bool | None = None
        self._interval_s = interval_s
        self._history: deque[TelemetrySample] = deque(maxlen=history_size)
        self._history_lock = Lock()
        self._poll_lock = Lock()
        self._lifecycle_lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._sequence = 0

    @property
    def controller(self) -> VerdiController:
        """The borrowed controller; create a new service to change ownership."""
        return self._controller

    @property
    def interval_s(self) -> float:
        """Validated minimum gap between samples; fixed for this service."""
        return self._interval_s

    @property
    def history(self) -> tuple[TelemetrySample, ...]:
        with self._history_lock:
            return tuple(self._history)

    def snapshot(self) -> TelemetrySnapshot:
        """Read only the cache, even while the controller is blocked in a transaction."""
        with self._history_lock:
            samples = tuple(self._history)
            status = samples[-1].status if samples else None
            age = (
                max(0.0, self._clock() - self._latest_started)
                if status is not None and self._latest_started is not None
                else None
            )
            return TelemetrySnapshot(
                self.controller.config.model,
                samples,
                status.simulated if status else None,
                age,
                self.interval_s,
            )

    @property
    def running(self) -> bool:
        with self._lifecycle_lock:
            return self._thread is not None and self._thread.is_alive()

    def poll_once(self) -> TelemetrySample:
        """Explicit synchronous sample for orchestration/tests, serialized with worker polls."""
        with self._poll_lock:
            started = self._clock()
            at = datetime.now(UTC)
            try:
                status = self.controller.status()
                error = error_type = None
            except Exception as exc:
                # Background workers must publish programming errors as well as I/O
                # failures, rather than dying and leaving a plausible frozen dashboard.
                status = None
                error, error_type = str(exc), type(exc).__name__
            with self._history_lock:
                # One plotted history must not silently mix simulated and physical
                # measurements after an explicit transport replacement.
                if status is not None:
                    if self._last_source is not None and status.simulated != self._last_source:
                        self._history.clear()
                    self._last_source = status.simulated
                self._latest_started = started
                self._sequence += 1
                sample = TelemetrySample(self._sequence, at, status, error, error_type)
                self._history.append(sample)
        # Application logging handlers are external code. Publish first and release
        # acquisition/cache locks so handlers can inspect the service safely.
        if sample.error_type is not None:
            try:
                logger.warning("telemetry sample failed (%s): %s", error_type, error)
            except Exception:
                # The sample retains the original failure even if a logging sink
                # fails; logging must not terminate the acquisition worker.
                pass
        return sample

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._stop.wait(self.interval_s)

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
            thread = self._thread
        # A worker's logging handler may inspect running while shutdown waits.
        # Do not hold the lifecycle lock across external worker execution.
        if thread is not None:
            thread.join(timeout_s)
            with self._lifecycle_lock:
                if thread.is_alive():
                    raise TimeoutError(
                        "telemetry worker still sampling; controller must remain open"
                    )
                if self._thread is thread:
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
