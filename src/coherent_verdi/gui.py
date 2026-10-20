"""Caller-scheduled status cache and optional read-only Dash view."""

from collections import deque
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any

from .controller import VerdiController, finite_range


class Monitor:
    """One caller polls the controller; browser callbacks only read the cache."""

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
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._lock = Lock()

    def poll_once(self) -> dict[str, Any]:
        started = self._clock()
        sample: dict[str, Any] = {"attempted_at": datetime.now(UTC).isoformat()}
        try:
            sample.update(status=self._controller.status(), error=None)
        except Exception as exc:
            sample.update(status=None, error=f"{type(exc).__name__}: {exc}".rstrip())
        with self._lock:
            self._started = started
            self._history.append(sample)
            return deepcopy(sample)

    def snapshot(self) -> dict[str, Any]:
        """Copy current readings and history without waiting for controller I/O."""
        with self._lock:
            history = deepcopy(list(self._history))
            started = self._started
        last = history[-1] if history else None
        status = last["status"] if last else None
        age = max(0.0, self._clock() - started) if started is not None and status else None
        stale = (
            age is not None
            and status is not None
            and age > max(5.0, 3 * self.interval_s + 2 * status["duration_s"])
        )
        return {
            "model": self._controller.model,
            "simulated": self._controller.is_simulated,
            "health": "NO DATA"
            if not last
            else "ERROR"
            if not status
            else "STALE"
            if stale
            else "LIVE",
            "error": last["error"] if last else None,
            "status": status,
            "age_s": age,
            "history": history,
        }


def create_app(monitor: Monitor) -> Any:
    """Build the view. The caller owns polling, connection lifetime and the server."""
    from dash import Dash, Input, Output, dcc, html

    app = Dash(__name__, assets_folder=str(Path(__file__).with_name("assets")))
    app.title = "Verdi monitor"
    source = "SIMULATOR" if monitor.snapshot()["simulated"] else "PHYSICAL / UNVALIDATED"
    app.layout = html.Main(
        [
            html.H1("Verdi monitor"),
            html.P(source, id="source"),
            html.Div(id="connection-warning", role="alert"),
            html.Section(id="sample"),
            html.Footer("Monitoring only · reported state is not a safety guarantee"),
            dcc.Interval(id="refresh", interval=1000),
            html.Span(id="server-heartbeat", hidden=True),
        ],
        id="dashboard",
    )

    @app.callback(
        Output("sample", "children"),
        Output("server-heartbeat", "children"),
        Input("refresh", "n_intervals"),
    )
    def refresh(tick: int) -> tuple[Any, int]:
        data = monitor.snapshot()
        status = data["status"]
        age = (
            f"Sample age {data['age_s']:.1f} s"
            if data["age_s"] is not None
            else "No current sample"
        )
        readings = [
            ("Measured power / W", "power", f"{status['power_w']:.3f}" if status else "—"),
            ("Setpoint / W", "setpoint", f"{status['set_power_w']:.4f}" if status else "—"),
            (
                "Laser",
                "laser",
                ("STANDBY", "ON", "FAULT")[status["laser_state"]] if status else "UNKNOWN",
            ),
            (
                "Safety shutter",
                "shutter",
                ("OPEN" if status["shutter_open"] else "CLOSED") if status else "UNKNOWN",
            ),
            ("Configured model", "model", data["model"]),
            (
                "Keyswitch",
                "keyswitch",
                ("ON" if status["keyswitch_on"] else "OFF") if status else "UNKNOWN",
            ),
            ("Diode current / A", "current", f"{status['diode_current_a']:.1f}" if status else "—"),
            ("LBO servo", "servo", str(status["lbo_servo"]) if status else "—"),
            (
                "Reported faults",
                "faults",
                (", ".join(map(str, status["faults"])) or "None reported") if status else "Unknown",
            ),
        ]
        readings += [
            (f"{label} / °C", field, f"{status[field]:.2f}" if status else "—")
            for label, field in (
                ("Diode 1", "diode_temp_c"),
                ("Heatsink", "heatsink_temp_c"),
                ("Baseplate", "baseplate_temp_c"),
                ("LBO", "lbo_temp_c"),
                ("Etalon", "etalon_temp_c"),
                ("Vanadate", "vanadate_temp_c"),
            )
        ]
        figure = {
            "data": [
                {
                    "x": [sample["attempted_at"] for sample in data["history"]],
                    "y": [
                        sample["status"][field] if sample["status"] else None
                        for sample in data["history"]
                    ],
                    "name": name,
                    "mode": "lines",
                    "connectgaps": False,
                }
                for field, name in (("power_w", "Measured power"), ("set_power_w", "Setpoint"))
            ],
            "layout": {
                "xaxis": {"title": "Time (UTC)"},
                "yaxis": {"title": "Power / W"},
                "uirevision": "power",
            },
        }
        return [
            html.P([html.Strong(data["health"], id="health"), " · ", age]),
            html.Div(data["error"] or "", id="error", role="alert"),
            html.Table(
                html.Tbody(
                    [
                        html.Tr([html.Th(label), html.Td(value, id=identifier)])
                        for label, identifier, value in readings
                    ]
                )
            ),
            dcc.Graph(id="power-graph", figure=figure, config={"displayModeBar": False}),
        ], tick

    return app
