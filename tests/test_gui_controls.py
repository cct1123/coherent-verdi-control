"""Full GUI operation coverage; all device exchanges use in-memory fixtures."""

import json
from threading import Event, Thread

import pytest
from fakes import FaultyVerdi, RecordingVerdi

from coherent_verdi.__main__ import main
from coherent_verdi.controller import QUERIES, QUERY_INFO
from coherent_verdi.gui import (
    SERVICE_ACTIONS,
    Monitor,
    create_app,
    describe_action,
    display_value,
)


def submit(session, action, value=None, *, confirmed=True, client=None, sequence=1):
    return session.submit(
        client or session.new_client(), "service", sequence, action, value, confirmed=confirmed
    )


def result(session, key):
    return next(item for item in session.snapshot()["actions"] if item["id"] == key)


OPERATIONS = [
    ("power", 0.25, b"P=0.2500\r\n", "verified"),
    ("start", None, b"L=1\r\n", "verified"),
    ("standby", None, b"L=0\r\n", "verified"),
    ("shutter_open", None, b"S=1\r\n", "verified"),
    ("shutter_close", None, b"S=0\r\n", "verified"),
    ("lbo_on", None, b"LBOH=1\r\n", "verified"),
    ("lbo_off", None, b"LBOH=0\r\n", "verified"),
    ("optimize_lbo", None, b"LBOOPT=1\r\n", "acknowledged"),
    ("flash", None, b"FL=1\r\n", "acknowledged"),
    ("chiller_on", None, b"CHILLER=ON\r\n", "acknowledged"),
    ("chiller_temperature", "20.2", b"CHILLER=20.2\r\n", "acknowledged"),
    ("front_panel_lock", "1", b"LFP=1\r\n", "acknowledged"),
    ("exit_screen", None, b"EXIT=1\r\n", "acknowledged"),
    ("knob_down", None, b"KNOBDN=1\r\n", "acknowledged"),
    ("menu_down", None, b"MENUDN=1\r\n", "acknowledged"),
    ("menu_select", None, b"SELECT=1\r\n", "acknowledged"),
    ("menu_up", None, b"MENUUP=1\r\n", "acknowledged"),
    ("baudrate", "9600", b"B=9600\r\n", "verified"),
    ("echo_on", None, b"E=1\r\n", "acknowledged"),
    ("echo_off", None, b"E=0\r\n", "acknowledged"),
    ("prompt_on", None, b"PROMPT=0\r\n", "acknowledged"),
    ("prompt_off", None, b"PROMPT=1\r\n", "acknowledged"),
]


@pytest.mark.parametrize("action,value,wire,state", OPERATIONS)
def test_every_gui_write_and_available_readback(action, value, wire, state):
    with RecordingVerdi(allow_writes=True) as laser:
        laser.set_key(True)
        if action == "shutter_open":
            laser.start()
        monitor = Monitor(laser)
        session = monitor.controls
        monitor.poll_once()
        before = len(laser.requests)
        key = submit(session, action, value)
        assert len(laser.requests) == before  # Browser submission does no I/O.
        monitor.poll_once()
        record = result(session, key)
        assert laser.requests[before] == wire
        assert record["state"] == state
        assert record["transaction"]["request_hex"] == wire.hex()
        assert record["transaction"]["outcome"] == "acknowledged"
        if state == "verified":
            readback = record["readback"]
            assert readback["matches"] is True
            assert type(readback["expected"]) is type(readback["actual"])  # 9600, not 9600.0.
        else:
            assert record["readback"] is None  # Never invent an unsupported getter.


@pytest.mark.parametrize(
    "action,value,summary",
    [
        ("start", None, "Requested 1 · ON; read back 1 · ON"),
        ("power", 0.25, "Requested 0.25; read back 0.25 W"),
        ("baudrate", "9600", "Requested 9600; read back 9600 baud"),
        ("read", "?SV", "?SV: SIMULATOR"),
        ("read", "?L", "?L: 0 · STANDBY"),
    ],
)
def test_action_summaries_show_only_physical_units(action, value, summary):
    with RecordingVerdi(allow_writes=True) as laser:
        laser.set_key(True)
        monitor = Monitor(laser)
        monitor.poll_once()
        key = submit(monitor.controls, action, value)
        monitor.poll_once()
        assert describe_action(result(monitor.controls, key)) == summary


