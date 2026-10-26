"""Byte-only transactions, including prompts that arrive after an empty RX queue."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import serial
from test_serial import FakeSerial

from coherent_verdi import VerdiController, VerdiError


@pytest.fixture
def peer(monkeypatch):
    handle = FakeSerial()
    monkeypatch.setattr(serial, "Serial", lambda **settings: handle)
    return handle


def test_raw_read_preserves_echo_prompt_and_non_ascii_bytes(peer, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("raw communication must not use text conversion")

    monkeypatch.setattr("coherent_verdi.controller.encode_instruction", forbidden)
    monkeypatch.setattr("coherent_verdi.controller.decode_response", forbidden)
    wire = b"?SV\x16\xe1\r\nVerdi V-2>"
    peer.responses.append(wire)
    with VerdiController("FAKE-ONLY", model="V2") as laser:
        assert laser.get(b"?SV") == b"\x16\xe1"
        assert laser.last_transaction["response"] == wire
    assert peer.writes == [b"?SV\r\n"]


def test_delayed_prompt_blocks_next_query_even_when_nothing_is_buffered(peer, monkeypatch):
    waiting, release, second_started = Event(), Event(), Event()
    original_read = peer.read
    prompt = b"Verdi V-2>"
    peer.responses.extend([b"6.05\r\n", b"0\r\n" + prompt])

    def read(size):
        if not peer.pending:
            waiting.set()
            assert release.wait(2), "test did not release delayed prompt"
            assert peer.writes == [b"?SV\r\n"]
            peer.pending.extend(prompt)
        return original_read(size)

    monkeypatch.setattr(peer, "read", read)
    with VerdiController("FAKE-ONLY", model="V2", timeout_s=5) as laser:

        def second_query():
            second_started.set()
            return laser.get(b"?L")

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(laser.get, b"?SV")
            try:
                assert waiting.wait(2)
                second = pool.submit(second_query)
                assert second_started.wait(2)
                assert not first.done() and not second.done()
                assert peer.writes == [b"?SV\r\n"]
            finally:
                release.set()
            assert first.result() == b"6.05"
            assert second.result() == b"0"
    assert peer.writes == [b"?SV\r\n", b"?L\r\n"]


@pytest.mark.parametrize("tail", [b"", b"Verdi V-2"])
def test_missing_or_partial_prompt_stops_session_without_next_transmission(peer, tail):
    peer.responses.append(b"6.05\r\n" + tail)
    with VerdiController("FAKE-ONLY", model="V2") as laser:
        with pytest.raises(VerdiError, match="prompt timed out") as caught:
            laser.get(b"?SV")
        assert caught.value.transaction["response"] == b"6.05\r\n" + tail
        assert laser.failed
        with pytest.raises(VerdiError, match="failed"):
            laser.get(b"?P")
    assert peer.writes == [b"?SV\r\n"]


@pytest.mark.parametrize("method", ["command", "set"])
def test_raw_write_consumes_ack_and_prompt_and_preserves_instruction(peer, method):
    wire = b"P=0.25000\r\nVerdi V-2>"
    peer.responses.append(wire)
    with VerdiController("FAKE-ONLY", model="V2", allow_writes=True, power_limit_w=0.5) as laser:
        assert getattr(laser, method)(b"P=0.25000") == wire
        assert not peer.pending
    assert peer.writes == [b"P=0.25000\r\n"]


def test_raw_command_permissions_and_ceiling_apply_before_transmission(peer):
    with VerdiController("FAKE-ONLY", power_limit_w=0.5) as laser:
        with pytest.raises(PermissionError):
            laser.command(b"L=1")
        with pytest.raises(ValueError):
            laser.command(b"P=0.6")
    assert not peer.writes


@pytest.mark.parametrize(
    "method,instruction",
    [
        ("get", "?SV"),
        ("command", "L=0"),
        ("set", "S=0"),
    ],
)
def test_raw_api_rejects_strings_without_encoding(peer, method, instruction):
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises(TypeError, match="bytes"):
            getattr(laser, method)(instruction)
    assert not peer.writes


def test_raw_query_errors_are_returned_unchanged(peer):
    wire = b"Query Error:?UNKNOWN\r\nVerdi V-2>"
    peer.responses.append(wire)
    with VerdiController("FAKE-ONLY", model="V2") as laser:
        assert laser.get(b"?UNKNOWN") == b"Query Error:?UNKNOWN"
        assert not laser.failed


def test_explicit_prompt_disabled_mode_completes_at_crlf(peer):
    peer.responses.append(b"6.05\r\n")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        assert laser.get(b"?SV") == b"6.05"


def test_raw_prompt_mode_changes_are_tracked(peer):
    peer.responses.extend([b"\r\n", b"6.05\r\n", b"\r\nVerdi V-2>", b"6.05\r\nVerdi V-2>"])
    with VerdiController("FAKE-ONLY", model="V2", allow_writes=True) as laser:
        assert laser.command(b"PROMPT=1") == b"\r\n"
        assert laser.get(b"?SV") == b"6.05"
        assert laser.command(b"PROMPT=0") == b"\r\nVerdi V-2>"
        assert laser.get(b"?SV") == b"6.05"


def test_read_uses_native_read_until_in_order_with_fixed_timeout(peer, monkeypatch):
    calls = []
    original = peer.read_until
    peer.responses.append(b"6.05\r\nVerdi V-2>")

    def read_until(expected, size=None):
        calls.append((expected, size, peer.timeout))
        return original(expected, size)

    monkeypatch.setattr(peer, "read_until", read_until)
    with VerdiController("FAKE-ONLY", model="V2", timeout_s=2) as laser:
        assert laser.get(b"?SV") == b"6.05"
        assert not hasattr(laser, "_exchange")
    assert calls == [(b"\r\n", 4096, 2), (b">", 4090, 2)]
    assert peer.writes == [b"?SV\r\n"]


def test_set_delegates_to_command(peer, monkeypatch):
    calls = []
    with VerdiController("FAKE-ONLY") as laser:

        def read(instruction):
            calls.append(instruction)
            return b"\r\nVerdi>"

        monkeypatch.setattr(laser, "command", read)
        assert laser.set(b"S=0") == b"\r\nVerdi>"
    assert calls == [b"S=0"]
    assert peer.writes == []


@pytest.mark.parametrize("method,instruction", [("get", b"S=0"), ("set", b"?S")])
def test_explicit_direction_is_validated_before_transmission(peer, method, instruction):
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises(ValueError):
            getattr(laser, method)(instruction)
    assert peer.writes == []


def test_removed_ambiguous_and_text_command_methods(peer):
    with VerdiController("FAKE-ONLY") as laser:
        for method in ("read", "write", "command_text", "_command"):
            assert not hasattr(laser, method)


@pytest.mark.parametrize("method", ["command", "set"])
def test_single_command_path_enforces_power_limit(peer, method):
    with VerdiController("FAKE-ONLY", allow_writes=True, power_limit_w=0.5) as laser:
        with pytest.raises(ValueError):
            getattr(laser, method)(b"P=0.6")
    assert peer.writes == []


def test_get_delegates_to_single_command_implementation(peer, monkeypatch):
    calls = []
    with VerdiController("FAKE-ONLY") as laser:

        def command(instruction):
            calls.append(instruction)
            return b"0\r\nVerdi>"

        monkeypatch.setattr(laser, "command", command)
        assert laser.get(b"?S") == b"0"
    assert calls == [b"?S"]
    assert peer.writes == []


@pytest.mark.parametrize("echo", [False, True])
@pytest.mark.parametrize("prefix", [b"", b"Verdi V-2> "])
@pytest.mark.parametrize("payload", [b"6.05", b"0.080.0", b"\x16\xe1", b"Query Error:?SV"])
def test_get_formats_only_framing_and_keeps_wire_evidence(peer, echo, prefix, payload):
    wire = prefix + (b"?SV " if echo else b"") + payload + b"\r\nVerdi V-2>"
    peer.responses.append(wire)
    with VerdiController("FAKE-ONLY", model="V2") as laser:
        assert laser.get(b"?SV") == payload
        assert laser.last_transaction["response"] == wire
        assert laser.last_transaction["payload"] == payload
    assert peer.writes == [b"?SV\r\n"]
