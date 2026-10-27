"""Every test is hardware-free, including serial adapter tests."""

import json
from pathlib import Path

import pytest
import serial
import serial.tools.list_ports
from dash_helpers import callback_request
from fakes import SerialPeer

from coherent_verdi.controller import _PORT_OWNERS


@pytest.fixture(autouse=True)
def isolate_serial_ownership():
    """Each hardware-free test owns its own fake handles, including failed closes."""
    _PORT_OWNERS.clear()
    yield
    _PORT_OWNERS.clear()


@pytest.fixture(autouse=True)
def prohibit_physical_hardware(monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError("physical serial access/discovery prohibited in hardware-free tests")

    monkeypatch.setattr(serial, "Serial", prohibited)
    monkeypatch.setattr(serial, "serial_for_url", prohibited)
    monkeypatch.setattr(serial.tools.list_ports, "comports", prohibited)
    monkeypatch.setattr(serial.tools.list_ports, "grep", prohibited)


@pytest.fixture
def callback_payload():
    """Build the real Dash callback request shared by client integration tests."""

    return lambda app: callback_request(app, "sample.children")


@pytest.fixture
def peer(monkeypatch):
    """One fake port per test; no OS serial handle is constructed."""
    handle = SerialPeer()

    def construct(**settings):
        handle.settings = settings
        return handle

    monkeypatch.setattr(serial, "Serial", construct)
    return handle


@pytest.fixture(scope="session")
def v2_replies():
    """Payloads saved by the operator, independent of the simulator catalogue."""
    capture = json.loads((Path(__file__).parent / "data/verdi_v2_status.json").read_text())
    return {
        row["query"].encode("ascii"): bytes.fromhex(row["payload_hex"])
        for row in capture["responses"]
    }


@pytest.fixture
def v2_serial(peer, v2_replies, monkeypatch):
    """Replay recorded payloads with the terminal framing observed in lesson 01."""
    write = peer.write

    def respond(request):
        assert not peer.pending, "new instruction sent before the previous prompt was consumed"
        assert request.endswith(b"\r\n")
        peer.responses.append(v2_replies[request[:-2]] + b"\r\nVerdi V-2>")
        return write(request)

    monkeypatch.setattr(peer, "write", respond)
    return peer