@pytest.mark.parametrize("value", ["", "   ", None])
def test_missing_service_operand_is_rejected_before_io(value):
    keys = []

    class MidSample(RecordingVerdi):
        armed = False

        def _simulate_response(self, request):
            if self.armed and request == b"?P\r\n":  # Arrives between overview reads.
                self.armed = False
                keys.append(submit(monitor.controls, "chiller_temperature", value))
            return super()._simulate_response(request)

    with MidSample(allow_writes=True) as laser:
        monitor = Monitor(laser)
        monitor.poll_once()  # A LIVE sample, so only the operand check can refuse.
        before = len(laser.requests)
        laser.armed = True
        sample = monitor.poll_once()
        record = result(monitor.controls, keys[0])
        assert record["state"] == "rejected" and "decimal temperature" in record["error"]
        assert b"CHILLER" not in b"".join(laser.requests[before:])
        # A write refused before I/O does not discard the overview sample.
        assert sample["status"] is not None and "interrupted" not in sample


def test_every_query_and_diagnostics_in_read_only_commissioning():
    assert set(QUERY_INFO) == QUERIES
    with RecordingVerdi() as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        session.set_commissioning()
        for query in QUERIES:
            before = len(laser.requests)
            key = submit(session, "read", query)
            monitor.poll_once()
            assert laser.requests[before:] == ((query + "\r\n").encode(),)
            assert result(session, key)["state"] == "read"
        key = submit(session, "diagnostics")
        monitor.poll_once()
        assert set(result(session, key)["result"]) == {"?SV", "?HH", "?PSH", "?D1H", "?FH"}
        assert len(session.snapshot()["queries"]) == 42
        assert display_value("?L", 0) == "0 · STANDBY"
        assert display_value("?LBOSS", 1) == "1 · LOCKED"


def test_raw_capture_can_inspect_unverified_empty_fault_reply_without_polling():
    with FaultyVerdi() as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        session.set_commissioning()
        laser.inject(b"\r\n")
        key = submit(session, "capture", "?F")
        monitor.poll_once()
        record = result(session, key)
        assert record["state"] == "captured"
        assert record["result"]["response_hex"] == "0d0a"
        assert not laser.failed
        assert laser.requests == (b"?F\r\n",)


@pytest.mark.parametrize("action", ["read", "capture", "diagnostics"])
def test_binary_reply_survives_gui_cache_and_json_export(action):
    payload = b"6.\x9605"
    with FaultyVerdi() as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        session.set_commissioning()
        laser.inject(b"?SV" + payload + b"\r\n")
        key = submit(session, action, None if action == "diagnostics" else "?SV")
        monitor.poll_once()
        record = result(session, key)
        assert record["state"] == ("captured" if action == "capture" else "read")
        value = record["result"]
        if action == "capture":
            assert value["payload"] is None and value["payload_hex"] == payload.hex()
            assert describe_action(record) == f"Captured bytes: {payload!r}"
        elif action == "diagnostics":
            assert value["?SV"] == {"bytes_hex": payload.hex()}
        else:
            assert value == {"bytes_hex": payload.hex()}
            assert describe_action(record) == f"?SV: {payload!r}"
        snapshot = session.snapshot()
        assert json.loads(json.dumps(snapshot, allow_nan=False)) == snapshot
        assert not laser.failed


def test_browser_cannot_override_write_permission_or_capture_restriction():
    with RecordingVerdi() as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        with pytest.raises(PermissionError, match="writes disabled"):
            submit(session, "power", 1)
        assert laser.requests == ()
    with RecordingVerdi(allow_writes=True) as laser:
        session = Monitor(laser).controls
        with pytest.raises(PermissionError, match="read-only"):
            submit(session, "capture", "?F")
        with pytest.raises(ValueError, match="read-only"):
            session.set_commissioning()


