"""Optional Dash GUI, connection ownership and worker/server lifetime.

Browser callbacks submit requests or render cached results. Only the single
acquisition worker opens, polls or closes the controller.
"""

import json
from collections.abc import Callable
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from .controller import BAUDRATES, QUERY_INFO, VerdiController, VerdiError, finite_range
from .monitor import (
    ACTIONS,
    BUTTONS,
    MENU_ACTIONS,
    MENU_DISABLED_REASON,
    PANEL_BUTTONS,
    SERVICE_ACTIONS,
    Monitor,
)
from .simulator import SimulatedVerdi

# Write buttons that also need a fresh overview; standby/close stay available.
FRESH_BUTTONS = ("apply-power", "start", "shutter-open", "service") + tuple(
    name for name in PANEL_BUTTONS if name != "panel-shutter"
)
LCD_WIDTH = 20


def _power_input_limit(limit_w: float) -> float:
    """Highest 0.01 W setting at or below the configured ceiling."""
    steps = round(limit_w * 100)
    if steps / 100 > limit_w:
        steps -= 1
    return steps / 100


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


class GuiSession:
    def __init__(
        self,
        *,
        port: str | None = None,
        model: str = "V5",
        baudrate: int = 19200,
        timeout_s: float = 1.0,
        allow_writes: bool = False,
        power_limit_w: float | None = None,
        prompt_enabled: bool = True,
    ) -> None:
        if type(prompt_enabled) is not bool:
            raise ValueError("prompt_enabled must be a bool")
        self.settings: dict[str, Any] = dict(
            source="hardware" if port else "simulator",
            port=port or "",
            model=model,
            baudrate=baudrate,
            timeout_s=finite_range(timeout_s, 0.001, 60, "timeout_s"),
            prompt_enabled=prompt_enabled,
        )
        self.options: dict[str, Any] = dict(
            allow_writes=allow_writes,
            power_limit_w=power_limit_w,
        )
        self.monitor = Monitor(
            SimulatedVerdi(
                model,
                allow_writes=allow_writes,
                power_limit_w=power_limit_w,
                prompt=prompt_enabled,
            )
        )
        self.monitor.session = self
        self.monitor.controls.close()
        self.stop = Event()
        self._lock = Lock()
        self._pending: tuple[str, dict[str, Any]] | None = None
        self._state = "DISCONNECTED"
        self._error: str | None = None
        self._connected = False

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(
                state=self._state,
                connected=self._connected,
                error=self._error,
                generation=self.monitor.generation,
                settings=dict(self.settings),
            )

    def submit(self, action: str, settings: dict[str, Any] | None = None) -> None:
        if action not in ("connect", "disconnect", "close"):
            raise ValueError("unknown connection action")
        with self._lock:
            if self.stop.is_set():
                raise PermissionError("application is closed")
            if self._state == "CLOSING":
                return
            if action == "connect" and (
                self._connected
                or self._pending is not None
                or self._state in ("CONNECTING", "DISCONNECTING")
            ):
                raise PermissionError("disconnect before opening another connection")
            if action != "close" and self._pending is not None:
                raise PermissionError("a connection action is already pending")
            self._pending = action, self.settings | (settings or {})
            self._state = {
                "connect": "CONNECTING",
                "disconnect": "DISCONNECTING",
                "close": "CLOSING",
            }[action]
            self._error = None
            # Close admission before the worker can finish this connection action.
            self.monitor.close()

    def require_monitoring(self) -> None:
        state = self.snapshot()
        if not state["connected"]:
            raise PermissionError("connect before starting monitoring")

    def remember_link_settings(self, instruction: bytes) -> None:
        """Retain acknowledged hardware link changes for the form and next connection."""
        with self._lock:
            if instruction.startswith(b"B=") and not self.monitor.controller.is_simulated:
                self.settings["baudrate"] = int(instruction[2:])
            elif instruction in (b"PROMPT=0", b"PROMPT=1"):
                self.settings["prompt_enabled"] = instruction == b"PROMPT=0"

    def step(self) -> None:
        """One worker iteration; useful in tests without a background thread."""
        monitor = self.monitor
        monitor.controls.wake.clear()
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is not None:
            action, settings = pending
            controller = monitor.controller
            try:
                controller.disconnect()
                with self._lock:
                    self._connected = False
                if action == "connect":
                    if settings.get("source") not in ("hardware", "simulator"):
                        raise ValueError("select Hardware or Simulator")
                    settings["timeout_s"] = finite_range(
                        settings["timeout_s"], 0.001, 60, "timeout_s"
                    )
                    if type(settings["prompt_enabled"]) is not bool:
                        raise ValueError("prompt_enabled must be a bool")
                    if settings["source"] == "hardware":
                        controller = VerdiController(
                            settings["port"],
                            model=settings["model"],
                            baudrate=settings["baudrate"],
                            timeout_s=settings["timeout_s"],
                            prompt_enabled=settings["prompt_enabled"],
                            **self.options,
                        )
                    else:
                        controller = SimulatedVerdi(
                            settings["model"],
                            allow_writes=self.options["allow_writes"],
                            power_limit_w=self.options["power_limit_w"],
                            prompt=settings["prompt_enabled"],
                        )
                    controller.connect(override=False)
                    with self._lock:
                        self.settings = settings
                        self._connected = True
                with self._lock:
                    if self._pending is None and self._state != "CLOSING":
                        self._state = "CONNECTED" if self._connected else "DISCONNECTED"
            except Exception as exc:
                with self._lock:
                    self._error = f"{type(exc).__name__}: {exc}"
                    if self._state != "CLOSING":
                        self._state = "ERROR"
            finally:
                with self._lock:
                    monitor.reset(controller, accepting=self._state == "CONNECTED")
                if action == "close":
                    self.stop.set()
            return  # Connecting is passive: monitoring needs a separate Start action.
        if self.snapshot()["connected"] and not monitor.controller.failed:
            sample = monitor.poll_once()
            if monitor.controller.failed:
                monitor.close()
                with self._lock:
                    self._state = "ERROR"
                    self._error = (
                        sample.get("error") or "communication failed; disconnect to recover"
                    )
        with self._lock:
            if self._pending is not None:
                monitor.controls.wake.set()

    def run(self) -> None:
        try:
            while not self.stop.is_set():
                self.step()
                self.monitor.wait(self.stop)
        except Exception as exc:
            with self._lock:
                self._error = f"{type(exc).__name__}: {exc}"
        finally:
            self.monitor.close()
            try:
                self.monitor.controller.disconnect()
                with self._lock:
                    self._connected = False
            except Exception as exc:
                with self._lock:
                    self._error = f"{type(exc).__name__}: {exc}"
            with self._lock:
                self._state = "ERROR" if self._error else "CLOSED"
            self.stop.set()


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


