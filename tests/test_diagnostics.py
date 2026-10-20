"""Transaction evidence and commissioning through an in-memory serial peer only."""

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


def test_capture_and_trace_preserve_exact_transaction_and_configuration(peer, monkeypatch):
    now = [10.0]
    monkeypatch.setattr("coherent_verdi.controller.monotonic", lambda: now[0])
    read = peer.read

    def timed_read(count):
        now[0] += 0.001
        return read(count)

    monkeypatch.setattr(peer, "read", timed_read)
    reply = b"Verdi> ?SV FIRMWARE 7\r\n"
    peer.responses.append(reply)
    records = []
    before = datetime.now(UTC)
    with VerdiController(
        "FAKE-DIAGNOSTICS", model="V6", baudrate=9600, timeout_s=0.25, trace=records.append
    ) as laser:
        assert peer.writes == []
        captured = laser.capture("?SV")
    after = datetime.now(UTC)
    assert len(records) == 1
    assert captured == records[0]
    assert captured is not records[0]
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


def test_read_trace_contains_wire_evidence_and_parsed_payload(peer):
    records = []
    peer.responses.append(b"?P 0.125\r\n")
    with VerdiController("FAKE-ONLY", trace=records.append) as laser:
        assert laser.read_power_w() == 0.125
    assert records[0]["request"] == b"?P\r\n"
    assert records[0]["response"] == b"?P 0.125\r\n"
    assert records[0]["payload"] == "0.125"
    assert records[0]["outcome"] == "ok"


@pytest.mark.parametrize("reply", [b"SYSTEM OK\r\n", b"0\r\n", b"\r\n"])
def test_fault_capture_does_not_establish_an_unverified_clear_convention(peer, reply):
    peer.responses.extend([reply, reply, b"1.000\r\n"])
    records = []
    with VerdiController("FAKE-ONLY", trace=records.append) as laser:
        captured = laser.capture("?F")
        assert captured["response"] == reply
        assert captured["payload"] == reply[:-2].decode()
        assert captured["outcome"] == "captured"
        with pytest.raises(VerdiError) as caught:
            laser.read_faults()
        assert caught.value.instruction == "?F"
        assert caught.value.raw_response == reply
        assert caught.value.write_outcome is None
        with pytest.raises(VerdiError, match="failed"):
            laser.read_power_w()
    assert [record["outcome"] for record in records] == ["captured", "failed"]
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
    records = []
    with VerdiController("FAKE-ONLY", allow_writes=True, trace=records.append) as laser:
        with pytest.raises(PermissionError, match="read-only"):
            laser.capture("?F")
        assert not peer.writes and not records
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
    records = []
    with VerdiController("FAKE-ONLY", trace=records.append) as laser:
        with pytest.raises(VerdiError) as caught:
            laser.capture("?SV")
        assert caught.value.instruction == "?SV"
        assert caught.value.request == b"?SV\r\n"
        assert caught.value.raw_response
        with pytest.raises(VerdiError, match="failed"):
            laser.capture("?SV")
    assert records[0]["outcome"] == "failed"
    assert len(peer.writes) == 1


@pytest.mark.parametrize("capture", [False, True])
def test_device_rejection_has_context_and_leaves_session_reusable(peer, capture):
    reply = b"Query Error: unsupported\r\n"
    peer.responses.extend([reply, b"TEST\r\n"])
    records = []
    with VerdiController("FAKE-ONLY", trace=records.append) as laser:
        action = laser.capture if capture else laser.read
        with pytest.raises(DeviceError) as caught:
            action("?F")
        error = caught.value
        assert error.instruction == "?F"
        assert error.response == "Query Error: unsupported"
        assert error.request == b"?F\r\n"
        assert error.raw_response == reply
        assert error.duration_s >= 0
        assert error.write_outcome is None
        assert laser.read("?SV") == "TEST"
    assert records[0]["outcome"] == "rejected"
    assert records[0]["response"] == reply
    assert "DeviceError" in records[0]["error"]
    assert peer.writes == [b"?F\r\n", b"?SV\r\n"]


def test_command_rejection_is_distinct_from_unknown_write_outcome(peer):
    reply = b"Command Error: unsupported\r\n"
    peer.responses.extend([reply, b"0\r\n"])
    records = []
    with VerdiController("FAKE-ONLY", allow_writes=True, trace=records.append) as laser:
        with pytest.raises(DeviceError) as caught:
            laser.start()
        assert caught.value.request == b"L=1\r\n"
        assert caught.value.raw_response == reply
        assert caught.value.write_outcome == "rejected"
        assert laser.read_laser_state() == 0
    assert records[0]["outcome"] == "rejected"