@pytest.mark.parametrize("action,value", [("power", 1), ("start", None), ("chiller_on", None)])
def test_stale_overview_rejects_writes_but_not_standby_or_close(action, value):
    now = [0.0]
    with RecordingVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser, clock=lambda: now[0])
        session = monitor.controls
        monitor.poll_once()
        now[0] = 6
        key = submit(session, action, value)
        monitor.poll_once()
        assert result(session, key)["state"] == "rejected"
        assert "fresh overview" in result(session, key)["error"]
        assert all(request.startswith(b"?") for request in laser.requests)
        now[0] = 12
        key = submit(session, "standby")
        monitor.poll_once()
        assert result(session, key)["state"] == "verified"


def test_start_and_open_require_readiness_confirmation_and_report_mismatched_state():
    with RecordingVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        monitor.poll_once()
        key = submit(session, "start", confirmed=False)
        monitor.poll_once()
        assert result(session, key)["state"] == "rejected"
        key = submit(session, "start")  # Key is OFF in this independent fixture.
        monitor.poll_once()
        assert result(session, key)["state"] == "mismatch"
        assert result(session, key)["readback"]["actual"] == 0


def test_duplicate_events_cross_browser_write_conflict_and_urgent_supersession():
    with RecordingVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        monitor.poll_once()
        client = session.new_client()
        key = submit(session, "power", 0.25, client=client)
        assert submit(session, "power", 0.5, client=client) == key
        with pytest.raises(PermissionError, match="another write"):
            submit(session, "start")
        stop = submit(session, "standby")
        monitor.poll_once()
        assert result(session, key)["state"] == "cancelled"
        assert result(session, stop)["state"] == "verified"
        assert not any(request.startswith(b"P=") for request in laser.requests)
        assert laser.requests.count(b"L=0\r\n") == 1
        assert submit(session, "power", 0.25, client=client) == key
        monitor.poll_once()
        assert not any(request.startswith(b"P=") for request in laser.requests)


def test_standby_and_shutter_close_are_both_preserved_when_queued_together():
    with RecordingVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        stop = submit(session, "standby")
        close = submit(session, "shutter_close")
        monitor.poll_once()
        assert result(session, stop)["state"] == result(session, close)["state"] == "verified"
        assert laser.requests[:4] == (b"L=0\r\n", b"?L\r\n", b"S=0\r\n", b"?S\r\n")


def test_standby_displaces_a_read_from_a_full_queue_and_runs_first():
    with RecordingVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        pending = [submit(session, "read", "?SV") for _ in range(16)]
        stop = submit(session, "standby")
        monitor.poll_once()
        assert laser.requests[0] == b"L=0\r\n"
        assert result(session, stop)["state"] == "verified"
        assert result(session, pending[-1])["state"] == "cancelled"


def test_command_interrupts_polling_between_reads_without_publishing_mixed_status(monkeypatch):
    with RecordingVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        monitor.poll_once()
        history_length = len(monitor.snapshot()["history"])
        before = len(laser.requests)
        original = laser._simulate_response
        queued = []

        def enqueue_after_first_read(request):
            answer = original(request)
            if not queued:
                queued.append(submit(session, "standby"))
            return answer

        monkeypatch.setattr(laser, "_simulate_response", enqueue_after_first_read)
        assert monitor.poll_once()["interrupted"] is True
        assert laser.requests[before:] == (b"?L\r\n", b"L=0\r\n", b"?L\r\n")
        assert len(monitor.snapshot()["history"]) == history_length
        assert result(session, queued[0])["state"] == "verified"
        monitor.poll_once()
        assert len(monitor.snapshot()["history"]) == history_length + 1


def test_old_evicted_action_cannot_replay_and_queue_is_bounded():
    with RecordingVerdi() as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        session.set_commissioning()
        client = session.new_client()
        for sequence in range(1, 132):
            submit(session, "read", "?SV", client=client, sequence=sequence)
            monitor.poll_once()
        with pytest.raises(ValueError, match="old action"):
            submit(session, "read", "?SV", client=client, sequence=1)
        for sequence in range(132, 148):
            submit(session, "read", "?SV", client=client, sequence=sequence)
        with pytest.raises(PermissionError, match="queue is full"):
            submit(session, "read", "?SV", client=client, sequence=148)


