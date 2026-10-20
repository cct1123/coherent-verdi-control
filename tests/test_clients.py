"""Cache-only Dash clients and read-only CLI workflows with simulated devices."""

import io
import json
import subprocess
import sys
from datetime import datetime, timedelta
from threading import Event, Thread
from threading import enumerate as threads

import pytest
from fakes import FaultyVerdi
from fakes import RecordingVerdi as SimulatedVerdi

from coherent_verdi import VerdiController
from coherent_verdi.__main__ import main
from coherent_verdi.gui import Monitor, create_app


def rendered_components(response):
    """Index the components returned by the single dashboard-body callback."""
    values = response.json["response"]

    def collect(node):
        if isinstance(node, list):
            for child in node:
                collect(child)
        elif isinstance(node, dict):
            props = node.get("props", {})
            if "id" in props:
                values[props["id"]] = props
            collect(props.get("children"))

    collect(values["sample"]["children"])
    return values


def test_bounded_history_failure_visibility_and_recovery():
    sim = FaultyVerdi(model="V5")
    controller = sim
    controller.connect()
    service = Monitor(controller, history_size=2)
    first = service.poll_once()
    assert first["status"] is not None and first["error"] is None
    sim.inject_timeout()
    failed = service.poll_once()
    assert failed["status"] is None
    assert failed["error"].startswith("VerdiError:")
    assert service.snapshot()["health"] == "ERROR"
    assert [
        s["status"]["power_w"] if s["status"] else None for s in service.snapshot()["history"]
    ] == [0.0, None]
    service.poll_once()
    assert len(service.snapshot()["history"]) == 2
    assert all(s["status"] is None for s in service.snapshot()["history"])
    assert service.snapshot()["health"] == "ERROR"
    assert len(sim.requests) == 15  # No extra I/O after failure.


def test_staleness_and_empty_history():
    now = [0.0]
    sim = SimulatedVerdi(model="V5")
    controller = sim
    controller.connect()
    service = Monitor(controller, clock=lambda: now[0])
    assert service.snapshot()["health"] == "NO DATA"
    service.poll_once()
    now[0] = 60.0
    requests = sim.requests
    assert service.snapshot()["health"] == "STALE"
    assert service.snapshot()["age_s"] >= 60
    assert sim.requests == requests


@pytest.mark.parametrize("wall_clock_offset_s", [-3600, 3600])
def test_freshness_ignores_wall_clock_steps(monkeypatch, wall_clock_offset_s):
    now = [0.0]
    with SimulatedVerdi(model="V5") as controller:
        status = controller.status()
        shifted = status | {
            "sampled_at": (
                datetime.fromisoformat(status["sampled_at"])
                + timedelta(seconds=wall_clock_offset_s)
            ).isoformat()
        }
        monkeypatch.setattr(controller, "status", lambda: shifted)
        service = Monitor(controller, clock=lambda: now[0])
        service.poll_once()
        assert service.snapshot()["health"] == "LIVE"
        now[0] = 60
        assert service.snapshot()["health"] == "STALE"
        assert service.snapshot()["age_s"] == 60


def test_freshness_includes_slow_sampling(monkeypatch):
    now = [0.0]
    with SimulatedVerdi(model="V5") as controller:
        original = controller.status

        def delayed():
            now[0] += 60
            return original()

        monkeypatch.setattr(controller, "status", delayed)
        service = Monitor(controller, clock=lambda: now[0])
        service.poll_once()
        assert service.snapshot()["age_s"] == 60
        assert service.snapshot()["health"] == "STALE"


def test_dash_routes_callbacks_assets_and_no_independent_polling(callback_payload):
    sim = FaultyVerdi(model="V5")
    controller = sim
    controller.connect()
    service = Monitor(controller)
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
        data = rendered_components(response)
        assert data["health"]["children"] == "LIVE"
        assert data["power"]["children"] == "0.000"
        assert data["server-heartbeat"]["children"] == 1
    assert len(sim.requests) == count
    sim.inject_timeout()
    service.poll_once()
    response = client.post("/_dash-update-component", json=payload)
    data = rendered_components(response)
    assert data["health"]["children"] == "ERROR"
    assert data["laser"]["children"] == "UNKNOWN"
    assert data["error"]["children"]
    assert data["power-graph"]["figure"]["data"][0]["y"][-1] is None


