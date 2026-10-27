"""Connection and monitoring lifecycle through fake ports and real Dash requests."""

from threading import Event, Thread
from types import SimpleNamespace

import pytest
from dash_helpers import callback_request

from coherent_verdi import VerdiError
from coherent_verdi.gui import GuiSession, create_app, run_gui


def session_action(session, action, value=None):
    controls = session.monitor.controls
    return controls.submit(controls.new_client(), "service", 1, action, value)


def hardware_session():
    return GuiSession(port="FAKE-ONLY", model="V2", baudrate=19200, clear_reply="SYSTEM OK")


def test_connect_is_passive_then_monitor_pause_interval_and_disconnect(v2_serial, v2_replies):
    session = hardware_session()
    assert session.snapshot()["state"] == "DISCONNECTED"
    assert v2_serial.opens == 0
    session.submit("connect")
    session.step()
    session.step()
    assert session.snapshot()["state"] == "CONNECTED"
    assert v2_serial.opens == 1 and v2_serial.writes == []
    assert not session.monitor.controls.polling

    session_action(session, "interval", 2.5)
    session_action(session, "polling", True)
    session.step()
    data = session.monitor.latest()
    assert data["health"] == "LIVE"
    assert data["status"]["diode_temp_c"] == float(v2_replies[b"?D1T"])
    assert data["status"]["diode_current_a"] == float(v2_replies[b"?D1C"])
    assert data["status"]["power_w"] == float(v2_replies[b"?P"])
    assert session.monitor.interval_s == 2.5

    count = len(v2_serial.writes)
    session_action(session, "polling", False)
    session.step()
    session.step()
    assert len(v2_serial.writes) == count
    session.submit("disconnect")
    session.step()
    assert session.snapshot()["state"] == "DISCONNECTED"
    assert v2_serial.closes == 1
    assert session.monitor.latest()["status"] is None
    assert not session.monitor.snapshot()["history"]
    assert all(request.startswith(b"?") for request in v2_serial.writes)


def test_monitoring_requires_verified_clear_text_but_capture_does_not(v2_serial):
    session = GuiSession(port="FAKE-ONLY", model="V2")
    session.submit("connect")
    session.step()
    session_action(session, "polling", True)
    session.step()
    assert not v2_serial.writes
    assert not session.monitor.controls.polling
    assert "verify" in session.monitor.controls.snapshot()["actions"][-1]["error"]
    session_action(session, "capture", "?F")
    session.step()
    assert v2_serial.writes == [b"?F\r\n"]
    session.submit("close")
    session.step()


def test_failed_open_can_be_retried_with_a_new_controller(peer):
    session = hardware_session()
    peer.open_failure = OSError("port busy")
    session.submit("connect")
    session.step()
    assert session.snapshot()["state"] == "ERROR"
    assert "port busy" in session.snapshot()["error"]
    assert not session.snapshot()["connected"] and not peer.writes
    peer.open_failure = None
    session.submit("connect")
    session.step()
    assert session.snapshot()["connected"] and peer.opens == 2
    assert not session.monitor.controls.controller.failed
    session.submit("close")
    session.step()


@pytest.mark.parametrize("value", [0, -1, 3601, True])
def test_invalid_monitoring_interval_preserves_previous_setting(v2_serial, value):
    session = hardware_session()
    session.submit("connect")
    session.step()
    session_action(session, "interval", value)
    session.step()
    assert session.monitor.interval_s == 1
    assert not v2_serial.writes
    session.submit("close")
    session.step()


def test_disconnect_cancels_queued_writes_without_sending_them(peer):
    session = GuiSession(port="FAKE-ONLY", model="V2", allow_writes=True)
    session.submit("connect")
    session.step()
    session_action(session, "standby")
    session.submit("disconnect")
    session.step()
    assert peer.writes == [] and peer.closes == 1


def test_failed_disconnect_requires_explicit_cleanup_before_reconnecting(peer):
    session = hardware_session()
    session.submit("connect")
    session.step()
    peer.close_failure = OSError("close failed")
    session.submit("disconnect")
    session.step()
    assert session.snapshot()["state"] == "ERROR"
    assert session.snapshot()["connected"]
    with pytest.raises(PermissionError, match="disconnect"):
        session.submit("connect")
    peer.close_failure = None
    session.submit("disconnect")
    session.step()
    assert not session.snapshot()["connected"]
    assert peer.closes == 2 and not peer.writes


