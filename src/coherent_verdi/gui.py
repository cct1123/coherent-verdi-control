"""Caller-scheduled telemetry and optional Dash control panel."""

import json
from collections import deque
from collections.abc import Callable
from copy import deepcopy
from itertools import islice
from pathlib import Path
from threading import Event, Lock
from time import monotonic
from typing import Any

from .catalogue import QUERY_INFO
from .controller import VerdiController, finite_range
from .gui_session import SERVICE_ACTIONS, ControlSession, display_value


class Monitor:
    """Own the cache and request queue, but never the connection or a thread.

    The launcher calls poll_once and wait on one worker. Browser callbacks use
    latest, power_history and controls; none of these wait for serial I/O.
    Constructing a Monitor or its Dash view sends no device instructions.
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
        self.history_size = history_size
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._lock = Lock()
        self._version = 0
        self._cycle_started: float | None = None
        self.controls = ControlSession(controller, self, clock=clock)

    def poll_once(self) -> dict[str, Any]:
        """Run queued actions and one overview; paused/interrupted cycles are not cached."""
        self._cycle_started = self._clock()
        return self.controls.poll_once()

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
        if stop.is_set():
            return
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
            samples = list(islice(reversed(self._history), count))
            samples.reverse()
            points = [
                (
                    sample["attempted_at"],
                    status["power_w"] if status else None,
                    status["set_power_w"] if status else None,
                )
                for sample in samples
                for status in (sample["status"],)
            ]
            return self._version, points

    def snapshot(self) -> dict[str, Any]:
        """Copy the complete bounded history for callers that need an export."""
        with self._lock:
            history = deepcopy(list(self._history))
            started = self._started
        last = history[-1] if history else None
        return self._describe(last, started) | {"history": history}

    def _describe(self, last: dict[str, Any] | None, started: float | None) -> dict[str, Any]:
        status = last["status"] if last else None
        age = max(0.0, self._clock() - started) if started is not None and status else None
        stale = (
            age is not None
            and status is not None
            and age > max(5.0, 3 * self.interval_s + 2 * status["duration_s"])
        )
        if last is None:
            health = "NO DATA"
        elif status is None:
            health = "ERROR"
        elif stale:
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


def create_app(monitor: Monitor) -> Any:
    """Build the view. The caller owns polling, connection lifetime and the server."""
    from dash import Dash, Input, Output, State, ctx, dcc, html, no_update

    controls = monitor.controls
    settings = controls.snapshot()
    fieldset_attributes: dict[str, Any] = {
        "data-server-disabled": str(not settings["allow_writes"]).lower()
    }
    app = Dash(__name__, assets_folder=str(Path(__file__).with_name("assets")))
    app.title = "Verdi control"
    source = "SIMULATOR" if monitor.latest()["simulated"] else "PHYSICAL / UNVALIDATED"

    def button(label: str, identifier: str, *, disabled: bool = False, urgent: bool = False) -> Any:
        return html.Button(
            label, id=identifier, n_clicks=0, disabled=disabled, className="stop" if urgent else ""
        )

    def card(title: str, *children: Any) -> Any:
        return html.Section([html.H2(title), *children], className="card")

    def layout() -> Any:
        # Inputs live outside refreshed results so an unsent edit survives polling.
        return html.Main(
            [
                html.H1("Verdi control"),
                html.P(source, id="source"),
                html.Div(id="connection-warning", role="alert"),
                dcc.Store(id="browser-session", data=controls.new_client()),
                html.Section(id="sample"),
                dcc.Store(id="history-cursor", data=0),
                dcc.Graph(
                    id="power-graph",
                    figure={
                        "data": [
                            {"x": [], "y": [], "name": name, "mode": "lines", "connectgaps": False}
                            for name in ("Measured power", "Setpoint")
                        ],
                        "layout": {
                            "xaxis": {"title": "Time (UTC)"},
                            "yaxis": {"title": "Power / W"},
                            "uirevision": "power",
                        },
                    },
                    config={"displayModeBar": False},
                ),
                dcc.Store(id="action-request"),
                card(
                    "Operate",
                    html.P(
                        f"Writes enabled · power ceiling {settings['power_limit_w']:g} W"
                        if settings["allow_writes"]
                        else "Read-only session · enable with gui --allow-writes",
                        id="permission-label",
                    ),
                    html.Fieldset(
                        [
                            html.Legend("Power, laser and shutter"),
                            html.Label("Target power / W", htmlFor="target-power"),
                            dcc.Input(
                                id="target-power",
                                type="number",
                                min=0,
                                max=settings["power_limit_w"],
                                step=0.0001,
                                value=0,
                            ),
                            button("Apply power", "apply-power"),
                            dcc.Checklist(
                                id="operator-ready",
                                options=[
                                    {
                                        "label": "Beam path, cooling and interlocks checked",
                                        "value": "ready",
                                    }
                                ],
                                value=[],
                            ),
                            html.P(
                                "Start resets faults and clears history. Capture history first."
                            ),
                            html.Div(
                                [
                                    button("Start / reset faults", "start"),
                                    button("Standby", "standby", urgent=True),
                                    button("Open shutter", "shutter-open"),
                                    button("Close shutter", "shutter-close", urgent=True),
                                ],
                                className="button-row",
                            ),
                            html.Details(
                                [
                                    html.Summary("Advanced service and front-panel controls"),
                                    html.Label("Action", htmlFor="service-action"),
                                    dcc.Dropdown(
                                        id="service-action",
                                        options=[
                                            {"label": label, "value": action}
                                            for action, label in SERVICE_ACTIONS.items()
                                        ],
                                        value="lbo_on",
                                        clearable=False,
                                    ),
                                    html.Label("Operand (when needed)", htmlFor="service-value"),
                                    dcc.Input(
                                        id="service-value",
                                        type="text",
                                        value="",
                                        placeholder="Temperature °C, baud rate, or LFP integer",
                                    ),
                                    button("Apply selected action", "service"),
                                    html.P(
                                        "Chiller: Coherent part 1037271 only; "
                                        "temperature range unspecified. "
                                        "Panel-lock values/unlock mapping and baud "
                                        "acknowledgment timing need verification. "
                                        "FLASH and optimization report initiation, "
                                        "not completion. Echo/prompt have no readback."
                                    ),
                                ]
                            ),
                        ],
                        id="write-controls",
                        disabled=not settings["allow_writes"],
                        **fieldset_attributes,
                    ),
                ),
                card(
                    "Queries and diagnostics",
                    html.Label("Read any documented query", htmlFor="query-choice"),
                    dcc.Dropdown(
                        id="query-choice",
                        options=[
                            {"label": f"{query} · {spec.name} / {spec.unit}", "value": query}
                            for query, spec in QUERY_INFO.items()
                        ],
                        value="?SV",
                        clearable=False,
                    ),
                    html.Div(
                        [
                            button("Read query", "read"),
                            button(
                                "Capture raw query", "capture", disabled=settings["allow_writes"]
                            ),
                            button("Read diagnostics + fault history", "diagnostics"),
                        ],
                        className="button-row",
                    ),
                    html.P(
                        "Capture preserves payload/wire evidence without interpreting it. "
                        "It requires a read-only session. For first connection, launch "
                        "gui --commission to start with overview polling paused."
                    ),
                    html.Div(
                        [
                            button("Pause overview", "pause-polling"),
                            button("Resume overview", "resume-polling"),
                        ],
                        className="button-row",
                    ),
                    html.Div(id="polling-state"),
                    html.Div(id="query-results"),
                ),
                card(
                    "Action results",
                    html.Div(id="submission", role="status"),
                    html.P(
                        "Shared across browser tabs. Acknowledged means protocol acceptance. "
                        "Verified means the documented query matches; "
                        "neither proves physical execution."
                    ),
                    html.Div(id="action-results"),
                ),
                html.Footer(
                    "Reported state is not a safety guarantee · standby is not full shutdown"
                ),
                dcc.Interval(id="refresh", interval=1000),
                dcc.Interval(id="action-refresh", interval=200, disabled=True),
                html.Span(id="server-heartbeat", hidden=True),
            ],
            id="dashboard",
        )

    app.layout = layout

    @app.callback(
        Output("sample", "children"),
        Output("server-heartbeat", "children"),
        Output("power-graph", "extendData"),
        Output("history-cursor", "data"),
        Input("refresh", "n_intervals"),
        State("history-cursor", "data"),
    )
    def refresh(tick: int, cursor: Any) -> tuple[Any, ...]:
        data = monitor.latest()
        version, points = monitor.power_history(
            cursor if type(cursor) is int and cursor >= 0 else 0
        )
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
            ("LBO servo", "servo", display_value("?LBOSS", status["lbo_servo"]) if status else "—"),
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
        return (
            [
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
            ],
            tick,
            (
                {
                    "x": [[point[0] for point in points]] * 2,
                    "y": [[point[index] for point in points] for index in (1, 2)],
                },
                [0, 1],
                monitor.history_size,
            )
            if points
            else no_update,
            version,
        )

    buttons = (
        "apply-power",
        "start",
        "standby",
        "shutter-open",
        "shutter-close",
        "service",
        "read",
        "capture",
        "diagnostics",
        "pause-polling",
        "resume-polling",
    )

    @app.callback(
        Output("submission", "children"),
        Output("action-request", "data"),
        inputs={
            "clicks": {button: Input(button, "n_clicks") for button in buttons},
            "client": State("browser-session", "data"),
            "power": State("target-power", "value"),
            "ready": State("operator-ready", "value"),
            "service": State("service-action", "value"),
            "operand": State("service-value", "value"),
            "query": State("query-choice", "value"),
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
    ) -> tuple[str, Any]:
        """Translate one explicit click into a queued request; never perform I/O."""
        trigger = ctx.triggered_id
        if trigger not in buttons:
            return "", no_update
        sequence = clicks[trigger]
        action = {
            "apply-power": "power",
            "shutter-open": "shutter_open",
            "shutter-close": "shutter_close",
        }.get(trigger, trigger)
        value = None
        if trigger == "service":
            action, value = service, operand
        elif trigger == "apply-power":
            value = power
        elif trigger in ("read", "capture"):
            value = query
        elif trigger in ("pause-polling", "resume-polling"):
            action, value = "polling", trigger == "resume-polling"
        try:
            request_id = controls.submit(
                client,
                trigger,
                sequence,
                action,
                value,
                confirmed=isinstance(ready, list) and "ready" in ready,
            )
            return f"Submitted {action} · {request_id[-12:]}", request_id
        except (ValueError, PermissionError) as exc:
            return str(exc), no_update

    @app.callback(
        Output("query-results", "children"),
        Output("action-results", "children"),
        Output("write-controls", "disabled"),
        Output("write-controls", "data-server-disabled"),
        Output("polling-state", "children"),
        [
            Output(button, "disabled")
            for button in ("apply-power", "start", "shutter-open", "service")
        ],
        Output("action-refresh", "disabled"),
        Input("refresh", "n_intervals"),
        Input("action-request", "data"),
        Input("action-refresh", "n_intervals"),
    )
    def refresh_controls(tick: int, request: Any, action_tick: int) -> tuple[Any, ...]:
        data = controls.snapshot()
        disabled = not data["allow_writes"] or data["failed"] or not data["accepting"]
        require_fresh = disabled or data["write_pending"] or monitor.latest()["health"] != "LIVE"
        queries = html.Table(
            [
                html.Thead(
                    html.Tr(
                        [html.Th(label) for label in ("Query", "Value", "Unit", "Acquired UTC")]
                    )
                ),
                html.Tbody(
                    [
                        html.Tr(
                            [
                                html.Td(f"{query} · {QUERY_INFO[query][0]}"),
                                html.Td(
                                    "Raw capture (see evidence)"
                                    if item["captured"]
                                    else display_value(query, item["value"])
                                ),
                                html.Td(QUERY_INFO[query][1]),
                                html.Td(item["sampled_at"]),
                            ]
                        )
                        for query, item in data["queries"].items()
                    ]
                ),
            ]
        )

        def describe_action(item: dict[str, Any]) -> str:
            if item["error"]:
                return str(item["error"])
            readback = item["readback"]
            if readback and "actual" in readback:
                query = readback["query"]
                return (
                    f"Requested {display_value(query, readback['expected'])}; "
                    f"read back {display_value(query, readback['actual'])} "
                    f"{QUERY_INFO[query][1]}"
                )
            if item["action"] == "read" and item["state"] == "read":
                query = item["transaction"]["instruction"]
                return f"{query}: {display_value(query, item['result'])} {QUERY_INFO[query][1]}"
            if item["state"] == "acknowledged":
                return (
                    "Acknowledged. No documented readback confirms this action or its completion."
                )
            if item["state"] == "captured":
                return f"Captured payload: {item['result']['payload']!r}"
            if item["action"] == "diagnostics" and item["result"]:
                return " · ".join(
                    f"{QUERY_INFO[q][0]}: {display_value(q, v)} {QUERY_INFO[q][1]}"
                    for q, v in item["result"].items()
                )
            return str(item["state"])

        results = [
            html.Details(
                [
                    html.Summary(
                        f"{item['action']} · {item['state']} · "
                        f"{item.get('finished_at', item['submitted_at'])}"
                    ),
                    html.P(describe_action(item)),
                    html.Details(
                        [
                            html.Summary("Transaction evidence"),
                            html.Pre(json.dumps(item, indent=2, allow_nan=False)),
                        ]
                    ),
                ],
                open=index == 0,
            )
            for index, item in enumerate(reversed(data["actions"]))
        ]
        return (
            queries,
            results,
            disabled,
            str(disabled).lower(),
            (
                "Overview polling active"
                if data["polling"]
                else "Overview polling paused · query results have individual acquisition times"
            ),
            *([require_fresh] * 4),
            not data["pending"],
        )

    return app