def test_expired_actions_and_shutdown_do_not_execute_queued_writes():
    now = [0.0]
    with RecordingVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser, clock=lambda: now[0])
        session = monitor.controls
        monitor.poll_once()
        key = submit(session, "power", 0.25)
        now[0] = 11
        monitor.poll_once()
        assert "expired" in result(session, key)["error"]
        key = submit(session, "standby")
        monitor.close()
        monitor.poll_once()
        assert result(session, key)["state"] == "cancelled"
        assert all(request.startswith(b"?") for request in laser.requests)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, "1;L=1"])
def test_invalid_gui_power_cannot_reach_wire(value):
    with RecordingVerdi(allow_writes=True, power_limit_w=0.5) as laser:
        monitor = Monitor(laser)
        session = monitor.controls
        monitor.poll_once()
        try:
            key = submit(session, "power", value)
        except ValueError:
            pass
        else:
            monitor.poll_once()
            assert result(session, key)["state"] == "rejected"
        assert all(request.startswith(b"?") for request in laser.requests)


def test_lost_ack_and_failed_readback_keep_distinct_wire_evidence():
    for readback in (False, True):
        with FaultyVerdi(allow_writes=True) as laser:
            monitor = Monitor(laser)
            session = monitor.controls
            monitor.poll_once()
            if readback:
                laser.inject(b"\r\n", after_apply=True)
            laser.inject_timeout(after_apply=not readback)
            key = submit(session, "power", 0.25)
            monitor.poll_once()
            record = result(session, key)
            assert record["state"] == ("readback_failed" if readback else "failed")
            assert record["transaction"]["outcome"] == ("acknowledged" if readback else "unknown")
            before = laser.requests
            with pytest.raises(PermissionError, match="failed"):
                submit(session, "standby")
            monitor.poll_once()
            assert laser.requests == before


def callback_request(app, output_id, *, trigger="refresh", count=1, state=None):
    key = next(key for key in app.callback_map if output_id in key)
    entry = app.callback_map[key]
    output = entry["output"]

    def describe(item):
        if isinstance(item, list):
            return [describe(child) for child in item]
        return {"id": item.component_id, "property": item.component_property}

    return {
        "output": key,
        "outputs": describe(output),
        "inputs": [
            {**item, "value": count if item["id"] == trigger else 0} for item in entry["inputs"]
        ],
        "state": [{**item, "value": (state or {}).get(item["id"])} for item in entry["state"]],
        "changedPropIds": [f"{trigger}.{'n_intervals' if trigger == 'refresh' else 'n_clicks'}"],
    }


def test_real_dash_callbacks_submit_without_io_and_render_all_results():
    with RecordingVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser)
        app = create_app(monitor)
        monitor.poll_once()
        client = app.server.test_client()
        layout = client.get("/_dash-layout")
        assert all(query.encode() in layout.data for query in QUERIES)
        assert all(action.encode() in layout.data for action in SERVICE_ACTIONS)
        token = monitor.controls.new_client()
        count = len(laser.requests)
        payload = callback_request(
            app,
            "submission.children",
            trigger="apply-power",
            state={
                "browser-session": token,
                "target-power": 0.25,
                "operator-ready": [],
                "service-action": "lbo_on",
                "service-value": "",
                "query-choice": "?SV",
            },
        )
        response = client.post("/_dash-update-component", json=payload)
        assert response.status_code == 200
        assert len(laser.requests) == count
        monitor.poll_once()
        response = client.post(
            "/_dash-update-component", json=callback_request(app, "query-results")
        )
        assert response.status_code == 200, response.data
        assert b"verified" in response.data
        assert b"request_hex" in response.data
        assert b"0.25" in response.data
        assert "target-power" not in response.json["response"]  # Unsent edits are untouched.


