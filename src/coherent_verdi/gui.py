"""Optional Dash monitoring client. All data comes from one TelemetryService."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .telemetry import TelemetryService


def dashboard_data(service: TelemetryService) -> dict[str, Any]:
    """Read cached values only; rendering or opening a second tab never polls hardware."""
    samples = service.history
    last = samples[-1] if samples else None
    status = last.status if last else None
    age = (datetime.now(UTC) - status.sampled_at).total_seconds() if status else None
    stale = (
        status is not None
        and age is not None
        and age > max(5.0, 3 * service.interval_s + 2 * status.duration_s)
    )
    return {
        "simulated": service.controller.is_simulated,
        "health": "NO DATA"
        if last is None
        else ("ERROR" if last.error else "STALE" if stale else "LIVE"),
        "error": last.error if last else None,
        "age_s": age,
        "status": status,
        "timestamps": [s.attempted_at for s in samples],
        "power_w": [s.status.power_w if s.status else None for s in samples],
        "set_power_w": [s.status.set_power_w if s.status else None for s in samples],
        "count": len(samples),
    }


def create_app(service: TelemetryService) -> Any:
    """Caller owns service lifecycle. Does not connect, start threads or send commands.

    Monitoring-only by design. Use the API for authorized operations. Serve on
    loopback or behind your lab's authenticated proxy; do not use debug/reloader.
    """
    import plotly.graph_objects as go
    from dash import Dash, Input, Output, dcc, html

    app = Dash(__name__, assets_folder=str(Path(__file__).with_name("assets")))
    app.title = "Verdi | Telemetry"

    def tile(title: str, identifier: str, subtitle: str) -> Any:
        return html.Div(
            [
                html.Label(title),
                html.Div("—", id=identifier, className="metric"),
                html.Small(subtitle),
            ],
            className="tile",
        )

    app.layout = html.Main(
        [
            html.Header(
                [
                    html.Div(
                        [
                            html.Div("RESEARCH INSTRUMENTATION", className="eyebrow"),
                            html.H1(["Verdi", html.Span(" / Telemetry")]),
                        ]
                    ),
                    html.Div(
                        "SIMULATOR"
                        if service.controller.is_simulated
                        else "PHYSICAL / UNVALIDATED",
                        className="badge",
                    ),
                ]
            ),
            html.Div(
                [
                    html.Span("NO DATA", id="health", className="health"),
                    html.Span("Waiting for the telemetry service", id="sample-age"),
                ],
                className="statusbar",
            ),
            html.Div(id="error", role="alert"),
            html.Div(id="connection-warning", role="alert"),
            html.Section(
                [
                    tile("MEASURED POWER", "power", "W · reported by controller"),
                    tile("POWER SETPOINT", "setpoint", "W · light regulation"),
                    tile("LASER STATE", "laser", "Reported state is not a safety guarantee"),
                    tile("SAFETY SHUTTER", "shutter", "Not an experimental modulator"),
                ],
                className="tiles",
            ),
            html.Section(
                [
                    html.Div(
                        [
                            html.H2("Power history"),
                            html.Span("Bounded telemetry · failed samples shown as gaps"),
                        ],
                        className="section-title",
                    ),
                    dcc.Graph(id="power-graph", config={"displayModeBar": False}),
                ],
                className="panel",
            ),
            html.Section(
                [
                    html.Div(
                        [html.H2("Thermal diagnostics"), html.Div(id="temperatures")],
                        className="panel",
                    ),
                    html.Div(
                        [html.H2("Instrument status"), html.Div(id="instrument")], className="panel"
                    ),
                ],
                className="lower",
            ),
            html.Footer(
                "Monitoring client · one shared controller / telemetry service · "
                "software and simulator validation only; physical behavior untested"
            ),
            dcc.Interval(id="refresh", interval=1000, n_intervals=0),
            html.Span(id="server-heartbeat", hidden=True),
        ],
        id="dashboard",
    )

    @app.callback(
        Output("health", "children"),
        Output("sample-age", "children"),
        Output("error", "children"),
        Output("power", "children"),
        Output("setpoint", "children"),
        Output("laser", "children"),
        Output("shutter", "children"),
        Output("power-graph", "figure"),
        Output("temperatures", "children"),
        Output("instrument", "children"),
        Output("server-heartbeat", "children"),
        Input("refresh", "n_intervals"),
    )
    def refresh(_tick: int) -> tuple[Any, ...]:
        data = dashboard_data(service)
        s = data["status"]
        figure = go.Figure()
        figure.add_scatter(
            x=data["timestamps"],
            y=data["power_w"],
            name="Measured power",
            mode="lines",
            line={"color": "#65e3cc", "width": 2.5},
            connectgaps=False,
        )
        figure.add_scatter(
            x=data["timestamps"],
            y=data["set_power_w"],
            name="Setpoint",
            mode="lines",
            line={"color": "#8999b1", "dash": "dot"},
            connectgaps=False,
        )
        figure.update_layout(
            template="plotly_dark",
            paper_bgcolor="#151c28",
            plot_bgcolor="#151c28",
            margin={"l": 52, "r": 24, "t": 12, "b": 38},
            height=290,
            font={"family": "Segoe UI, sans-serif", "color": "#acb9ce"},
            yaxis_title="Power / W",
            xaxis_title="Time (UTC)",
            legend={"orientation": "h", "y": 1.14},
            uirevision="verdi-power",
        )

        def row(label: str, value: str) -> Any:
            return html.Div([html.Span(label), html.Strong(value)], className="data-row")

        thermal = [
            row(label, f"{getattr(s, field):.2f} °C" if s else "—")
            for label, field in [
                ("Diode 1", "diode_temp_c"),
                ("Heatsink", "heatsink_temp_c"),
                ("Baseplate", "baseplate_temp_c"),
                ("LBO", "lbo_temp_c"),
                ("Etalon", "etalon_temp_c"),
                ("Vanadate", "vanadate_temp_c"),
            ]
        ]
        instrument = [
            row("Configured model", service.controller.config.model.value),
            row("Keyswitch", ("ON" if s.keyswitch_on else "OFF") if s else "—"),
            row("Diode current", f"{s.diode_current_a:.1f} A" if s else "—"),
            row("LBO servo", s.lbo_servo.name if s else "—"),
            row(
                "Reported faults",
                ", ".join(f"{f.code}: {f.description}" for f in s.faults) or "None reported"
                if s
                else "Unknown",
            ),
            row("History samples", str(data["count"])),
        ]
        age = (
            f"Sample age {data['age_s']:.1f} s"
            if data["age_s"] is not None
            else "No current sample"
        )
        return (
            data["health"],
            age,
            data["error"] or "",
            f"{s.power_w:.3f}" if s else "—",
            f"{s.set_power_w:.4f}" if s else "—",
            s.laser_state.name if s else "UNKNOWN",
            ("OPEN" if s.shutter_open else "CLOSED") if s else "UNKNOWN",
            figure,
            thermal,
            instrument,
            _tick,
        )

    return app
