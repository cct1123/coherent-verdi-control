"""Cache-only clients must remain truthful and responsive during acquisition faults."""

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


def callback_payload(app):
    key = next(iter(app.callback_map))
    return {
        "output": key,
        "outputs": [
            {"id": output.component_id, "property": output.component_property}
            for output in app.callback_map[key]["output"]
        ],
        "inputs": [{"id": "refresh", "property": "n_intervals", "value": 1}],
        "changedPropIds": ["refresh.n_intervals"],
        "state": [],
    }


def test_blank_exception_is_error_with_unavailable_current_values(monkeypatch):
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


def test_gui_is_responsive_during_blocked_controller_poll(monkeypatch):
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
            worker.join(5)
            service.stop()


def test_source_badge_tracks_sample_and_history_never_mixes_source_kinds():
    # This transport remains entirely in memory; only its source metadata differs.
    class NonSimulatedFake(SimulatedTransport):
        is_simulated = False

    with VerdiController(SimulatedTransport(), ControllerConfig(Model.V5)) as controller:
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


def test_oversized_integer_setpoint_fails_before_io():
    sim = SimulatedTransport()
    with VerdiController(sim, ControllerConfig(Model.V5, allow_writes=True)) as controller:
        with pytest.raises(ValueError, match="finite"):
            controller.set_power_w(10**1000)
        assert not sim.requests