def test_rendering_and_submission_remain_responsive_during_a_blocked_exchange(monkeypatch):
    with RecordingVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser)
        app = create_app(monitor)
        monitor.poll_once()
        entered, release = Event(), Event()
        original = laser._simulate_response

        def blocked(request):
            entered.set()
            assert release.wait(3)
            return original(request)

        monkeypatch.setattr(laser, "_simulate_response", blocked)
        key = submit(monitor.controls, "power", 0.25)
        worker = Thread(target=monitor.poll_once)
        worker.start()
        try:
            assert entered.wait(2)
            response = app.server.test_client().post(
                "/_dash-update-component", json=callback_request(app, "query-results")
            )
            assert response.status_code == 200
            assert result(monitor.controls, key)["state"] == "running"
            submit(monitor.controls, "standby")
        finally:
            release.set()
            worker.join(3)
        assert not worker.is_alive()
        assert laser.requests.index(b"L=0\r\n") > laser.requests.index(b"P=0.2500\r\n")


def test_cli_gui_write_enablement_and_commissioning_flags(monkeypatch):
    from coherent_verdi import gui

    observed = []

    class App:
        def run(self, **settings):
            raise KeyboardInterrupt

    def build(monitor):
        observed.append(monitor.controls.snapshot())
        return App()

    monkeypatch.setattr(gui, "create_app", build)
    assert main(["gui", "--allow-writes", "--power-limit-w", "0.3"]) == 130
    assert observed[-1]["allow_writes"] and observed[-1]["power_limit_w"] == 0.3
    assert main(["gui", "--commission"]) == 130
    assert not observed[-1]["allow_writes"] and not observed[-1]["polling"]
    with pytest.raises(SystemExit):
        main(["gui", "--commission", "--allow-writes"])


def test_adapter_value_error_after_applying_write_is_failed_with_unknown_outcome():
    with FaultyVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser)
        monitor.poll_once()
        laser.inject(ValueError("adapter failed after applying write"), after_apply=True)
        key = submit(monitor.controls, "power", 0.25)
        monitor.poll_once()
        item = result(monitor.controls, key)
        assert laser._power == 0.25  # The independent fixture actually applied the command.
        assert item["state"] == "failed"
        assert item["transaction"]["outcome"] == "unknown"
        assert item["transaction"]["request_hex"] == b"P=0.2500\r\n".hex()
        assert laser.failed
        assert laser.requests.count(b"P=0.2500\r\n") == 1


def test_explicit_pause_then_resume_callbacks_do_not_depend_on_cached_polling_state():
    with RecordingVerdi() as laser:
        monitor = Monitor(laser)
        app = create_app(monitor)
        monitor.poll_once()
        client = app.server.test_client()
        before = laser.requests
        state = {"browser-session": monitor.controls.new_client()}
        for button in ("pause-polling", "resume-polling"):
            response = client.post(
                "/_dash-update-component",
                json=callback_request(app, "submission.children", trigger=button, state=state),
            )
            assert response.status_code == 200, response.data
            assert response.json["response"]["action-request"]["data"]
        assert laser.requests == before
        assert [item["value"] for item in monitor.controls.snapshot()["actions"]] == [False, True]
        monitor.poll_once()
        data = monitor.controls.snapshot()
        assert data["polling"]
        assert all(item["state"] == "applied" for item in data["actions"])


def test_repeated_pause_requests_are_idempotent_across_browsers():
    with RecordingVerdi() as laser:
        monitor = Monitor(laser)
        for _ in range(2):
            submit(monitor.controls, "polling", False)
        sample = monitor.poll_once()
        assert sample["paused"] and sample["status"] is None
        assert laser.requests == ()
        assert not monitor.controls.snapshot()["polling"]
        assert monitor.snapshot()["history"] == []
        submit(monitor.controls, "polling", True)
        assert monitor.poll_once()["status"] is not None


def test_fast_action_refresh_runs_only_while_requests_are_pending():
    with RecordingVerdi() as laser:
        monitor = Monitor(laser)
        monitor.controls.set_commissioning()
        app = create_app(monitor)
        client = app.server.test_client()

        def refresh():
            response = client.post(
                "/_dash-update-component", json=callback_request(app, "query-results")
            )
            assert response.status_code == 200, response.data
            return response.json["response"]["action-refresh"]["disabled"]

        assert refresh() is True
        submit(monitor.controls, "read", "?SV")
        assert refresh() is False
        monitor.poll_once()
        assert refresh() is True