def test_blank_exception_is_error_with_unavailable_current_values(monkeypatch, callback_payload):
    with SimulatedVerdi(model="V5") as controller:
        service = Monitor(controller)
        service.poll_once()

        def fail():
            raise RuntimeError()

        monkeypatch.setattr(controller, "status", fail)
        service.poll_once()
        data = service.snapshot()
        assert data["health"] == "ERROR"
        assert data["error"] == "RuntimeError:"
        assert data["status"] is None and data["simulated"] is True
        assert [s["status"]["power_w"] if s["status"] else None for s in data["history"]] == [
            0.0,
            None,
        ]
        app = create_app(service)
        response = app.server.test_client().post(
            "/_dash-update-component", json=callback_payload(app)
        )
        assert response.status_code == 200
        values = rendered_components(response)
        assert values["health"]["children"] == "ERROR"
        assert b"SIMULATOR" in app.server.test_client().get("/_dash-layout").data
        assert values["power"]["children"] == "—"


def test_gui_is_responsive_during_blocked_controller_poll(monkeypatch, callback_payload):
    sim = SimulatedVerdi(model="V5")
    with sim as controller:
        service = Monitor(controller)
        service.poll_once()
        entered, release, rendered = Event(), Event(), Event()
        original = sim._exchange
        attempted = []

        def blocking(request):
            attempted.append(request)
            entered.set()
            assert release.wait(5)
            return original(request)

        monkeypatch.setattr(sim, "_exchange", blocking)
        responses = []

        def render():
            app = create_app(service)
            responses.append(
                app.server.test_client().post("/_dash-update-component", json=callback_payload(app))
            )
            rendered.set()

        poller = Thread(target=service.poll_once)
        poller.start()
        worker = Thread(target=render)
        try:
            assert entered.wait(2)
            count = len(attempted)
            worker.start()
            assert rendered.wait(2), "cached GUI waited for the controller transaction"
            assert len(attempted) == count
            assert responses[0].status_code == 200
            assert rendered_components(responses[0])["health"]["children"] == "LIVE"
        finally:
            release.set()
            if worker.ident is not None:
                worker.join(5)
            poller.join(5)
            assert not poller.is_alive()


@pytest.mark.parametrize("args", [["status"], ["--model", "V2", "diagnostics"], ["query", "?SV"]])
def test_cli_read_paths(args, capsys):
    assert main(args) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == "SIMULATOR" if args[0] == "query" else isinstance(data, dict)


@pytest.fixture
def serial_cli(monkeypatch):
    """Run the real controller with an independent in-memory serial peer."""
    sim = SimulatedVerdi("V5")
    opened = []

    def open_serial(controller):
        opened.append(controller)
        sim.connect()

    monkeypatch.setattr(VerdiController, "_open", open_serial)
    monkeypatch.setattr(VerdiController, "_close", lambda controller: sim.disconnect())
    monkeypatch.setattr(
        VerdiController, "_exchange", lambda controller, request: sim._exchange(request)
    )
    yield sim, opened
    sim.disconnect()


