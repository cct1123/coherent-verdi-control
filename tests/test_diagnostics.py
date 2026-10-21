"""Commissioning and failure evidence through an in-memory serial peer only."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest
import serial

from coherent_verdi import DeviceError, VerdiController, VerdiError


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


def test_capture_preserves_exact_transaction_and_configuration(peer, monkeypatch):
    now = [10.0]
    monkeypatch.setattr("coherent_verdi.controller.monotonic", lambda: now[0])
    read = peer.read

    def timed_read(count):
        result = read(count)
        now[0] += len(result) * 0.001
        return result

    monkeypatch.setattr(peer, "read", timed_read)
    reply = b"Verdi> ?SV FIRMWARE 7\r\n"
    peer.responses.append(reply)
    before = datetime.now(UTC)
    with VerdiController("FAKE-DIAGNOSTICS", model="V6", baudrate=9600, timeout_s=0.25) as laser:
        assert peer.writes == []
        assert laser.last_transaction is None
        captured = laser.capture("?SV")
        latest = laser.last_transaction
    after = datetime.now(UTC)
    assert captured == latest
    assert captured is not latest
    assert captured["instruction"] == "?SV"
    assert captured["request"] == b"?SV\r\n"
    assert captured["response"] == reply
    assert captured["payload"] == "FIRMWARE 7"
    assert before <= datetime.fromisoformat(captured["timestamp_utc"]) <= after
    assert captured["duration_s"] == pytest.approx(len(reply) * 0.001)
    assert captured["port"] == "FAKE-DIAGNOSTICS"
    assert captured["model"] == "V6"
    assert captured["baudrate"] == 9600
    assert captured["timeout_s"] == 0.25
    assert captured["simulated"] is False
    assert captured["write_attempted"] is True
    assert captured["pending_bytes"] == 0
    assert captured["outcome"] == "captured"
    assert captured["error"] is None
    assert peer.writes == [b"?SV\r\n"]
    assert peer.opens == peer.closes == 1


def test_normal_read_updates_latest_wire_evidence(peer):
    peer.responses.append(b"?P 0.125\r\n")
    with VerdiController("FAKE-ONLY") as laser:
        assert laser.read_power_w() == 0.125
        record = laser.last_transaction
    assert record["request"] == b"?P\r\n"
    assert record["response"] == b"?P 0.125\r\n"
    assert record["payload"] == "0.125"
    assert record["outcome"] == "ok"


@pytest.mark.parametrize("reply", [b"SYSTEM OK\r\n", b"0\r\n", b"\r\n"])
def test_fault_capture_does_not_establish_an_unverified_clear_convention(peer, reply):
    peer.responses.extend([reply, reply, b"1.000\r\n"])
    with VerdiController("FAKE-ONLY") as laser:
        captured = laser.capture("?F")
        assert captured["response"] == reply
        assert captured["payload"] == reply[:-2].decode()
        assert captured["outcome"] == "captured"
        with pytest.raises(VerdiError) as caught:
            laser.read_faults()
        assert caught.value.transaction["instruction"] == "?F"
        assert caught.value.transaction["response"] == reply
        assert caught.value.transaction["outcome"] == "failed"
        with pytest.raises(VerdiError, match="failed"):
            laser.read_power_w()
    assert peer.writes == [b"?F\r\n", b"?F\r\n"]


@pytest.mark.parametrize("query", ["?BAD", "?SV;L=1", "?SV\r\nL=1", "", None, [], 1])
def test_capture_allowlist_rejects_before_io_and_leaves_session_usable(peer, query):
    peer.responses.append(b"TEST\r\n")
    with VerdiController("FAKE-ONLY") as laser:
        with pytest.raises(ValueError, match="unknown query"):
            laser.capture(query)
        assert not peer.writes
        assert laser.read("?SV") == "TEST"
    assert peer.writes == [b"?SV\r\n"]


def test_capture_requires_read_only_controller_before_io(peer):
    peer.responses.append(b"0.125\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
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
    with VerdiController("FAKE-ONLY") as laser:
        assert laser.capture(query)["payload"] == payload
        with pytest.raises(VerdiError):
            laser.read(query)
        with pytest.raises(VerdiError, match="failed"):
            laser.capture("?SV")


@pytest.mark.parametrize(
    "reply", [b"\xff\r\n", b"bad\tvalue\r\n", b"missing-cr\n", b"one\r\ntwo\r\n"]
)
def test_capture_still_enforces_framing_and_retires_malformed_sessions(peer, reply):
    peer.responses.append(reply)
    with VerdiController("FAKE-ONLY") as laser:
        with pytest.raises(VerdiError) as caught:
            laser.capture("?SV")
        assert caught.value.transaction["instruction"] == "?SV"
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
    with VerdiController("FAKE-ONLY") as laser:
        action = laser.capture if capture else laser.read
        with pytest.raises(DeviceError) as caught:
            action("?F")
        error = caught.value
        assert error.transaction["instruction"] == "?F"
        assert error.response == "Query Error: unsupported"
        assert error.transaction["request"] == b"?F\r\n"
        assert error.transaction["response"] == reply
        assert error.transaction["duration_s"] >= 0
        assert error.transaction["outcome"] == "rejected"
        record = laser.last_transaction
        assert laser.read("?SV") == "TEST"
    assert record["outcome"] == "rejected"
    assert record["response"] == reply
    assert "DeviceError" in record["error"]
    assert peer.writes == [b"?F\r\n", b"?SV\r\n"]


def test_command_rejection_is_distinct_from_unknown_write_outcome(peer):
    reply = b"Command Error: unsupported\r\n"
    peer.responses.extend([reply, b"0\r\n"])
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises(DeviceError) as caught:
            laser.start()
        assert caught.value.transaction["request"] == b"L=1\r\n"
        assert caught.value.transaction["response"] == reply
        assert caught.value.transaction["outcome"] == "rejected"
        record = laser.last_transaction
        assert laser.read_laser_state() == 0
    assert record["outcome"] == "rejected"


@pytest.mark.parametrize("command", [False, True])
def test_partial_timeout_retains_exact_bytes_and_outcome(peer, command):
    peer.responses.append(b"partial")
    with VerdiController("FAKE-ONLY", allow_writes=command) as laser:
        with pytest.raises(VerdiError, match="timed out") as caught:
            laser.start() if command else laser.read("?SV")
        error = caught.value
        assert error.transaction["instruction"] == ("L=1" if command else "?SV")
        assert error.transaction["request"] == (b"L=1\r\n" if command else b"?SV\r\n")
        assert error.transaction["response"] == b"partial"
        assert error.transaction["duration_s"] >= 0
        assert error.transaction["outcome"] == ("unknown" if command else "failed")
        record = laser.last_transaction
    assert record["response"] == b"partial"
    assert record["outcome"] == ("unknown" if command else "failed")


def test_partial_command_write_retains_unknown_outcome_and_no_replay(peer):
    peer.partial = True
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises(VerdiError, match="partial write") as caught:
            laser.stop()
        error = caught.value
        assert error.transaction["instruction"] == "L=0"
        assert error.transaction["request"] == b"L=0\r\n"
        assert error.transaction["response"] == b""
        assert error.transaction["duration_s"] >= 0
        assert error.transaction["outcome"] == "unknown"
        record = laser.last_transaction
        with pytest.raises(VerdiError, match="failed"):
            laser.stop()
    assert record["write_attempted"] is True
    assert record["outcome"] == "unknown"
    assert peer.writes == [b"L=0\r\n"]


def test_late_byte_is_failure_evidence_even_though_reply_missed_deadline(peer, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("coherent_verdi.controller.monotonic", lambda: now[0])
    read = peer.read

    def late_terminator(count):
        data = read(count)
        if data.endswith(b"\r\n"):
            now[0] = 0.02
        return data

    monkeypatch.setattr(peer, "read", late_terminator)
    peer.responses.append(b"\r\n")
    with VerdiController("FAKE-ONLY", timeout_s=0.01, allow_writes=True) as laser:
        with pytest.raises(VerdiError, match="timed out") as caught:
            laser.stop()
        record = laser.last_transaction
    assert caught.value.transaction["response"] == b"\r\n"
    assert caught.value.transaction["outcome"] == "unknown"
    assert record["response"] == b"\r\n"
    assert record["outcome"] == "unknown"


def test_pretransmit_buffered_input_records_command_as_not_sent(peer):
    peer.pending.extend(b"late\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises(VerdiError, match="buffered input") as caught:
            laser.start()
        assert caught.value.transaction["instruction"] == "L=1"
        assert caught.value.transaction["request"] == b"L=1\r\n"
        assert caught.value.transaction["response"] == b""
        assert caught.value.transaction["outcome"] == "not_sent"
        record = laser.last_transaction
    assert record["write_attempted"] is False
    assert record["pending_bytes"] == len(b"late\r\n")
    assert record["outcome"] == "not_sent"
    assert peer.pending == b"late\r\n"  # Evidence is not silently purged.
    assert peer.writes == []


def test_capture_and_read_are_serialized_under_concurrent_callers(peer, monkeypatch):
    replies = {"?SV": b"TEST\r\n", "?P": b"0.125\r\n", "?L": b"1\r\n"}
    write = peer.write

    def respond(request):
        peer.responses.append(replies[request[:-2].decode()])
        return write(request)

    monkeypatch.setattr(peer, "write", respond)
    with VerdiController("FAKE-ONLY") as laser:

        def read_or_capture(index):
            query = ("?SV", "?P", "?L")[index % 3]
            if index % 2:
                record = laser.capture(query)
                assert record["instruction"] == query
                assert record["request"] == (query + "\r\n").encode()
                assert record["response"] == replies[query]
                return record["payload"]
            return laser.read(query)

        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(read_or_capture, range(40)))
    assert values == [
        ("TEST", "0.125", "1")[index % 3] if index % 2 else ("TEST", 0.125, 1)[index % 3]
        for index in range(40)
    ]
    assert len(peer.writes) == 40


def test_acknowledged_command_keeps_its_wire_evidence(peer):
    peer.responses.append(b"\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        laser.stop()
        record = laser.last_transaction
    assert record["outcome"] == "acknowledged"
    assert record["request"] == b"L=0\r\n"
    assert record["response"] == b"\r\n"


def test_returned_records_cannot_mutate_latest_evidence(peer):
    peer.responses.append(b"TEST\r\n")
    with VerdiController("FAKE-ONLY") as laser:
        captured = laser.capture("?SV")
        latest = laser.last_transaction
        captured.clear()
        latest["response"] = b"changed"
        assert laser.last_transaction["response"] == b"TEST\r\n"


def test_error_record_is_independent_of_latest_evidence(peer):
    peer.responses.append(b"partial")
    with VerdiController("FAKE-ONLY") as laser:
        with pytest.raises(VerdiError) as caught:
            laser.read("?SV")
        caught.value.transaction.clear()
        assert laser.last_transaction["response"] == b"partial"
        latest = laser.last_transaction
        latest.clear()
        assert laser.last_transaction["response"] == b"partial"


def test_local_validation_preserves_previous_transaction(peer):
    peer.responses.append(b"TEST\r\n")
    with VerdiController("FAKE-ONLY") as laser:
        laser.read("?SV")
        previous = laser.last_transaction
        with pytest.raises(ValueError):
            laser.capture("?BAD")
        with pytest.raises(PermissionError):
            laser.start()
        assert laser.last_transaction == previous
    assert peer.writes == [b"?SV\r\n"]


def test_disconnected_and_failed_refusals_preserve_previous_transaction(peer):
    peer.responses.append(b"partial")
    laser = VerdiController("FAKE-ONLY")
    with pytest.raises(VerdiError) as disconnected:
        laser.read("?SV")
    assert disconnected.value.transaction is None
    assert laser.last_transaction is None
    with laser:
        with pytest.raises(VerdiError) as caught:
            laser.read("?SV")
        failed = laser.last_transaction
        assert failed == caught.value.transaction
        with pytest.raises(VerdiError, match="failed") as refused:
            laser.capture("?SV")
        assert refused.value.transaction is None
        assert laser.last_transaction == failed
    with pytest.raises(VerdiError):
        laser.read("?SV")
    assert laser.last_transaction == failed
    assert peer.writes == [b"?SV\r\n"]