def test_latest_and_incremental_plot_reads_never_copy_the_export_history(monkeypatch):
    with RecordingVerdi() as laser:
        monitor = Monitor(laser, history_size=3)
        returned = monitor.poll_once()
        returned["status"]["faults"].append(999)
        assert monitor.latest()["status"]["faults"] == []
        version, points = monitor.power_history()
        assert version == 1 and len(points) == 1
        assert monitor.power_history(version) == (version, [])
        for _ in range(4):
            monitor.poll_once()
        version, points = monitor.power_history(version)
        assert version == 5 and len(points) == 3
        assert points == monitor.power_history()[1]  # A disconnected browser catches up, bounded.

        def forbidden_export():
            raise AssertionError("browser must not deep-copy the full export history")

        monkeypatch.setattr(monitor, "snapshot", forbidden_export)
        app = create_app(monitor)
        response = app.server.test_client().post(
            "/_dash-update-component", json=callback_request(app, "query-results")
        )
        assert response.status_code == 200


def test_graph_updates_append_only_new_points_and_preserve_failure_gaps(callback_payload):
    with FaultyVerdi() as laser:
        monitor = Monitor(laser, history_size=3)
        for _ in range(5):
            monitor.poll_once()
        app = create_app(monitor)
        client = app.server.test_client()
        payload = callback_payload(app)
        response = client.post("/_dash-update-component", json=payload)
        data = response.json["response"]
        update, indices, maximum = data["power-graph"]["extendData"]
        assert len(update["y"][0]) == maximum == 3 and indices == [0, 1]
        payload["state"][0]["value"] = data["history-cursor"]["data"]
        response = client.post("/_dash-update-component", json=payload)
        assert "power-graph" not in response.json["response"]
        monitor.poll_once()
        response = client.post("/_dash-update-component", json=payload)
        data = response.json["response"]
        assert data["power-graph"]["extendData"][0]["y"] == [[0.0], [0.0]]
        payload["state"][0]["value"] = data["history-cursor"]["data"]
        laser.inject_timeout()
        monitor.poll_once()
        response = client.post("/_dash-update-component", json=payload)
        assert response.json["response"]["power-graph"]["extendData"][0]["y"] == [[None], [None]]


def test_wait_subtracts_acquisition_time_and_close_wakes_immediately(monkeypatch):
    now = [0.0]
    with RecordingVerdi() as laser:
        monitor = Monitor(laser, interval_s=1, clock=lambda: now[0])
        monitor.poll_once()
        waits = []
        monkeypatch.setattr(monitor.controls.wake, "wait", waits.append)
        now[0] = 0.4
        monitor.wait(Event())
        now[0] = 1.2
        monitor.wait(Event())
        assert waits == pytest.approx([0.6, 0])
        monitor.close()
        assert monitor.controls.wake.is_set()
        stop = Event()
        stop.set()
        monitor.wait(stop)
        assert len(waits) == 2


def panel_click(app, monitor, trigger, **state):
    """Click a front-panel key through the real submit callback; return the queued record."""
    before = {item["id"] for item in monitor.controls.snapshot()["actions"]}
    state = {"browser-session": monitor.controls.new_client(), "operator-ready": ["ready"]} | state
    response = app.server.test_client().post(
        "/_dash-update-component",
        json=callback_request(app, "submission.children", trigger=trigger, state=state),
    )
    assert response.status_code == 200, response.data
    new = [item for item in monitor.controls.snapshot()["actions"] if item["id"] not in before]
    return response.json["response"]["submission"]["children"], (new[0] if new else None)