def test_close_application_waits_for_current_exchange_before_stopping_server(
    v2_serial, monkeypatch
):
    session = hardware_session()
    entered, release, stopped = Event(), Event(), Event()
    read_until = v2_serial.read_until

    def blocked_read(expected, size=None):
        entered.set()
        assert release.wait(3)
        return read_until(expected, size)

    monkeypatch.setattr(v2_serial, "read_until", blocked_read)

    class Server:
        server_port = 8051

        def serve_forever(self, **kwargs):
            session.submit("connect")
            # The worker wakes from its wait when Connect is queued.
            for _ in range(100):
                if session.snapshot()["connected"]:
                    break
                stopped.wait(0.01)
            assert session.snapshot()["connected"]
            session_action(session, "polling", True)
            assert entered.wait(3)
            session.submit("close")
            assert v2_serial.closes == 0
            release.set()
            assert stopped.wait(3)

        def shutdown(self):
            assert v2_serial.closes == 1
            stopped.set()

        def server_close(self):
            assert stopped.is_set()

    monkeypatch.setattr("werkzeug.serving.make_server", lambda *args, **kwargs: Server())
    try:
        run_gui(session, SimpleNamespace(server=object()), 8051)
    finally:
        release.set()
    assert session.stop.is_set() and session.snapshot()["state"] == "CLOSED"
    assert v2_serial.writes == [b"?L\r\n"]


def test_dash_connection_toggle_only_enqueues_the_displayed_action(v2_serial):
    session = hardware_session()
    app = create_app(session.monitor, session=session)
    client = app.server.test_client()
    state = {
        "connection-toggle": "Connect",
        "connection-source": "hardware",
        "connection-port": "FAKE-ONLY",
        "connection-model": "V2",
        "connection-baud": 19200,
        "connection-clear": "SYSTEM OK",
    }

    def click(label, count):
        return client.post(
            "/_dash-update-component",
            json=callback_request(
                app,
                "connection-message",
                trigger="connection-toggle",
                count=count,
                state=state | {"connection-toggle": label},
            ),
        )

    def refresh():
        response = client.post(
            "/_dash-update-component", json=callback_request(app, "connection-state")
        )
        assert response.status_code == 200, response.data
        return response.json["response"]["connection-toggle"]

    assert refresh()["children"] == "Connect"
    response = click("Connect", 1)
    assert response.status_code == 200
    assert v2_serial.opens == 0 and not v2_serial.writes
    assert refresh()["children"] == "Connecting…"
    assert refresh()["disabled"]
    session.step()
    assert v2_serial.opens == 1 and not v2_serial.writes
    assert refresh()["children"] == "Disconnect"
    assert not refresh()["disabled"]
    # A delayed Connect event must not toggle the new connection back off.
    response = click("Connect", 1)
    assert "disconnect before" in response.json["response"]["connection-message"]["children"]
    assert session.snapshot()["connected"] and v2_serial.closes == 0
    response = click("Disconnect", 2)
    assert response.status_code == 200
    assert v2_serial.closes == 0
    assert refresh()["children"] == "Disconnecting…"
    assert refresh()["disabled"]
    session.step()
    assert v2_serial.closes == 1 and not v2_serial.writes
    assert refresh()["children"] == "Connect"
    assert not refresh()["disabled"]


def test_runtime_never_takes_a_port_owned_by_another_controller(peer):
    from coherent_verdi import VerdiController

    with VerdiController("FAKE-ONLY", model="V2") as owner:
        session = hardware_session()
        session.submit("connect")
        session.step()
        assert session.snapshot()["state"] == "ERROR"
        assert "already belongs" in session.snapshot()["error"]
        assert peer.opens == 1 and peer.closes == 0
        assert owner.last_transaction is None
        session.submit("close")
        session.step()
    assert peer.closes == 1 and peer.writes == []


def test_failed_monitoring_requires_disconnect_and_reconnect(v2_serial):
    session = hardware_session()
    session.submit("connect")
    session.step()
    old = session.monitor.controls.controller
    v2_serial.read_failure = OSError("link lost")
    session_action(session, "polling", True)
    session.step()
    assert session.snapshot()["state"] == "ERROR"
    assert old.failed
    assert not session.monitor.controls.polling
    count = len(v2_serial.writes)
    session.step()
    assert len(v2_serial.writes) == count  # No replay after a transport failure.
    assert not session.monitor.controls.wake.is_set()  # The failed worker can sleep.
    session.submit("disconnect")
    session.step()
    v2_serial.read_failure = None
    # Opening pySerial normally purges queues; emulate that local open behavior here.
    v2_serial.pending.clear()
    session.submit("connect")
    session.step()
    assert session.monitor.controls.controller is not old
    assert not session.monitor.controls.controller.failed
    assert not session.monitor.controls.polling
    assert session.monitor.latest()["status"] is None
    session.submit("close")
    session.step()


