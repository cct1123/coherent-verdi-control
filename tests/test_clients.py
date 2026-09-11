"""TEST-006: cache-only Dash clients and simulator CLI workflows."""

import io
import json
from dataclasses import replace
from datetime import timedelta
from threading import Event, Thread

import pytest

from coherent_verdi import (
    ControllerConfig,
    Model,
    SimulatedTransport,
    TelemetryService,
    VerdiController,
)
from coherent_verdi.cli import main
from coherent_verdi.gui import create_app, dashboard_data


def test_bounded_history_failure_visibility_and_recovery():
    sim = SimulatedTransport()
    controller = VerdiController(sim, ControllerConfig(Model.V5))
    service = TelemetryService(controller, history_size=2)
    first = service.poll_once()
    assert first.status is not None and first.error is None
    sim.inject_timeout()
    failed = service.poll_once()
    assert failed.status is None
    assert failed.error_type == "ResponseTimeout"
    assert dashboard_data(service)["health"] == "ERROR"
    assert dashboard_data(service)["power_w"] == [0.0, None]
    service.poll_once()
    assert [s.sequence for s in service.history] == [2, 3]
    assert dashboard_data(service)["health"] == "LIVE"


def test_staleness_and_empty_history():
    now = [0.0]
    sim = SimulatedTransport()
    controller = VerdiController(sim, ControllerConfig(Model.V5))
    service = TelemetryService(controller, clock=lambda: now[0])
    assert dashboard_data(service)["health"] == "NO DATA"
    service.poll_once()
    now[0] = 60.0
    requests = sim.requests
    assert dashboard_data(service)["health"] == "STALE"
    assert dashboard_data(service)["age_s"] >= 60
    assert sim.requests == requests


@pytest.mark.parametrize("wall_clock_offset_s", [-3600, 3600])
def test_freshness_ignores_wall_clock_steps(monkeypatch, wall_clock_offset_s):
    now = [0.0]
    with VerdiController(SimulatedTransport(), ControllerConfig(Model.V5)) as controller:
        status = controller.status()
        shifted = replace(
            status, sampled_at=status.sampled_at + timedelta(seconds=wall_clock_offset_s)
        )
        monkeypatch.setattr(controller, "status", lambda: shifted)
        service = TelemetryService(controller, clock=lambda: now[0])
        service.poll_once()
        assert dashboard_data(service)["health"] == "LIVE"
        now[0] = 60
        assert dashboard_data(service)["health"] == "STALE"
        assert service.snapshot().age_s == 60


def test_freshness_includes_slow_sampling(monkeypatch):
    now = [0.0]
    with VerdiController(SimulatedTransport(), ControllerConfig(Model.V5)) as controller:
        original = controller.status

        def delayed():
            now[0] += 60
            return original()

        monkeypatch.setattr(controller, "status", delayed)
        service = TelemetryService(controller, clock=lambda: now[0])
        service.poll_once()
        assert service.snapshot().age_s == 60
        assert dashboard_data(service)["health"] == "STALE"


def test_dash_routes_callbacks_assets_and_no_independent_polling(callback_payload):
    sim = SimulatedTransport()
    controller = VerdiController(sim, ControllerConfig(Model.V5))
    service = TelemetryService(controller)
    service.poll_once()
    count = len(sim.requests)
    app = create_app(service)
    client = app.server.test_client()
    assert client.get("/").status_code == 200
    layout = client.get("/_dash-layout")
    assert layout.status_code == 200 and b"SIMULATOR" in layout.data
    assert client.get("/assets/style.css").status_code == 200
    assert client.get("/assets/watchdog.js").status_code == 200
    payload = callback_payload(app)
    for _ in range(3):  # independent browser clients all consume the same cache
        response = client.post("/_dash-update-component", json=payload)
        assert response.status_code == 200
        data = response.json["response"]
        assert data["health"]["children"] == "LIVE"
        assert data["power"]["children"] == "0.000"
        assert data["server-heartbeat"]["children"] == 1
    assert len(sim.requests) == count
    assert not service.running  # app creation doesn't spawn a worker
    sim.inject_timeout()
    service.poll_once()
    response = client.post("/_dash-update-component", json=payload)
    data = response.json["response"]
    assert data["health"]["children"] == "ERROR"
    assert data["laser"]["children"] == "UNKNOWN"
    assert data["error"]["children"]
    assert data["power-graph"]["figure"]["data"][0]["y"][-1] is None