def test_cli_hardware_status_and_watch_use_verified_fault_reply(serial_cli, capsys):
    sim, opened = serial_cli
    settings = ["--port", "FAKE-ONLY", "--model", "V5", "--active-fault-clear-reply", "SYSTEM OK"]
    assert main([*settings, "status"]) == 0
    assert json.loads(capsys.readouterr().out)["simulated"] is False
    assert main([*settings, "watch", "--count", "2", "--interval", "0.001"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 2 and all(row["status"]["faults"] == [] for row in rows)
    assert all(row["status"]["simulated"] is False for row in rows)
    assert len(opened) == 2 and all(c._allow_writes is False for c in opened)
    assert all(request.startswith(b"?") for request in sim.requests)


def test_cli_hardware_gui_separates_serial_and_http_ports(serial_cli, monkeypatch):
    _, opened = serial_cli
    received_sample = Event()
    original_poll = Monitor.poll_once

    def poll(monitor):
        result = original_poll(monitor)
        received_sample.set()
        return result

    class App:
        def run(self, **settings):
            assert settings["port"] == 8051
            assert received_sample.wait(3)
            raise KeyboardInterrupt

    monkeypatch.setattr(Monitor, "poll_once", poll)
    monkeypatch.setattr("coherent_verdi.gui.create_app", lambda monitor: App())
    assert (
        main(
            [
                "--port",
                "FAKE-ONLY",
                "--model",
                "V5",
                "--active-fault-clear-reply",
                "SYSTEM OK",
                "gui",
                "--port",
                "8051",
            ]
        )
        == 130
    )
    assert len(opened) == 1 and opened[0]._port == "FAKE-ONLY"
    assert opened[0]._connected is False


def test_cli_hardware_status_rejects_unverified_clear_reply(serial_cli, capsys):
    sim, _ = serial_cli
    assert main(["--port", "FAKE-ONLY", "--model", "V5", "status"]) == 2
    assert "invalid fault list" in json.loads(capsys.readouterr().err)["error"]
    assert sim.requests[-1] == b"?F\r\n"


def test_cli_watch_jsonlines_and_invalid_interval(capsys):
    assert main(["watch", "--count", "2", "--interval", "0.001"]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 2 and all(row["status"]["simulated"] for row in rows)
    assert main(["watch", "--interval", "nan"]) == 2
    assert capsys.readouterr().err


def test_cli_watch_flushes_each_record_before_waiting(monkeypatch):
    class Output(io.StringIO):
        flushes = 0

        def flush(self):
            self.flushes += 1

    output = Output()
    monkeypatch.setattr("coherent_verdi.__main__.sys.stdout", output)

    def after_first_record(interval):
        assert output.flushes == 1
        assert json.loads(output.getvalue())["status"]["simulated"] is True

    monkeypatch.setattr("coherent_verdi.__main__.sleep", after_first_record)
    assert main(["watch", "--count", "2"]) == 0
    assert output.flushes == 2


def test_cli_watch_returns_failure_when_any_sample_failed(monkeypatch, capsys):
    def fail(self):
        raise RuntimeError()

    monkeypatch.setattr(VerdiController, "status", fail)
    assert main(["watch", "--count", "1"]) == 2
    sample = json.loads(capsys.readouterr().out)
    assert sample["status"] is None and sample["error"] == "RuntimeError:"


def test_gui_launcher_drains_acquisition_before_disconnect(monkeypatch):
    entered, release, finished = Event(), Event(), Event()
    original_status = VerdiController.status
    original_disconnect = VerdiController.disconnect

    def sample(controller):
        entered.set()
        assert release.wait(3)
        result = original_status(controller)
        finished.set()
        return result

    def disconnect(controller):
        assert finished.is_set(), "connection closed before acquisition finished"
        original_disconnect(controller)

    class App:
        def run(self, **settings):
            assert settings["host"] == "127.0.0.1"
            assert not settings["debug"] and not settings["use_reloader"]
            assert entered.wait(3)
            release.set()
            raise KeyboardInterrupt

    monkeypatch.setattr(VerdiController, "status", sample)
    monkeypatch.setattr(VerdiController, "disconnect", disconnect)
    monkeypatch.setattr("coherent_verdi.gui.create_app", lambda monitor: App())
    assert main(["gui"]) == 130


@pytest.mark.parametrize(
    "options",
    [
        {"interval_s": 0},
        {"interval_s": float("nan")},
        {"history_size": 0},
        {"history_size": True},
    ],
)
def test_invalid_monitor_settings(options):
    with pytest.raises(ValueError):
        Monitor(SimulatedVerdi(), **options)


def test_sampling_is_explicit_bounded_and_does_not_own_the_connection():
    before = threads()
    sim = SimulatedVerdi()
    laser = sim
    monitor = Monitor(laser, history_size=17)
    assert not sim.requests and monitor.snapshot()["history"] == []
    laser.connect()
    for _ in range(1000):
        assert monitor.poll_once()["error"] is None
    samples = monitor.snapshot()["history"]
    assert len(samples) == 17
    samples[-1]["status"]["faults"].append(999)
    assert monitor.snapshot()["history"][-1]["status"]["faults"] == []
    assert len(sim.requests) == 4096
    assert threads() == before
    record = json.loads(json.dumps(samples[-1]))
    assert record["status"]["power_w"] == 0
    assert record["status"]["sampled_at"].endswith("+00:00")
    laser.disconnect()
    failure = monitor.poll_once()
    assert failure["status"] is None and "VerdiError" in failure["error"]


def test_core_import_does_not_load_optional_clients_or_start_threads():
    code = """
import sys, threading
before = threading.enumerate()
from coherent_verdi import VerdiController, SimulatedVerdi
with SimulatedVerdi() as laser:
    assert laser.read('?P') == 0
assert threading.enumerate() == before
for name in ('serial', 'dash', 'plotly', 'coherent_verdi.gui'):
    assert name not in sys.modules, name
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=15)