def test_reconnection_clears_the_browser_plot(v2_serial, callback_payload):
    session = hardware_session()
    app = create_app(session.monitor, session=session)
    client = app.server.test_client()
    session.submit("connect")
    session.step()
    session_action(session, "polling", True)
    session.step()
    request = callback_payload(app)
    data = client.post("/_dash-update-component", json=request).get_json()["response"]
    generation = data["connection-generation"]["data"]
    assert data["power-graph"]["figure"]["data"][0]["x"] == []
    session.submit("disconnect")
    session.step()
    request["state"][1]["value"] = generation
    data = client.post("/_dash-update-component", json=request).get_json()["response"]
    assert data["power-graph"]["figure"]["data"][0]["x"] == []
    assert data["connection-generation"]["data"] > generation
    assert data["history-cursor"]["data"] == 0


def test_ctrl_c_releases_the_connection_and_stops_the_worker(v2_serial, monkeypatch):
    session = hardware_session()
    closed, stopped = Event(), Event()
    session.submit("connect")
    session.step()

    class Server:
        server_port = 8051

        def serve_forever(self, **kwargs):
            raise KeyboardInterrupt

        def shutdown(self):
            stopped.set()

        def server_close(self):
            closed.set()

    monkeypatch.setattr("werkzeug.serving.make_server", lambda *args, **kwargs: Server())
    with pytest.raises(KeyboardInterrupt):
        run_gui(session, SimpleNamespace(server=object()), 8051)
    assert v2_serial.closes == 1 and not v2_serial.writes
    assert closed.is_set() and stopped.is_set() and session.stop.is_set()


def test_close_cancels_a_connect_that_has_not_started(peer):
    session = hardware_session()
    session.submit("connect")
    session.submit("close")
    session.step()
    assert session.stop.is_set()
    assert peer.opens == 0 and peer.writes == []


def test_connect_handoff_keeps_the_new_connection_accepting(v2_serial, monkeypatch):
    session = hardware_session()
    entered, release, opened = Event(), Event(), Event()
    close = session.monitor.controls.close
    open_port = v2_serial.open

    def delayed_close():
        entered.set()
        assert release.wait(3)
        close()

    def track_open():
        open_port()
        opened.set()

    monkeypatch.setattr(session.monitor.controls, "close", delayed_close)
    monkeypatch.setattr(v2_serial, "open", track_open)
    callback = Thread(target=session.submit, args=("connect",))
    worker = Thread(target=session.step)
    try:
        callback.start()
        assert entered.wait(3)
        worker.start()
        assert not opened.wait(0.05), "worker opened before queue admission was closed"
    finally:
        release.set()
        callback.join(3)
        if worker.ident is not None:
            worker.join(3)
    assert not callback.is_alive() and not worker.is_alive()
    assert session.snapshot()["state"] == "CONNECTED"
    assert session.monitor.controls.snapshot()["accepting"]
    session_action(session, "capture", "?SV")
    session.step()
    assert v2_serial.writes == [b"?SV\r\n"]
    session.submit("close")
    session.step()


def test_close_during_connect_keeps_device_actions_disabled(v2_serial, monkeypatch):
    session = hardware_session()
    entered, release = Event(), Event()
    open_port = v2_serial.open

    def blocked_open():
        open_port()
        entered.set()
        assert release.wait(3)

    monkeypatch.setattr(v2_serial, "open", blocked_open)
    session.submit("connect")
    worker = Thread(target=session.step)
    worker.start()
    try:
        assert entered.wait(3)
        session.submit("close")
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert session.snapshot()["state"] == "CLOSING"
    with pytest.raises(PermissionError, match="closing"):
        session_action(session, "capture", "?SV")
    session.step()
    assert session.stop.is_set() and not session.snapshot()["connected"]
    assert v2_serial.closes == 1 and not v2_serial.writes


@pytest.mark.parametrize("initial,target,ceiling", [("V5", "V2", None), ("V2", "V6", 1.25)])
def test_gui_model_and_power_controls_follow_the_connected_controller(initial, target, ceiling):
    session = GuiSession(model=initial, allow_writes=True, power_limit_w=ceiling)
    app = create_app(session.monitor, session=session)
    settings = session.snapshot()["settings"] | {"model": target}
    session.submit("connect", settings)
    session.step()
    response = app.server.test_client().post(
        "/_dash-update-component", json=callback_request(app, "query-results")
    )
    assert response.status_code == 200, response.data
    data = response.json["response"]
    expected = ceiling if ceiling is not None else float(target[1:])
    assert data["header-model"]["children"] == f"Coherent Verdi {target}"
    assert data["panel-model"]["children"] == f"VERDI {target}"
    assert data["permission-label"]["children"] == f"Writes enabled · ≤ {expected:g} W"
    assert all(
        data[name]["max"] == expected
        for name in ("target-power", "panel-level-1-value", "panel-level-2-value")
    )
    assert data["panel-knob"] == {"aria-valuemax": expected, "data-max": expected}
    assert session.monitor.controller.last_transaction is None
    session.submit("close")
    session.step()