@pytest.mark.parametrize("command", [False, True])
def test_partial_timeout_retains_exact_bytes_and_outcome(peer, command):
    records = []
    peer.responses.append(b"partial")
    with VerdiController("FAKE-ONLY", allow_writes=command, trace=records.append) as laser:
        with pytest.raises(VerdiError, match="timed out") as caught:
            laser.start() if command else laser.read("?SV")
        error = caught.value
        assert error.instruction == ("L=1" if command else "?SV")
        assert error.request == (b"L=1\r\n" if command else b"?SV\r\n")
        assert error.raw_response == b"partial"
        assert error.duration_s >= 0
        assert error.write_outcome == ("unknown" if command else None)
    assert records[0]["response"] == b"partial"
    assert records[0]["outcome"] == ("unknown" if command else "failed")


def test_partial_command_write_retains_unknown_outcome_and_no_replay(peer):
    peer.partial = True
    records = []
    with VerdiController("FAKE-ONLY", allow_writes=True, trace=records.append) as laser:
        with pytest.raises(VerdiError, match="partial write") as caught:
            laser.stop()
        error = caught.value
        assert error.instruction == "L=0"
        assert error.request == b"L=0\r\n"
        assert error.raw_response == b""
        assert error.duration_s >= 0
        assert error.write_outcome == "unknown"
        with pytest.raises(VerdiError, match="failed"):
            laser.stop()
    assert records[0]["write_attempted"] is True
    assert records[0]["outcome"] == "unknown"
    assert peer.writes == [b"L=0\r\n"]


