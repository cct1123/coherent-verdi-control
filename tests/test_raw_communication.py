"""Byte communication following the successful V2 notebook runs."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from coherent_verdi import DeviceError, VerdiController, VerdiError


def test_byte_api_names_are_distinct_from_typed_helpers():
    from coherent_verdi import SimulatedVerdi

    for cls in (VerdiController, SimulatedVerdi):
        assert callable(cls.read) and callable(cls.write)
        assert not hasattr(cls, "get") and not hasattr(cls, "set")
        assert not hasattr(cls, "_request")
        for method in ("get_value", "set_value", "get_status", "get_power_w", "set_power_w"):
            assert callable(getattr(cls, method))


def test_read_recorded_status_in_sequence(v2_serial, v2_replies):
    with VerdiController("FAKE-ONLY", model="V2", baudrate=19200) as laser:
        for query, payload in v2_replies.items():
            assert laser.read(query) == payload
            assert laser.last_transaction == {
                "instruction": query,
                "request": query + b"\r\n",
                "response": payload + b"\r\nVerdi V-2>",
                "payload": payload,
                "outcome": "received",
                "error": None,
            }
    assert v2_serial.writes == [query + b"\r\n" for query in v2_replies]
    assert not v2_serial.pending


@pytest.mark.parametrize(
    "wire,payload",
    [
        (b"?SV6.05\r\nVerdi V-2>", b"6.05"),
        (b"Verdi V-2> ?SV 6.05\r\nVerdi V-2>", b"6.05"),
        (b"?SV\x16\xe1\r\nVerdi V-2>", b"\x16\xe1"),
        (b" Query Error:?SV\r\nVerdi V-2>", b" Query Error:?SV"),
    ],
)
def test_read_removes_framing_without_interpreting_payload(peer, wire, payload):
    peer.responses.append(wire)
    with VerdiController("FAKE-ONLY", model="V2") as laser:
        assert laser.read(b"?SV") == payload
        assert laser.last_transaction["response"] == wire
        assert not laser.failed


def test_next_query_waits_for_the_prompt(peer, monkeypatch):
    waiting, release, second_started = Event(), Event(), Event()
    read = peer.read
    peer.responses.extend([b"6.05\r\n", b"0\r\nVerdi V-2>"])

    def delayed_read(size):
        if not peer.pending:
            waiting.set()
            assert release.wait(2)
            peer.pending.extend(b"Verdi V-2>")
        return read(size)

    monkeypatch.setattr(peer, "read", delayed_read)
    with VerdiController("FAKE-ONLY", model="V2", timeout_s=5) as laser:

        def get_state():
            second_started.set()
            return laser.read(b"?L")

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(laser.read, b"?SV")
            try:
                assert waiting.wait(2)
                second = pool.submit(get_state)
                assert second_started.wait(2)
                assert not first.done() and not second.done()
                assert peer.writes == [b"?SV\r\n"]
            finally:
                release.set()
            assert first.result() == b"6.05"
            assert second.result() == b"0"
    assert peer.writes == [b"?SV\r\n", b"?L\r\n"]


@pytest.mark.parametrize("reply", [b"partial", b"6.05\r\n", b"6.05\r\nVerdi V-2"])
def test_incomplete_reply_stops_without_retry(peer, reply):
    peer.responses.append(reply)
    with VerdiController("FAKE-ONLY", model="V2") as laser:
        with pytest.raises(VerdiError, match="timed out") as caught:
            laser.read(b"?SV")
        assert caught.value.transaction["response"] == reply
        with pytest.raises(VerdiError, match="failed"):
            laser.read(b"?P")
    assert peer.writes == [b"?SV\r\n"]


def test_write_consumes_its_acknowledgment_before_readback(peer):
    # Synthetic setting acknowledgment: the reference runs were read-only.
    peer.responses.extend([b"\r\nVerdi V-2>", b"0.0100\r\nVerdi V-2>"])
    with VerdiController("FAKE-ONLY", model="V2", allow_writes=True) as laser:
        assert laser.write(b"P=0.0100") == b"\r\nVerdi V-2>"
        assert not peer.pending
        assert laser.read(b"?SP") == b"0.0100"
    assert peer.writes == [b"P=0.0100\r\n", b"?SP\r\n"]


@pytest.mark.parametrize(
    "method,instruction,error",
    [
        ("read", "?SV", TypeError),
        ("write", "L=0", TypeError),
        ("command", "?SV", TypeError),
        ("read", b"S=0", ValueError),
        ("write", b"?S", ValueError),
        ("write", b"L=1", PermissionError),
        ("write", b"P=0.6", ValueError),
        ("command", b"P=0.6", ValueError),
    ],
)
def test_invalid_or_disabled_requests_do_not_transmit(peer, method, instruction, error):
    with VerdiController(
        "FAKE-ONLY", allow_writes=error is not PermissionError, power_limit_w=0.5
    ) as laser:
        with pytest.raises(error):
            getattr(laser, method)(instruction)
    assert peer.writes == []


def test_explicitly_disabled_prompt_and_mode_changes(peer):
    peer.responses.extend([b"\r\n", b"6.05\r\n", b"\r\nVerdi V-2>"])
    with VerdiController("FAKE-ONLY", model="V2", allow_writes=True) as laser:
        assert laser.write(b"PROMPT=1") == b"\r\n"
        assert laser.read(b"?SV") == b"6.05"
        assert laser.write(b"PROMPT=0") == b"\r\nVerdi V-2>"


@pytest.mark.parametrize("initial_prompt", [False, True])
@pytest.mark.parametrize("typed", [False, True])
@pytest.mark.parametrize("echo", [False, True])
def test_rejected_prompt_change_keeps_previous_framing(peer, initial_prompt, typed, echo):
    instruction = b"PROMPT=1" if initial_prompt else b"PROMPT=0"
    prompt = b"Verdi>" if initial_prompt else b""
    rejected = (
        (instruction + b" " if echo else b"") + b"Command Error: " + instruction + b"\r\n" + prompt
    )
    peer.responses.extend([rejected, b"6.05\r\n" + prompt])
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=initial_prompt) as laser:
        if typed:
            with pytest.raises(DeviceError):
                laser.set_prompt(enabled=not initial_prompt)
            assert laser.last_transaction["outcome"] == "rejected"
        else:
            assert laser.write(instruction) == rejected
        assert laser._prompt_enabled is initial_prompt
        assert not peer.pending
        assert not laser.failed
        assert laser.get_value("?SV") == "6.05"
        assert not peer.pending
    assert peer.writes == [instruction + b"\r\n", b"?SV\r\n"]


@pytest.mark.parametrize("write", [False, True])
def test_typed_interpretation_stays_with_its_exchange_under_lock(peer, monkeypatch, write):
    peer.responses.extend([b"\r\n" if write else b"0.125\r\n", b"6.05\r\n"])
    entered, release, second_started = Event(), Event(), Event()
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=False) as laser:
        interpret = laser._interpret_reply

        def blocked(*args, **kwargs):
            entered.set()
            assert release.wait(3)
            return interpret(*args, **kwargs)

        def another_query():
            second_started.set()
            return laser.read(b"?SV")

        monkeypatch.setattr(laser, "_interpret_reply", blocked)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = (
                pool.submit(laser.set_power_w, 0.25) if write else pool.submit(laser.get_power_w)
            )
            try:
                assert entered.wait(3)
                second = pool.submit(another_query)
                assert second_started.wait(3)
                assert len(peer.writes) == 1
                assert not second.done()
            finally:
                release.set()
            assert first.result() == (None if write else 0.125)
            assert second.result() == b"6.05"


@pytest.mark.parametrize("capture", [False, True])
def test_typed_queries_and_capture_delegate_to_public_read(peer, monkeypatch, capture):
    peer.responses.append(b"6.05\r\n")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        sent = []
        raw_read = laser.read

        def tracked_read(query):
            sent.append(query)
            return raw_read(query)

        monkeypatch.setattr(laser, "read", tracked_read)
        if capture:
            assert laser.get_capture("PRINT SOFTWARE")["payload"] == b"6.05"
        else:
            assert laser.get_value("PRINT SOFTWARE") == "6.05"
        assert sent == [b"?SV"]
        assert peer.writes == [b"?SV\r\n"]