# Overview rows: label, element id, text without a sample, and a status formatter.
# The configured model (None) is shown with or without a sample.
READINGS: list[tuple[str, str, str, Callable[[dict[str, Any]], str] | None]] = [
    ("Measured power / W", "power", "—", lambda s: f"{s['power_w']:.3f}"),
    ("Setpoint / W", "setpoint", "—", lambda s: f"{s['set_power_w']:.4f}"),
    ("Laser", "laser", "UNKNOWN", lambda s: QUERY_INFO["?L"].labels[s["laser_state"]]),
    ("Safety shutter", "shutter", "UNKNOWN", lambda s: "OPEN" if s["shutter_open"] else "CLOSED"),
    ("Configured model", "model", "", None),
    ("Keyswitch", "keyswitch", "UNKNOWN", lambda s: "ON" if s["keyswitch_on"] else "OFF"),
    ("Diode current / A", "current", "—", lambda s: f"{s['diode_current_a']:.2f}"),
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
    return {
        "read": "Read query",
        "capture": "Raw capture",
        "polling": "Monitoring",
        "interval": "Sampling interval",
    }.get(action, action.capitalize())


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
    """Indicator classes; only a live sample can establish the displayed state."""
    status = data["status"] if data["health"] == "LIVE" else None

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


def create_app(monitor: Monitor, *, session: GuiSession | None = None) -> Any:
    """Build the view. The caller owns polling, connection lifetime and the server."""
    if session is not None and session.monitor is not monitor:
        raise ValueError("session and view must share the same monitor")
    import dash_bootstrap_components as dbc
    from dash import Dash, Input, Output, State, ctx, dcc, html, no_update

    controls = monitor.controls
    settings = controls.snapshot()
    writable = settings["allow_writes"]
    app = Dash(__name__, assets_folder=str(Path(__file__).with_name("assets")))
    app.title = "Verdi control"
    source = (
        "DISCONNECTED" if session else "SIMULATOR" if monitor.latest()["simulated"] else "HARDWARE"
    )

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
    limit = _power_input_limit(settings["power_limit_w"])
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
                        id="target-power", type="number", min=0, max=limit, step=0.01, value=0
                    ),
                    dbc.InputGroupText("W"),
                    button("Apply", "apply-power", tone="primary", solid=True),
                ],
                size="sm",
            ),
            dbc.FormText(
                "Power targets and presets use 0.01 W increments. "
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
            disabled=PANEL_BUTTONS.get(identifier) in MENU_ACTIONS,
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
                    f"Apply preset {number} in 0.01 W increments; stored in this browser",
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
                    step=0.01,
                    placeholder="W",
                    persistence=True,
                    persistence_type="local",
                    className="preset",
                ),
            ],
            className="level",
        )

    menu = MENU_DISABLED_REASON
    panel = html.Fieldset(
        [
            html.Legend("Verdi front panel", className="visually-hidden"),
            html.Div(
                [
                    html.Span("COHERENT", className="brand"),
                    html.Span(className="rule"),
                    html.Span(
                        f"VERDI {monitor.latest()['model']}", id="panel-model", className="model"
                    ),
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
                            key("panel-menu-up", "MENU UP", menu, "▲"),
                            key("panel-menu-down", "MENU DOWN", menu, "▼"),
                            legend("MENU DOWN"),
                        ],
                        className="menu-arrows",
                    ),
                    pushbutton("panel-select", "MENU SELECT", menu),
                    pushbutton("panel-exit", "MENU EXIT", menu),
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
                                title="Drag, scroll or use arrow keys in 0.01 W steps "
                                "(Shift ×10) to edit the target; SET POWER sends it",
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
        "Panel replica. The display is synthesized from queries. "
        f"{MENU_DISABLED_REASON} POWER ADJUST only edits the "
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
            button("Read value", "read", tone="primary"),
            button("Capture bytes", "capture", disabled=writable),
            button("Diagnostics + fault history", "diagnostics"),
        ),
        dbc.FormText(
            "Read value interprets the reply. Capture bytes preserves the byte payload and full "
            "reply in Transaction evidence, and needs a read-only session. "
            "Connect first; monitoring starts only when you click Start monitoring."
        ),
        dbc.FormText(
            "Query availability depends on firmware. The reference V2 run rejected ?DIOS; "
            "the health-check notebook skips it."
        ),
        html.Div(id="query-results"),
    )
    connection = None
    if session is not None:
        initial = session.settings
        connection = card(
            "Connection",
            dbc.Row(
                [
                    dbc.Col(
                        [
                            field("Source", "connection-source"),
                            dropdown(
                                "connection-source",
                                {"hardware": "Hardware", "simulator": "Simulator"},
                                initial["source"],
                            ),
                        ],
                        md=3,
                    ),
                    dbc.Col(
                        [
                            field("Serial port", "connection-port"),
                            dbc.Input(
                                id="connection-port", value=initial["port"], placeholder="COM5"
                            ),
                        ],
                        md=3,
                    ),
                    dbc.Col(
                        [
                            field("Model", "connection-model"),
                            dropdown(
                                "connection-model",
                                {m: m for m in ("V2", "V5", "V6")},
                                initial["model"],
                            ),
                        ],
                        md=3,
                    ),
                    dbc.Col(
                        [
                            field("Baud rate", "connection-baud"),
                            dcc.Dropdown(
                                id="connection-baud",
                                clearable=False,
                                value=initial["baudrate"],
                                options=[{"label": str(b), "value": b} for b in BAUDRATES],
                            ),
                        ],
                        md=3,
                    ),
                ],
                className="g-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            field("Device prompt", "connection-prompt"),
                            dropdown(
                                "connection-prompt",
                                {"enabled": "Enabled", "disabled": "Disabled"},
                                "enabled" if initial["prompt_enabled"] else "disabled",
                            ),
                        ],
                        md=6,
                    ),
                    dbc.Col(
                        [
                            field("Timeout / s", "connection-timeout"),
                            dbc.Input(
                                id="connection-timeout",
                                type="number",
                                min=0.001,
                                max=60,
                                step="any",
                                value=initial["timeout_s"],
                            ),
                        ],
                        md=6,
                    ),
                ],
                className="g-3",
            ),
            row(
                button("Connect", "connection-toggle", tone="primary"),
                button("Close application", "close-application", tone="danger"),
            ),
            html.Div("DISCONNECTED", id="connection-state", role="status"),
            html.Div(id="connection-message", role="status"),
            dbc.FormText(
                "Connect only opens the port. Start monitoring separately. Disconnect "
                "and Close application release communication; they do not shut down the laser."
            ),
            dbc.FormText(
                "Match the existing device prompt setting; no modes are changed automatically. "
                "Timeout applies to serial write and receive waits."
            ),
        )

    header = html.Header(
        [
            html.Div(
                [
                    html.H1("Verdi control", className="app-title"),
                    html.Span(
                        f"Coherent Verdi {monitor.latest()['model']}",
                        id="header-model",
                        className="muted",
                    ),
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
        subtitle="Explicit power, laser and shutter commands",
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
        monitoring = card(
            "Monitoring",
            row(
                button("Start monitoring", "resume-polling", tone="primary"),
                button("Pause monitoring", "pause-polling"),
            ),
            field("Target sampling interval / s", "monitoring-interval"),
            dbc.Input(
                id="monitoring-interval",
                type="number",
                min=0.1,
                max=3600,
                step=0.1,
                value=monitor.interval_s,
            ),
            row(button("Apply interval", "apply-interval")),
            html.Div(id="polling-state", className="muted"),
            dbc.FormText(
                "Reads power, diode current and temperatures. Slow serial replies can "
                "make a cycle longer than the target interval."
            ),
        )
        # Inputs live outside refreshed results so an unsent edit survives polling.
        return html.Main(
            dbc.Container(
                [
                    header,
                    dbc.Row(
                        [
                            dbc.Col(connection, lg=8) if connection else None,
                            dbc.Col(monitoring, lg=4 if connection else 12),
                        ],
                        className="g-4",
                    ),
                    html.Div(id="connection-warning", role="alert"),
                    dcc.Store(id="browser-session", data=controls.new_client()),
                    dcc.Store(id="panel-setpoint"),
                    dcc.Store(id="history-cursor", data=0),
                    dcc.Store(id="connection-generation", data=0),
                    dcc.Store(id="connection-settings"),
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
        Output("power-graph", "figure"),
        Output("connection-generation", "data"),
        Output("operator-ready", "value"),
        Output("front-panel", "className"),
        Output("panel-display", "children"),
        [Output(f"panel-{name}", "className") for name in ("ac", "emission", "shutter-led", "key")],
        Output("panel-shutter", "data-shown"),
        Output("panel-setpoint", "data"),
        Output("header-health", "children"),
        Output("header-health", "className"),
        Input("refresh", "n_intervals"),
        State("history-cursor", "data"),
        State("connection-generation", "data"),
    )
    def refresh(tick: int, cursor: Any, previous_generation: Any = 0) -> tuple[Any, ...]:
        data = monitor.latest()
        status = data["status"]
        generation = monitor.generation
        reset_plot = generation != previous_generation
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
            (plot, [0, 1], monitor.history_size) if points and not reset_plot else no_update,
            0 if reset_plot else version,
            {"data": traces, "layout": figure_layout | {"uirevision": f"power-{generation}"}}
            if reset_plot
            else no_update,
            generation,
            [] if reset_plot else no_update,
            "front-panel" if data["health"] == "LIVE" else "front-panel stale",
            [html.Div(line) for line in lcd_lines(data)],
            lamps["ac"],
            lamps["emission"],
            lamps["shutter"],
            f"keyswitch {lamps['key']}",
            lamps["shown"],
            status["set_power_w"] if status and health == "LIVE" else None,
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
            "interval": State("monitoring-interval", "value"),
            "generation": State("connection-generation", "data"),
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
        interval: Any,
        generation: Any,
    ) -> tuple[str, Any]:
        """Translate one explicit click into a queued request; never perform I/O."""
        trigger = ctx.triggered_id
        if trigger not in BUTTONS:
            return "", no_update
        action = service if trigger == "service" else BUTTONS[trigger]
        if trigger == "panel-shutter":
            action = shutter_toggle(shown, monitor.latest())
        values = {
            "apply-interval": interval,
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
                client,
                trigger,
                clicks[trigger],
                action,
                value,
                confirmed=confirmed,
                generation=generation if type(generation) is int else -1,
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
        Output("header-model", "children"),
        Output("panel-model", "children"),
        Output("permission-label", "children"),
        [
            Output(name, "max")
            for name in ("target-power", "panel-level-1-value", "panel-level-2-value")
        ],
        Output("panel-knob", "aria-valuemax"),
        Output("panel-knob", "data-max"),
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
        ceiling = data["power_limit_w"]
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
            f"Monitoring active · target interval {monitor.interval_s:g} s"
            if data["polling"]
            else "Monitoring paused · query results have individual acquisition times",
            *(require_fresh or BUTTONS[name] in MENU_ACTIONS for name in FRESH_BUTTONS),
            not data["pending"],
            f"Coherent Verdi {monitor.controller.model}",
            f"VERDI {monitor.controller.model}",
            f"Writes enabled · ≤ {ceiling:g} W"
            if data["allow_writes"]
            else "Read-only · launch with --allow-writes",
            *([_power_input_limit(ceiling)] * 5),
        )

    if session is not None:
        connection_fields = ("source", "port", "model", "baud", "prompt", "timeout")

        @app.callback(
            Output("connection-message", "children"),
            Input("connection-toggle", "n_clicks"),
            Input("close-application", "n_clicks"),
            State("connection-toggle", "children"),
            [State(f"connection-{name}", "value") for name in connection_fields],
            prevent_initial_call=True,
        )
        def change_connection(
            toggle: int,
            close: int,
            toggle_label: str,
            source: str,
            port: str,
            model: str,
            baud: int,
            prompt_mode: str,
            timeout_s: float,
        ) -> str:
            try:
                if ctx.triggered_id == "close-application":
                    action = "close"
                else:
                    if toggle_label not in ("Connect", "Disconnect"):
                        raise ValueError("a connection change is already in progress")
                    # Follow the displayed action, so delayed/duplicate Connect clicks
                    # cannot disconnect a connection that just finished opening.
                    action = toggle_label.lower()
                requested = None
                if action == "connect":
                    if prompt_mode not in ("enabled", "disabled"):
                        raise ValueError("select Enabled or Disabled for the device prompt")
                    requested = dict(
                        source=source,
                        port=port,
                        model=model,
                        baudrate=baud,
                        prompt_enabled=prompt_mode == "enabled",
                        timeout_s=timeout_s,
                    )
                session.submit(action, requested)
                return (
                    "Closing application; communication will be released."
                    if action == "close"
                    else f"{action.capitalize()} requested."
                )
            except (ValueError, PermissionError) as exc:
                return str(exc)

        @app.callback(
            Output("connection-state", "children"),
            Output("source", "children"),
            Output("connection-toggle", "children"),
            Output("connection-toggle", "disabled"),
            Output("connection-toggle", "color"),
            [Output(f"connection-{name}", "disabled") for name in connection_fields],
            [Output(f"connection-{name}", "value") for name in connection_fields],
            Output("connection-settings", "data"),
            [
                Output(name, "disabled")
                for name in (
                    "resume-polling",
                    "pause-polling",
                    "apply-interval",
                    "read",
                    "capture",
                    "diagnostics",
                )
            ],
            Input("refresh", "n_intervals"),
            State("connection-settings", "data"),
        )
        def connection_status(tick: int, previous_settings: Any) -> tuple[Any, ...]:
            state = session.snapshot()
            busy = state["state"] in ("CONNECTING", "DISCONNECTING", "CLOSING")
            connected = state["connected"]
            label = state["state"] + (f" · {state['error']}" if state["error"] else "")
            source = state["settings"]["source"].upper() if connected else "DISCONNECTED"
            disabled = not connected or busy or monitor.controller.failed
            settings = state["settings"]
            values = [
                settings["source"],
                settings["port"],
                settings["model"],
                settings["baudrate"],
                "enabled" if settings["prompt_enabled"] else "disabled",
                settings["timeout_s"],
            ]
            return (
                label,
                source,
                {
                    "CONNECTING": "Connecting…",
                    "DISCONNECTING": "Disconnecting…",
                    "CLOSING": "Closing…",
                }.get(state["state"], "Disconnect" if connected else "Connect"),
                busy,
                "secondary" if connected else "primary",
                *([connected or busy] * len(connection_fields)),
                *(values if settings != previous_settings else [no_update] * len(values)),
                settings,
                disabled or monitor.controls.polling,
                disabled or not monitor.controls.polling,
                disabled,
                disabled,
                disabled or writable,
                disabled,
            )

    # Browser-only presentation; registered after the server callbacks (see conftest).
    clientside: Any = app.clientside_callback  # Untyped in Dash.
    clientside(
        """
        function (value, max) {
            const ok = typeof value === "number" && isFinite(value);
            const stepped = Math.round(value * 100) / 100;
            const valid = ok && value >= 0 && value <= max &&
                Math.abs(value - stepped) <= 2 * Number.EPSILON * Math.abs(value);
            const fraction = ok && max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;
            return [
                {"--level": fraction},
                ok ? value : 0,
                valid ? "TARGET " + stepped.toFixed(2) + " W"
                      : ok ? "TARGET INVALID" : "TARGET —",
            ];
        }
        """,
        Output("panel-knob", "style"),
        Output("panel-knob", "aria-valuenow"),
        Output("panel-target", "children"),
        Input("target-power", "value"),
        Input("target-power", "max"),
    )
    clientside(
        """
        function (setpoint, first, second, max) {
            // Only valid presets can match the stored-setpoint readback.
            return [first, second].map(function (preset) {
                if (typeof setpoint !== "number" || !isFinite(setpoint)) return "led unknown";
                if (typeof preset !== "number" || !isFinite(preset) || preset < 0 ||
                    preset > max || Math.abs(preset - Math.round(preset * 100) / 100) >
                    2 * Number.EPSILON * Math.abs(preset)) return "led";
                return Math.abs(setpoint - preset) < 5e-5 ? "led on" : "led";
            });
        }
        """,
        Output("panel-level-1-led", "className"),
        Output("panel-level-2-led", "className"),
        Input("panel-setpoint", "data"),
        Input("panel-level-1-value", "value"),
        Input("panel-level-2-value", "value"),
        Input("target-power", "max"),
    )

    return app


def run_gui(session: GuiSession, app: Any, port: int) -> None:
    """Own the HTTP server and worker; Close application drains I/O before shutdown."""
    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", port, app.server, threaded=True)

    def work() -> None:
        try:
            session.run()
        finally:
            server.shutdown()

    worker = Thread(target=work, name="verdi-monitor")
    worker.start()
    print(f"Verdi GUI: http://127.0.0.1:{server.server_port} (disconnected)", flush=True)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        if not session.stop.is_set():
            session.submit("close")
        worker.join()
        server.server_close()
    if error := session.snapshot()["error"]:
        raise VerdiError(error)