def test_blank_exception_is_error_with_unavailable_current_values(monkeypatch, callback_payload):
    with VerdiController(SimulatedTransport(), ControllerConfig(Model.V5)) as controller:
        service = TelemetryService(controller)
        service.poll_once()

        def fail():
            raise RuntimeError()

        monkeypatch.setattr(controller, "status", fail)
        service.poll_once()
        data = dashboard_data(service)
        assert data["health"] == "ERROR"
        assert data["error"] == "RuntimeError"
        assert data["status"] is None and data["simulated"] is None
        assert data["power_w"] == [0.0, None]
        app = create_app(service)
        response = app.server.test_client().post(
            "/_dash-update-component", json=callback_payload(app)
        )
        assert response.status_code == 200
        values = response.json["response"]
        assert values["health"]["children"] == "ERROR"
        assert values["source"]["children"] == "SOURCE UNAVAILABLE"
        assert values["power"]["children"] == "—"


def test_gui_is_responsive_during_blocked_controller_poll(monkeypatch, callback_payload):
    sim = SimulatedTransport()
    with VerdiController(sim, ControllerConfig(Model.V5)) as controller:
        service = TelemetryService(controller)
        service.poll_once()
        entered, release, rendered = Event(), Event(), Event()
        original = sim.exchange

        def blocking(request):
            entered.set()
            assert release.wait(5)
            return original(request)

        monkeypatch.setattr(sim, "exchange", blocking)
        responses = []

        def render():
            app = create_app(service)
            responses.append(
                app.server.test_client().post("/_dash-update-component", json=callback_payload(app))
            )
            rendered.set()

        service.start()
        worker = Thread(target=render)
        try:
            assert entered.wait(2)
            count = len(sim.requests)
            worker.start()
            assert rendered.wait(2), "cached GUI waited for the controller transaction"
            assert len(sim.requests) == count
            assert responses[0].status_code == 200
            assert responses[0].json["response"]["source"]["children"] == "SIMULATOR"
        finally:
            release.set()
            if worker.ident is not None:
                worker.join(5)
            service.stop()


def test_source_badge_tracks_sample_and_history_never_mixes_source_kinds(callback_payload):
    # This transport remains entirely in memory; only its source metadata differs.
    class NonSimulatedFake(SimulatedTransport):
        is_simulated = False

    config = ControllerConfig(Model.V5, active_fault_clear_reply="SYSTEM OK")
    with VerdiController(SimulatedTransport(), config) as controller:
        service = TelemetryService(controller)
        service.poll_once()
        app = create_app(service)
        client = app.server.test_client()
        assert b"SIMULATOR" in client.get("/_dash-layout").data
        controller.replace_transport(NonSimulatedFake())
        service.poll_once()
        snapshot = service.snapshot()
        assert snapshot.simulated is False
        assert len(snapshot.history) == 1 and snapshot.history[0].sequence == 2
        response = client.post("/_dash-update-component", json=callback_payload(app))
        assert response.json["response"]["source"]["children"] == "PHYSICAL / UNVALIDATED"


@pytest.mark.parametrize(
    "args", [["status"], ["--model", "V2", "diagnostics"], ["query", "?SV"], ["--demo", "status"]]
)
def test_cli_read_paths(args, capsys):
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["simulated"] is True


def test_cli_explicit_writes_and_errors(capsys):
    assert main(["enable"]) == 2
    assert json.loads(capsys.readouterr().err)["type"] == "WritesDisabled"
    assert main(["--allow-writes", "set-power", "nan"]) == 2
    assert "finite" in capsys.readouterr().err
    assert main(["--allow-writes", "--sim-key-on", "enable"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["laser_state"] == 1
    assert main(["--demo", "shutter", "closed"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["shutter_open"] is False
    assert main(["--allow-writes", "set-power", "0.25"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["set_power_w"] == 0.25
    assert main(["--demo", "standby"]) == 0
    assert json.loads(capsys.readouterr().out)["result"]["laser_state"] == 0


def test_cli_watch_jsonlines_and_invalid_interval(capsys):
    assert main(["watch", "--count", "2", "--interval", "0.001"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["sample"]["sequence"] for row in rows] == [1, 2]
    assert main(["watch", "--interval", "nan"]) == 2
    assert capsys.readouterr().err


def test_cli_watch_flushes_each_record_before_waiting(monkeypatch):
    class Output(io.StringIO):
        flushes = 0

        def flush(self):
            self.flushes += 1

    output = Output()
    monkeypatch.setattr("coherent_verdi.cli.sys.stdout", output)

    def after_first_record(interval):
        assert output.flushes == 1
        assert json.loads(output.getvalue())["sample"]["sequence"] == 1

    monkeypatch.setattr("coherent_verdi.cli.sleep", after_first_record)
    assert main(["watch", "--count", "2"]) == 0
    assert output.flushes == 2


def test_cli_watch_returns_failure_when_any_sample_failed(monkeypatch, capsys):
    def fail(self):
        raise RuntimeError()

    monkeypatch.setattr(VerdiController, "status", fail)
    assert main(["watch", "--count", "1"]) == 2
    sample = json.loads(capsys.readouterr().out)["sample"]
    assert sample["status"] is None and sample["error_type"] == "RuntimeError"
