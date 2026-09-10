"""TEST-005/006: lifecycle, bounded storage, stale/error UI and CLI workflows."""

import json
from threading import Event

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


def setup_service(**kwargs):
    sim = SimulatedTransport()
    c = VerdiController(sim, ControllerConfig(Model.V5))
    return sim, c, TelemetryService(c, **kwargs)


def test_bounded_history_failure_visibility_and_recovery():
    sim, _, service = setup_service(history_size=2)
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


def test_programming_errors_are_visible_in_background_sample(monkeypatch):
    _, c, service = setup_service()

    def broken():
        raise RuntimeError("injected application bug")

    monkeypatch.setattr(c, "status", broken)
    assert service.poll_once().error_type == "RuntimeError"


def test_staleness_and_empty_history():
    now = [0.0]
    sim, _, service = setup_service(clock=lambda: now[0])
    assert dashboard_data(service)["health"] == "NO DATA"
    service.poll_once()
    now[0] = 60.0
    requests = sim.requests
    assert dashboard_data(service)["health"] == "STALE"
    assert dashboard_data(service)["age_s"] >= 60
    assert sim.requests == requests


def test_start_stop_idempotent_restart_and_controller_ownership(monkeypatch):
    _, c, service = setup_service(interval_s=0.01)
    observed = Event()
    real_status = c.status

    def record_status():
        result = real_status()
        observed.set()
        return result

    monkeypatch.setattr(c, "status", record_status)
    assert not service.running
    service.start()
    service.start()
    assert observed.wait(2)
    service.stop()
    service.stop()
    assert not service.running
    assert c.power_w() == 0.0  # service does not own/close controller
    observed.clear()
    service.start()
    assert observed.wait(2)
    service.stop()
    c.close()


def test_stop_timeout_does_not_claim_worker_stopped(monkeypatch):
    _, c, service = setup_service()
    entered, release = Event(), Event()
    original = c.status

    def delayed():
        entered.set()
        assert release.wait(2)
        return original()

    monkeypatch.setattr(c, "status", delayed)
    service.start()
    try:
        assert entered.wait(2)
        with pytest.raises(TimeoutError, match="still sampling"):
            service.stop(timeout_s=0.001)
        assert service.running
    finally:
        release.set()
        service.stop()


def test_dash_routes_callbacks_assets_and_no_independent_polling(callback_payload):
    sim, _, service = setup_service()
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


def test_cli_watch_jsonlines_and_invalid_interval(capsys):
    assert main(["watch", "--count", "2", "--interval", "0.001"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["sample"]["sequence"] for row in rows] == [1, 2]
    assert main(["watch", "--interval", "nan"]) == 2
    assert capsys.readouterr().err


@pytest.mark.parametrize(
    "kwargs",
    [{"interval_s": 0}, {"interval_s": float("nan")}, {"history_size": 0}, {"history_size": True}],
)
def test_invalid_service_configuration(kwargs):
    with pytest.raises(ValueError):
        setup_service(**kwargs)
