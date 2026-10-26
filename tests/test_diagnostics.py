"""Commissioning and failure evidence through an in-memory serial peer only."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor

import pytest
import serial

from coherent_verdi import DeviceError, VerdiController, VerdiError
from coherent_verdi.controller import transaction_evidence


class DiagnosticPeer:
    """A serial byte queue; writes append replies without discarding queued input."""

    def __init__(self):
        self.responses = deque()
        self.pending = bytearray()
        self.writes = []
        self.partial = False
        self.opens = self.closes = 0

    @property
    def in_waiting(self):
        return len(self.pending)

    def open(self):
        self.opens += 1

    def read_until(self, expected=b"\n", size=None):
        self._timeout = self.timeout
        return serial.SerialBase.read_until(self, expected, size)

    def close(self):
        self.closes += 1

    def write(self, request):
        self.writes.append(request)
        self.pending.extend(self.responses.popleft() if self.responses else b"")
        return len(request) - int(self.partial)

    def read(self, count):
        data = self.pending[:count]
        del self.pending[:count]
        return bytes(data)


@pytest.fixture
def peer(monkeypatch):
    fake = DiagnosticPeer()
    monkeypatch.setattr(serial, "Serial", lambda **settings: fake)
    return fake


def test_capture_preserves_exact_minimal_transaction(peer):
    reply = b"Verdi> ?SV FIRMWARE 7\r\n"
    peer.responses.append(reply)
    with VerdiController(
        "FAKE-DIAGNOSTICS", model="V6", baudrate=9600, timeout_s=0.25, prompt_enabled=False
    ) as laser:
        assert peer.writes == []
        assert laser.last_transaction is None
        captured = laser.capture("?SV")
        latest = laser.last_transaction
    assert captured == latest
    assert captured is not latest
    assert captured["instruction"] == b"?SV"
    assert captured["request"] == b"?SV\r\n"
    assert captured["response"] == reply
    assert captured["payload"] == b"FIRMWARE 7"
    assert set(captured) == {"instruction", "request", "response", "payload", "outcome", "error"}
    assert captured["outcome"] == "captured"
    assert captured["error"] is None
    assert peer.writes == [b"?SV\r\n"]
    assert peer.opens == peer.closes == 1


def test_normal_read_updates_latest_wire_evidence(peer):
    peer.responses.append(b"?P 0.125\r\n")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        assert laser.read_power_w() == 0.125
        record = laser.last_transaction
    assert record["request"] == b"?P\r\n"
    assert record["response"] == b"?P 0.125\r\n"
    assert record["payload"] == "0.125"
    assert record["outcome"] == "ok"


def test_standalone_prompt_is_preserved_in_json_evidence(peer):
    peer.pending.extend(b"Verdi V-2>")
    peer.responses.append(b"?SV6.05\r\n")
    with VerdiController("FAKE-ONLY", model="V2", prompt_enabled=False) as laser:
        record = laser.capture("?SV")
    encoded = transaction_evidence(record)
    assert "preamble_hex" not in encoded
    assert encoded["response_hex"] == b"Verdi V-2>?SV6.05\r\n".hex()


def test_capture_preserves_all_payload_byte_values_without_an_encoding(peer):
    payload = bytes(value for value in range(256) if value not in (10, 13))
    reply = b"?SV" + payload + b"\r\nVerdi V-2>"
    peer.responses.append(reply)
    with VerdiController("FAKE-ONLY", model="V2", prompt_enabled=True) as laser:
        record = laser.capture("?SV")
        assert record["payload"] == payload
        assert record["response"] == reply
        assert record["outcome"] == "captured" and not laser.failed
    encoded = transaction_evidence(record)
    assert encoded["payload"] is None
    assert bytes.fromhex(encoded["payload_hex"]) == payload
    assert record["payload"] == payload


@pytest.mark.parametrize("payload", [b"6.\x9605", b"\xd6\xff", b"ASCII"])
def test_text_query_retains_non_ascii_bytes_and_keeps_ascii_text_compatible(peer, payload):
    peer.responses.extend([b"?SV" + payload + b"\r\n", b"1.25\r\n"])
    expected = payload if not payload.isascii() else payload.decode("ascii")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        assert laser.get_value("?SV") == expected
        assert laser.last_transaction["payload"] == expected
        assert not laser.failed
        assert laser.read_power_w() == 1.25
    assert peer.writes == [b"?SV\r\n", b"?P\r\n"]


@pytest.mark.parametrize("query", ["?P", "?L", "?F", "?B"])
def test_binary_numeric_or_fault_payload_can_be_captured_but_is_not_a_valid_value(peer, query):
    peer.responses.extend([b"\x961\r\n", b"\x961\r\n"])
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        assert laser.capture(query)["payload"] == b"\x961"
        assert not laser.failed
        with pytest.raises(VerdiError, match="invalid .* payload"):
            laser.get_value(query)
        assert laser.failed
    assert peer.writes == [(query + "\r\n").encode("ascii")] * 2


@pytest.mark.parametrize("reply", [b"SYSTEM OK\r\n", b"0\r\n", b"\r\n"])
def test_fault_capture_does_not_establish_an_unverified_clear_convention(peer, reply):
    peer.responses.extend([reply, reply, b"1.000\r\n"])
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        captured = laser.capture("?F")
        assert captured["response"] == reply
        assert captured["payload"] == reply[:-2]
        assert captured["outcome"] == "captured"
        with pytest.raises(VerdiError) as caught:
            laser.read_faults()
        assert caught.value.transaction["instruction"] == b"?F"
        assert caught.value.transaction["response"] == reply
        assert caught.value.transaction["outcome"] == "failed"
        with pytest.raises(VerdiError, match="failed"):
            laser.read_power_w()
    assert peer.writes == [b"?F\r\n", b"?F\r\n"]


@pytest.mark.parametrize("query", ["?BAD", "?SV;L=1", "?SV\r\nL=1", "", None, [], 1])
def test_capture_allowlist_rejects_before_io_and_leaves_session_usable(peer, query):
    peer.responses.append(b"TEST\r\n")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        with pytest.raises(ValueError, match="unknown query"):
            laser.capture(query)
        assert not peer.writes
        assert laser.get_value("?SV") == "TEST"
    assert peer.writes == [b"?SV\r\n"]


def test_capture_requires_read_only_controller_before_io(peer):
    peer.responses.append(b"0.125\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=False) as laser:
        with pytest.raises(PermissionError, match="read-only"):
            laser.capture("?F")
        assert not peer.writes
        assert laser.last_transaction is None
        assert laser.read_power_w() == 0.125


@pytest.mark.parametrize(
    ("query", "reply", "payload"),
    [("?P", b"nan\r\n", "nan"), ("?L", b"9\r\n", "9"), ("?F", b"UNKNOWN\r\n", "UNKNOWN")],
)
def test_capture_preserves_typed_malformed_payload_without_claiming_validity(
    peer, query, reply, payload
):
    peer.responses.extend([reply, reply])
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        assert laser.capture(query)["payload"] == payload.encode("ascii")
        with pytest.raises(VerdiError):
            laser.get_value(query)
        with pytest.raises(VerdiError, match="failed"):
            laser.capture("?SV")


@pytest.mark.parametrize("reply", [b"missing-cr\n"])
def test_capture_still_enforces_framing_and_retires_malformed_sessions(peer, reply):
    peer.responses.append(reply)
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        with pytest.raises(VerdiError) as caught:
            laser.capture("?SV")
        assert caught.value.transaction["instruction"] == b"?SV"
        assert caught.value.transaction["request"] == b"?SV\r\n"
        assert caught.value.transaction["response"]
        record = laser.last_transaction
        with pytest.raises(VerdiError, match="failed"):
            laser.capture("?SV")
    assert record["outcome"] == "failed"
    assert len(peer.writes) == 1


@pytest.mark.parametrize("capture", [False, True])
def test_device_rejection_has_context_and_leaves_session_reusable(peer, capture):
    reply = b"Query Error: unsupported\r\n"
    peer.responses.extend([reply, b"TEST\r\n"])
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        action = laser.capture if capture else laser.get_value
        with pytest.raises(DeviceError) as caught:
            action("?F")
        error = caught.value
        assert error.transaction["instruction"] == b"?F"
        assert error.response == "Query Error: unsupported"
        assert error.transaction["request"] == b"?F\r\n"
        assert error.transaction["response"] == reply
        assert error.transaction["outcome"] == "rejected"
        record = laser.last_transaction
        assert laser.get_value("?SV") == "TEST"
    assert record["outcome"] == "rejected"
    assert record["response"] == reply
    assert "DeviceError" in record["error"]
    assert peer.writes == [b"?F\r\n", b"?SV\r\n"]


def test_command_rejection_is_distinct_from_unknown_write_outcome(peer):
    reply = b"Command Error: unsupported\r\n"
    peer.responses.extend([reply, b"0\r\n"])
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=False) as laser:
        with pytest.raises(DeviceError) as caught:
            laser.start()
        assert caught.value.transaction["request"] == b"L=1\r\n"
        assert caught.value.transaction["response"] == reply
        assert caught.value.transaction["outcome"] == "rejected"
        record = laser.last_transaction
        assert laser.read_laser_state() == 0
    assert record["outcome"] == "rejected"


@pytest.mark.parametrize("capture", [False, True])
@pytest.mark.parametrize("rejected", [b"?K", b"?K?SV"])
def test_query_error_for_different_instruction_invalidates_session(peer, capture, rejected):
    # Bench capture: the current query is echoed, but the rejected input contains
    # a previous query. A complete CR/LF frame does not establish alignment.
    reply = b"?SV Query Error:" + rejected + b"\r\n"
    peer.responses.append(reply)
    with VerdiController(
        "FAKE-ONLY", model="V2", allow_writes=not capture, prompt_enabled=False
    ) as laser:
        action = laser.capture if capture else laser.get_value
        with pytest.raises(VerdiError, match="device rejected a different query") as caught:
            action("?SV")
        assert not isinstance(caught.value, DeviceError)
        assert caught.value.transaction["request"] == b"?SV\r\n"
        assert caught.value.transaction["response"] == reply
        assert caught.value.transaction["outcome"] == "failed"
        assert laser.failed
        with pytest.raises(VerdiError, match="failed"):
            laser.get_value("?SV")
        if not capture:
            with pytest.raises(VerdiError, match="failed"):
                laser.start()
    assert peer.writes == [b"?SV\r\n"]


def test_query_error_naming_current_instruction_remains_a_device_rejection(peer):
    peer.responses.extend([b"?SV Query Error:?SV\r\n", b"?SV6.05\r\n"])
    with VerdiController("FAKE-ONLY", model="V2", prompt_enabled=False) as laser:
        with pytest.raises(DeviceError):
            laser.get_value("?SV")
        assert not laser.failed
        assert laser.get_value("?SV") == "6.05"
    assert peer.writes == [b"?SV\r\n", b"?SV\r\n"]


@pytest.mark.parametrize("command", [False, True])
def test_partial_timeout_retains_exact_bytes_and_outcome(peer, command):
    peer.responses.append(b"partial")
    with VerdiController("FAKE-ONLY", allow_writes=command, prompt_enabled=False) as laser:
        with pytest.raises(VerdiError, match="timed out") as caught:
            laser.start() if command else laser.get_value("?SV")
        error = caught.value
        assert error.transaction["instruction"] == (b"L=1" if command else b"?SV")
        assert error.transaction["request"] == (b"L=1\r\n" if command else b"?SV\r\n")
        assert error.transaction["response"] == b"partial"
        assert error.transaction["outcome"] == ("unknown" if command else "failed")
        record = laser.last_transaction
    assert record["response"] == b"partial"
    assert record["outcome"] == ("unknown" if command else "failed")


def test_partial_command_write_retains_unknown_outcome_and_no_replay(peer):
    peer.partial = True
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=False) as laser:
        with pytest.raises(VerdiError, match="partial write") as caught:
            laser.stop()
        error = caught.value
        assert error.transaction["instruction"] == b"L=0"
        assert error.transaction["request"] == b"L=0\r\n"
        assert error.transaction["response"] == b""
        assert error.transaction["outcome"] == "unknown"
        record = laser.last_transaction
        with pytest.raises(VerdiError, match="failed"):
            laser.stop()
    assert record["outcome"] == "unknown"
    assert peer.writes == [b"L=0\r\n"]


def test_capture_and_read_are_serialized_under_concurrent_callers(peer, monkeypatch):
    replies = {"?SV": b"TEST\r\n", "?P": b"0.125\r\n", "?L": b"1\r\n"}
    write = peer.write

    def respond(request):
        peer.responses.append(replies[request[:-2].decode()])
        return write(request)

    monkeypatch.setattr(peer, "write", respond)
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:

        def read_or_capture(index):
            query = ("?SV", "?P", "?L")[index % 3]
            if index % 2:
                record = laser.capture(query)
                assert record["instruction"] == query.encode("ascii")
                assert record["request"] == (query + "\r\n").encode()
                assert record["response"] == replies[query]
                return record["payload"]
            return laser.get_value(query)

        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(read_or_capture, range(40)))
    assert values == [
        (b"TEST", b"0.125", b"1")[index % 3] if index % 2 else ("TEST", 0.125, 1)[index % 3]
        for index in range(40)
    ]
    assert len(peer.writes) == 40


def test_acknowledged_command_keeps_its_wire_evidence(peer):
    peer.responses.append(b"\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=False) as laser:
        laser.stop()
        record = laser.last_transaction
    assert record["outcome"] == "acknowledged"
    assert record["request"] == b"L=0\r\n"
    assert record["response"] == b"\r\n"


def test_returned_records_cannot_mutate_latest_evidence(peer):
    peer.responses.append(b"TEST\r\n")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        captured = laser.capture("?SV")
        latest = laser.last_transaction
        captured.clear()
        latest["response"] = b"changed"
        assert laser.last_transaction["response"] == b"TEST\r\n"


def test_error_record_is_independent_of_latest_evidence(peer):
    peer.responses.append(b"partial")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        with pytest.raises(VerdiError) as caught:
            laser.get_value("?SV")
        caught.value.transaction.clear()
        assert laser.last_transaction["response"] == b"partial"
        latest = laser.last_transaction
        latest.clear()
        assert laser.last_transaction["response"] == b"partial"


def test_local_validation_preserves_previous_transaction(peer):
    peer.responses.append(b"TEST\r\n")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        laser.get_value("?SV")
        previous = laser.last_transaction
        with pytest.raises(ValueError):
            laser.capture("?BAD")
        with pytest.raises(PermissionError):
            laser.start()
        assert laser.last_transaction == previous
    assert peer.writes == [b"?SV\r\n"]


def test_disconnected_and_failed_refusals_preserve_previous_transaction(peer):
    peer.responses.append(b"partial")
    laser = VerdiController("FAKE-ONLY", prompt_enabled=False)
    with pytest.raises(VerdiError) as disconnected:
        laser.get_value("?SV")
    assert disconnected.value.transaction is None
    assert laser.last_transaction is None
    with laser:
        with pytest.raises(VerdiError) as caught:
            laser.get_value("?SV")
        failed = laser.last_transaction
        assert failed == caught.value.transaction
        with pytest.raises(VerdiError, match="failed") as refused:
            laser.capture("?SV")
        assert refused.value.transaction is None
        assert laser.last_transaction == failed
    with pytest.raises(VerdiError):
        laser.get_value("?SV")
    assert laser.last_transaction == failed
    assert peer.writes == [b"?SV\r\n"]