def test_reconnection_clears_readiness_and_rejects_actions_from_the_old_view(callback_payload):
    session = GuiSession(allow_writes=True)
    app = create_app(session.monitor, session=session)
    browser = app.server.test_client()
    session.submit("connect")
    session.step()
    session_action(session, "polling", True)
    session.step()
    response = browser.post("/_dash-update-component", json=callback_payload(app))
    first = response.json["response"]
    assert first["operator-ready"]["value"] == []
    old_generation = first["connection-generation"]["data"]
    session.submit("disconnect")
    session.step()
    session.submit("connect")
    session.step()
    session_action(session, "polling", True)
    session.step()
    pending = session.monitor.controls.snapshot()["actions"]
    response = browser.post(
        "/_dash-update-component",
        json=callback_request(
            app,
            "submission.children",
            trigger="apply-power",
            state={
                "browser-session": session.monitor.controls.new_client(),
                "target-power": 0.5,
                "operator-ready": ["ready"],
                "connection-generation": old_generation,
            },
        ),
    )
    assert response.status_code == 200
    assert "connection changed" in response.json["response"]["submission"]["children"]
    assert session.monitor.controls.snapshot()["actions"] == pending
    session.submit("close")
    session.step()


def test_acknowledged_hardware_link_changes_survive_gui_reconnect(peer, v2_replies, monkeypatch):
    session = GuiSession(port="FAKE-ONLY", model="V2", clear_reply="SYSTEM OK", allow_writes=True)
    app = create_app(session.monitor, session=session)
    old_settings = session.snapshot()["settings"]
    link = {"baudrate": 19200, "prompt": True}
    write = peer.write

    def respond(request):
        assert not peer.pending
        instruction = request[:-2]
        payload = b""
        if instruction == b"B=9600":
            link["baudrate"] = 9600
        elif instruction == b"PROMPT=1":
            link["prompt"] = False
        elif instruction == b"?B":
            payload = b"9600"
        else:
            payload = v2_replies[instruction]
        peer.responses.append(payload + b"\r\n" + (b"Verdi V-2>" if link["prompt"] else b""))
        return write(request)

    monkeypatch.setattr(peer, "write", respond)
    session.submit("connect")
    session.step()
    session_action(session, "polling", True)
    session.step()
    session_action(session, "polling", False)
    session.step()
    session_action(session, "baudrate", "9600")
    session.step()
    session_action(session, "prompt_off")
    session.step()
    assert all(
        item["state"] in ("applied", "verified", "acknowledged")
        for item in session.monitor.controls.snapshot()["actions"]
    )
    assert session.snapshot()["settings"]["baudrate"] == link["baudrate"]
    response = app.server.test_client().post(
        "/_dash-update-component",
        json=callback_request(app, "connection-state", state={"connection-settings": old_settings}),
    )
    assert response.status_code == 200, response.data
    data = response.json["response"]
    assert data["connection-baud"]["value"] == 9600
    session.submit("disconnect")
    session.step()
    session.submit("connect")
    session.step()
    assert peer.settings["baudrate"] == 9600
    session_action(session, "read", "?SV")
    session.step()
    result = session.monitor.controls.snapshot()["actions"][-1]
    assert result["state"] == "read" and result["result"] == "6.05"
    session.submit("close")
    session.step()


def test_worker_failure_is_reported_after_releasing_the_port(peer, monkeypatch):
    session = hardware_session()
    session.submit("connect")
    session.step()
    stopped, closed = Event(), Event()

    def fail_poll():
        raise RuntimeError("worker failed")

    monkeypatch.setattr(session.monitor, "poll_once", fail_poll)

    class Server:
        server_port = 8051

        def serve_forever(self, **kwargs):
            assert stopped.wait(3)

        def shutdown(self):
            assert peer.closes == 1
            stopped.set()

        def server_close(self):
            closed.set()

    monkeypatch.setattr("werkzeug.serving.make_server", lambda *args, **kwargs: Server())
    with pytest.raises(VerdiError, match="RuntimeError: worker failed"):
        run_gui(session, SimpleNamespace(server=object()), 8051)
    assert session.snapshot()["state"] == "ERROR"
    assert closed.is_set() and session.stop.is_set() and not peer.writes