def test_late_byte_is_failure_evidence_even_though_reply_missed_deadline(peer, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("coherent_verdi.controller.monotonic", lambda: now[0])
    read = peer.read

    def late_terminator(count):
        data = read(count)
        if data == b"\n":
            now[0] = 0.02
        return data

    monkeypatch.setattr(peer, "read", late_terminator)
    peer.responses.append(b"\r\n")
    records = []
    with VerdiController(
        "FAKE-ONLY", timeout_s=0.01, allow_writes=True, trace=records.append
    ) as laser:
        with pytest.raises(VerdiError, match="timed out") as caught:
            laser.stop()
    assert caught.value.raw_response == b"\r\n"
    assert caught.value.write_outcome == "unknown"
    assert records[0]["response"] == b"\r\n"
    assert records[0]["outcome"] == "unknown"


def test_pretransmit_buffered_input_records_command_as_not_sent(peer):
    peer.pending.extend(b"late\r\n")
    records = []
    with VerdiController("FAKE-ONLY", allow_writes=True, trace=records.append) as laser:
        with pytest.raises(VerdiError, match="buffered input") as caught:
            laser.start()
        assert caught.value.instruction == "L=1"
        assert caught.value.request == b"L=1\r\n"
        assert caught.value.raw_response == b""
        assert caught.value.write_outcome == "not_sent"
    assert records[0]["write_attempted"] is False
    assert records[0]["pending_bytes"] == len(b"late\r\n")
    assert records[0]["outcome"] == "not_sent"
    assert peer.pending == b"late\r\n"  # Evidence is not silently purged.
    assert peer.writes == []


def test_trace_sink_failure_after_acknowledged_write_preserves_outcome(peer):
    records = []

    def failed_sink(record):
        records.append(record)
        raise OSError("diagnostic disk full")

    peer.responses.append(b"\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True, trace=failed_sink) as laser:
        with pytest.raises(VerdiError, match="trace failed") as caught:
            laser.stop()
        assert caught.value.instruction == "L=0"
        assert caught.value.request == b"L=0\r\n"
        assert caught.value.raw_response == b"\r\n"
        assert caught.value.write_outcome == "acknowledged"
        assert isinstance(caught.value.__cause__, OSError)
        with pytest.raises(VerdiError, match="failed"):
            laser.start()
    assert records[0]["outcome"] == "acknowledged"
    assert records[0]["error"] is None
    assert peer.writes == [b"L=0\r\n"]


def test_trace_sink_failure_preserves_primary_error_and_note(peer):
    def failed_sink(record):
        raise OSError("diagnostic disk full")

    peer.responses.append(b"0.12")
    with VerdiController("FAKE-ONLY", trace=failed_sink) as laser:
        with pytest.raises(VerdiError, match="reply timed out") as caught:
            laser.read_power_w()
    assert caught.value.instruction == "?P"
    assert caught.value.raw_response == b"0.12"
    assert caught.value.write_outcome is None
    assert "transaction trace failed: diagnostic disk full" in caught.value.__notes__
    assert peer.writes == [b"?P\r\n"]


def test_trace_failure_preserves_device_rejection_but_retires_session(peer):
    def failed_sink(record):
        raise OSError("diagnostic disk full")

    peer.responses.append(b"Command Error: L=0\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True, trace=failed_sink) as laser:
        with pytest.raises(DeviceError) as caught:
            laser.stop()
        assert caught.value.write_outcome == "rejected"
        assert "transaction trace failed: diagnostic disk full" in caught.value.__notes__
        with pytest.raises(VerdiError, match="failed"):
            laser.stop()
    assert peer.writes == [b"L=0\r\n"]


@pytest.mark.parametrize("action", ["read", "start", "connect", "disconnect"])
def test_trace_callback_cannot_reenter_controller_or_change_connection(peer, action):
    records = []

    def reentrant_sink(record):
        records.append(record)
        if len(records) == 1:
            if action == "read":
                laser.read_power_w()
            else:
                getattr(laser, action)()

    peer.responses.extend([b"\r\n", b"0.125\r\n" if action == "read" else b"\r\n"])
    with VerdiController("FAKE-ONLY", allow_writes=True, trace=reentrant_sink) as laser:
        with pytest.raises(VerdiError) as caught:
            laser.stop()
        assert caught.value.instruction == "L=0"
        assert caught.value.request == b"L=0\r\n"
        assert caught.value.raw_response == b"\r\n"
        assert caught.value.write_outcome == "acknowledged"
        assert peer.closes == 0
        with pytest.raises(VerdiError, match="failed"):
            laser.start()
    assert peer.writes == [b"L=0\r\n"]
    assert peer.opens == peer.closes == 1
    assert len(records) == 1
    assert records[0]["outcome"] == "acknowledged"


def test_trace_callback_interrupt_is_propagated_and_retires_session(peer):
    records = []
    interrupt = KeyboardInterrupt("trace interrupted")

    def interrupted_sink(record):
        records.append(record)
        raise interrupt

    peer.responses.append(b"\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True, trace=interrupted_sink) as laser:
        with pytest.raises(KeyboardInterrupt) as caught:
            laser.stop()
        assert caught.value is interrupt
        with pytest.raises(VerdiError, match="failed"):
            laser.start()
    assert records[0]["outcome"] == "acknowledged"
    assert records[0]["response"] == b"\r\n"
    assert peer.writes == [b"L=0\r\n"]


def test_trace_callback_interrupt_does_not_replace_primary_timeout(peer):
    def interrupted_sink(record):
        raise KeyboardInterrupt("trace interrupted")

    peer.responses.append(b"partial")
    with VerdiController("FAKE-ONLY", trace=interrupted_sink) as laser:
        with pytest.raises(VerdiError, match="reply timed out") as caught:
            laser.capture("?SV")
    assert caught.value.instruction == "?SV"
    assert caught.value.raw_response == b"partial"
    assert "transaction trace failed: trace interrupted" in caught.value.__notes__


def test_trace_callback_cannot_mutate_returned_capture_record(peer):
    def destructive_sink(record):
        record.clear()

    peer.responses.append(b"TEST\r\n")
    with VerdiController("FAKE-ONLY", trace=destructive_sink) as laser:
        captured = laser.capture("?SV")
    assert captured["request"] == b"?SV\r\n"
    assert captured["response"] == b"TEST\r\n"
    assert captured["payload"] == "TEST"
    assert captured["outcome"] == "captured"


def test_capture_and_read_are_serialized_under_concurrent_callers(peer):
    peer.responses.extend([b"0.125\r\n"] * 40)
    records = []
    with VerdiController("FAKE-ONLY", trace=records.append) as laser:

        def read_or_capture(index):
            return laser.capture("?P")["payload"] if index % 2 else laser.read_power_w()

        with ThreadPoolExecutor(max_workers=8) as pool:
            values = list(pool.map(read_or_capture, range(40)))
    assert values == [0.125 if index % 2 == 0 else "0.125" for index in range(40)]
    assert len(peer.writes) == len(records) == 40
    assert sum(record["outcome"] == "captured" for record in records) == 20
    assert sum(record["outcome"] == "ok" for record in records) == 20


@pytest.mark.parametrize("trace", [False, "trace.jsonl", [], 1])
def test_invalid_trace_sink_rejected_before_open(peer, trace):
    with pytest.raises(ValueError, match="trace must be a callable"):
        VerdiController("FAKE-ONLY", trace=trace)
    assert peer.opens == 0