def test_front_panel_display_and_lamps_never_invent_state():
    from coherent_verdi.gui import lcd_lines, panel_lamps

    with RecordingVerdi() as laser:
        monitor = Monitor(laser)
        empty = monitor.latest()
        assert lcd_lines(empty) == ("LIGHT        -.--- W", "NO DATA".ljust(20))
        assert set(panel_lamps(empty).values()) == {"led unknown", "unknown"}
        laser.set_key(True)
        monitor.poll_once()
        live = monitor.latest()
        assert lcd_lines(live) == ("LIGHT        0.000 W", "STANDBY SET  0.0000W")
        lamps = panel_lamps(live)
        assert lamps == {
            "ac": "led on",
            "emission": "led",
            "shutter": "led",
            "key": "on",
            "shown": "closed",
        }
        laser.set_faults(5, 12)
        monitor.poll_once()
        assert lcd_lines(monitor.latest())[1] == "FAULT 5,12".ljust(20)
        assert all(len(line) == 20 for line in lcd_lines(monitor.latest()))
        stale = live | {"health": "STALE"}
        assert lcd_lines(stale)[1].strip() == "STALE SAMPLE"
        assert panel_lamps(stale)["ac"] == "led unknown"


def test_front_panel_shutter_key_opens_only_when_browser_and_live_sample_agree():
    with RecordingVerdi(allow_writes=True) as laser:
        laser.set_key(True)
        laser.start()
        monitor = Monitor(laser)
        app = create_app(monitor)
        monitor.poll_once()
        for shown, action in (("closed", "shutter_open"), ("open", "shutter_close")):
            _, record = panel_click(app, monitor, "panel-shutter", **{"panel-shutter": shown})
            assert record["action"] == action
            monitor.poll_once()
        # The browser showed CLOSED, but the server's latest sample says OPEN: close it.
        laser.set_shutter(open=True)
        monitor.poll_once()
        _, record = panel_click(app, monitor, "panel-shutter", **{"panel-shutter": "closed"})
        assert record["action"] == "shutter_close"
        monitor.poll_once()
        # No live sample backs the browser's CLOSED: never open.
        stale = Monitor(laser)
        _, record = panel_click(
            create_app(stale), stale, "panel-shutter", **{"panel-shutter": "closed"}
        )
        assert record["action"] == "shutter_close"


def test_front_panel_keys_queue_documented_commands_and_presets():
    with RecordingVerdi(allow_writes=True) as laser:
        monitor = Monitor(laser)
        app = create_app(monitor)
        layout = app.server.test_client().get("/_dash-layout").data
        assert all(name.encode() in layout for name in ("front-panel", "panel-knob", "panel-ac"))
        monitor.poll_once()
        message, record = panel_click(app, monitor, "panel-level-1")
        assert record is None and "preset" in message
        for trigger, wire, state in (
            ("panel-menu-up", b"MENUUP=1\r\n", {}),
            ("panel-menu-down", b"MENUDN=1\r\n", {}),
            ("panel-select", b"SELECT=1\r\n", {}),
            ("panel-exit", b"EXIT=1\r\n", {}),
            ("panel-level-2", b"P=0.3000\r\n", {"panel-level-2-value": 0.3}),
            ("panel-apply-power", b"P=0.1250\r\n", {"target-power": 0.125}),
        ):
            before = len(laser.requests)
            _, record = panel_click(app, monitor, trigger, **state)
            assert record["state"] == "queued" and len(laser.requests) == before
            monitor.poll_once()
            assert laser.requests[before] == wire
            assert result(monitor.controls, record["id"])["state"] in ("acknowledged", "verified")


def test_front_panel_refresh_and_read_only_lock(callback_payload):
    with RecordingVerdi() as laser:
        laser.set_key(True)
        monitor = Monitor(laser)
        app = create_app(monitor)
        client = app.server.test_client()
        monitor.poll_once()
        data = client.post("/_dash-update-component", json=callback_payload(app)).json["response"]
        assert data["front-panel"]["className"] == "front-panel"
        assert data["panel-key"]["className"] == "keyswitch on"
        assert data["panel-shutter"]["data-shown"] == "closed"
        assert data["panel-setpoint"]["data"] == 0.0
        response = client.post(
            "/_dash-update-component", json=callback_request(app, "query-results")
        )
        controls = response.json["response"]
        assert controls["front-panel"] == {"disabled": True, "data-server-disabled": "true"}
        assert controls["panel-menu-up"]["disabled"] is True
