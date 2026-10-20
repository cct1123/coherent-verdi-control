"""Real controller API through a fake pySerial handle, never a port."""

import json
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import pytest
import serial

from coherent_verdi import VerdiController, VerdiError
from coherent_verdi.__main__ import main


class FakeSerial:
    """A byte-oriented peer that can retain unsolicited or duplicate replies."""

    def __init__(self, **settings):
        self.settings = settings
        self.responses = deque()
        self.pending = bytearray()
        self.writes = []
        self.opens = self.closes = 0
        self.write_failure = self.read_failure = self.open_failure = self.close_failure = None
        self.in_waiting_failure = None
        self.partial = False

    @property
    def in_waiting(self):
        if self.in_waiting_failure:
            raise self.in_waiting_failure
        return len(self.pending)

    def open(self):
        self.opens += 1
        if self.open_failure:
            raise self.open_failure

    def write(self, data):
        if self.write_failure:
            raise self.write_failure
        self.writes.append(data)
        self.pending.extend(self.responses.popleft() if self.responses else b"")
        return len(data) - int(self.partial)

    def read(self, size):
        if self.read_failure:
            raise self.read_failure
        chunk = self.pending[:size]
        del self.pending[:size]
        return bytes(chunk)

    def close(self):
        self.closes += 1
        if self.close_failure:
            raise self.close_failure


@pytest.fixture
def peer(monkeypatch):
    fake = FakeSerial()

    def construct(**settings):
        fake.settings = settings
        return fake

    monkeypatch.setattr(serial, "Serial", construct)
    return fake


@pytest.mark.parametrize(
    ("command", "reply", "expected"),
    [
        (["query", "?SV"], b"TEST-FIRMWARE\r\n", "TEST-FIRMWARE"),
        (["query", "?P"], b"0.125\r\n", 0.125),
    ],
)
def test_cli_hardware_reads_explicit_port_without_initialization(
    peer, capsys, command, reply, expected
):
    peer.responses.append(reply)
    assert main(["--port", "FAKE-ONLY", "--model", "V6", "--baudrate", "9600", *command]) == 0
    assert json.loads(capsys.readouterr().out) == expected
    assert peer.port == "FAKE-ONLY"
    assert peer.settings["baudrate"] == 9600
    assert peer.writes == [(command[1] + "\r\n").encode()]
    assert peer.opens == peer.closes == 1


@pytest.mark.parametrize(
    "options",
    [
        ["--port", "FAKE-ONLY", "query", "?SV"],
        ["--baudrate", "9600", "query", "?SV"],
    ],
)
def test_cli_incomplete_connection_settings_never_open(peer, options):
    with pytest.raises(SystemExit) as error:
        main(options)
    assert error.value.code == 2
    assert peer.opens == 0


@pytest.mark.parametrize(
    "options",
    [
        ["--baudrate", "12345", "query", "?SV"],
        ["--timeout-s", "nan", "query", "?SV"],
        ["watch", "--count", "0"],
        ["watch", "--interval", "nan"],
        ["gui", "--port", "0"],
    ],
)
def test_cli_invalid_hardware_configuration_never_open(peer, capsys, options):
    assert main(["--port", "FAKE-ONLY", "--model", "V5", *options]) == 2
    assert json.loads(capsys.readouterr().err)["type"] == "ValueError"
    assert peer.opens == 0


def test_cli_hardware_open_failure_does_not_fall_back_to_simulation(peer, capsys):
    peer.open_failure = OSError("disconnected adapter")
    assert main(["--port", "FAKE-ONLY", "--model", "V5", "query", "?SV"]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "disconnected adapter" in json.loads(output.err)["error"]
    assert peer.opens == 1 and peer.writes == []


def test_cli_hardware_timeout_never_retries(peer, capsys):
    assert (
        main(["--port", "FAKE-ONLY", "--model", "V5", "--timeout-s", "0.001", "query", "?SV"]) == 2
    )
    assert "timed out" in json.loads(capsys.readouterr().err)["error"]
    assert peer.opens == peer.closes == 1
    assert peer.writes == [b"?SV\r\n"]


def test_commission_defaults_to_one_raw_version_query(peer, capsys):
    peer.responses.append(b"Version-TEST\r\n")
    assert main(["--port", "FAKE-ONLY", "--model", "V5", "commission"]) == 0
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert record["instruction"] == "?SV" and record["payload"] == "Version-TEST"
    assert bytes.fromhex(record["request_hex"]) == b"?SV\r\n"
    assert bytes.fromhex(record["response_hex"]) == b"Version-TEST\r\n"
    assert record["outcome"] == "captured" and record["simulated"] is False
    assert output.err == ""
    assert peer.writes == [b"?SV\r\n"] and peer.opens == peer.closes == 1


@pytest.mark.parametrize("reply", [b"UNVERIFIED CLEAR\r\n", b"\r\n", b"0\r\n"])
def test_commission_captures_fault_reply_without_assuming_clear(peer, capsys, reply):
    peer.responses.extend([b"Version-TEST\r\n", reply])
    assert (
        main(
            [
                "--port",
                "FAKE-ONLY",
                "--model",
                "V5",
                "commission",
                "--query",
                "?SV",
                "--query",
                "?F",
            ]
        )
        == 0
    )
    rows = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
    assert [row["instruction"] for row in rows] == ["?SV", "?F"]
    assert bytes.fromhex(rows[1]["response_hex"]) == reply
    assert rows[1]["outcome"] == "captured" and "faults" not in rows[1]
    assert peer.writes == [b"?SV\r\n", b"?F\r\n"]


@pytest.mark.parametrize(
    "args",
    [
        ["commission"],
        ["--port", "FAKE-ONLY", "--model", "V5", "commission", "--query", "L=1"],
    ],
)
def test_commission_requires_explicit_connection_and_whitelisted_queries(peer, args):
    with pytest.raises(SystemExit) as caught:
        main(args)
    assert caught.value.code == 2
    assert peer.opens == 0 and peer.writes == []


@pytest.mark.parametrize(
    ("reply", "outcome"),
    [
        (b"Query Error: ?SV\r\n", "rejected"),
        (b"Version-TEST\r\n0\r\n", "failed"),
        (b"partial", "failed"),
        (b"\xff\r\n", "failed"),
    ],
)
def test_commission_records_failure_and_stops_remaining_queries(peer, capsys, reply, outcome):
    peer.responses.extend([reply, b"0\r\n"])
    assert (
        main(
            [
                "--port",
                "FAKE-ONLY",
                "--model",
                "V5",
                "commission",
                "--query",
                "?SV",
                "--query",
                "?F",
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert record["outcome"] == outcome and record["error"]
    assert json.loads(output.err)["type"] in ("DeviceError", "VerdiError")
    assert peer.writes == [b"?SV\r\n"] and peer.closes == 1


@pytest.mark.parametrize(
    "options",
    [
        {"port": ""},
        {"port": "loop://"},
        {"port": None},
        {"baudrate": 115200},
        {"baudrate": 19200.0},
        {"timeout_s": 0},
        {"timeout_s": float("inf")},
        {"timeout_s": True},
    ],
)
def test_invalid_connection_settings_never_open(peer, options):
    with pytest.raises(ValueError):
        VerdiController(**({"port": "FAKE-ONLY"} | options))
    assert peer.opens == 0


def test_passive_explicit_lifecycle_and_framing(peer):
    laser = VerdiController("FAKE-ONLY")
    assert peer.opens == 0
    with pytest.raises(VerdiError, match="disconnected"):
        laser.read_power_w()
    laser.connect()
    laser.connect()
    assert peer.opens == 1 and not peer.writes
    assert peer.settings == dict(
        port=None,
        baudrate=19200,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=1.0,
        write_timeout=1.0,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    assert peer.port == "FAKE-ONLY" and peer.dtr is False and peer.rts is False
    peer.responses.append(b"1.234\r\n")
    assert laser.read_power_w() == 1.234
    assert peer.write_timeout == 1 and 0 < peer.timeout <= 1
    laser.disconnect()
    laser.disconnect()
    assert peer.closes == 1 and peer.writes == [b"?P\r\n"]
    # Normal, fully acknowledged sessions can explicitly reopen; no state is replayed.
    laser.connect()
    laser.disconnect()
    assert peer.opens == peer.closes == 2
    assert peer.writes == [b"?P\r\n"]


@pytest.mark.parametrize(
    "reply,error",
    [
        (b"", "timed out"),
        (b"1.2", "timed out"),
        (b"1.2\r", "timed out"),
        (b"X" * 4096, "byte limit"),
        (b"nan\r\n", "expected decimal"),
        (b"\x001\r\n", "control character"),
    ],
)
def test_failed_read_blocks_late_replies_and_reconnect(peer, reply, error):
    peer.responses.extend([reply, b"9.000\r\n"])
    with VerdiController("FAKE-ONLY") as laser:
        with pytest.raises(VerdiError, match=error):
            laser.read_power_w()
        for action in (laser.read_power_w, laser.connect):
            with pytest.raises(VerdiError, match="failed"):
                action()
        laser.disconnect()
        with pytest.raises(VerdiError, match="failed"):
            laser.connect()
    assert peer.writes == [b"?P\r\n"]


@pytest.mark.parametrize("queued", [b"0", b"0\r\n", b"\r\n"])
def test_preexisting_input_blocks_transmission_and_latches_failure(peer, queued):
    peer.pending.extend(queued)
    peer.responses.append(b"1.234\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises(VerdiError):
            laser.read_power_w()
        for action in (laser.read_power_w, laser.start, laser.connect):
            with pytest.raises(VerdiError, match="failed"):
                action()
    assert peer.writes == []


@pytest.mark.parametrize("trailing", [b"0\r\n", b"0", b"\r\n", b"unsolicited\r\n"])
def test_trailing_reply_bytes_cannot_shift_the_next_read(peer, trailing):
    peer.responses.extend([b"1.000\r\n" + trailing, b"1\r\n"])
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises(VerdiError):
            laser.read_power_w()
        for action in (laser.read_laser_state, laser.start, laser.connect):
            with pytest.raises(VerdiError, match="failed"):
                action()
    # In particular, the queued 0 must never be returned as the next ?L value.
    assert peer.writes == [b"?P\r\n"]


def test_bytes_arriving_between_requests_block_the_next_transmission(peer):
    peer.responses.extend([b"1.000\r\n", b"1\r\n"])
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        assert laser.read_power_w() == 1.0
        peer.pending.extend(b"0\r\n")
        with pytest.raises(VerdiError):
            laser.read_laser_state()
        with pytest.raises(VerdiError, match="failed"):
            laser.start()
    assert peer.writes == [b"?P\r\n"]


@pytest.mark.parametrize("reply", [b"\r\n", b"Command Error: unsupported\r\n"])
def test_trailing_command_reply_bytes_invalidate_even_complete_rejections(peer, reply):
    peer.responses.extend([reply + b"0\r\n", b"\r\n"])
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises(VerdiError):
            laser.start()
        for action in (laser.start, laser.stop, laser.read_power_w, laser.connect):
            with pytest.raises(VerdiError, match="failed"):
                action()
    assert peer.writes == [b"L=1\r\n"]


@pytest.mark.parametrize("when", ["before_write", "after_reply"])
def test_pending_count_failure_latches_without_replaying(peer, monkeypatch, when):
    peer.responses.append(b"1.000\r\n")
    if when == "before_write":
        peer.in_waiting_failure = OSError("adapter input-count failure")
    else:
        read = peer.read

        def fail_after_terminator(size):
            result = read(size)
            if result == b"\n":
                peer.in_waiting_failure = OSError("adapter input-count failure")
            return result

        monkeypatch.setattr(peer, "read", fail_after_terminator)
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises(VerdiError, match="input-count failure"):
            laser.read_power_w()
        peer.in_waiting_failure = None
        for action in (laser.read_power_w, laser.start, laser.connect):
            with pytest.raises(VerdiError, match="failed"):
                action()
    assert peer.writes == ([] if when == "before_write" else [b"?P\r\n"])


@pytest.mark.parametrize("failure", ["partial", "write", "interrupt", "unexpected"])
def test_uncertain_write_is_never_replayed(peer, failure):
    peer.partial = failure == "partial"
    if failure == "write":
        peer.write_failure = OSError("cable loss")
    if failure == "interrupt":
        peer.read_failure = KeyboardInterrupt()
    if failure == "unexpected":
        peer.read_failure = RuntimeError("adapter failure")
    peer.responses.append(b"\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises((VerdiError, KeyboardInterrupt, RuntimeError)):
            laser.start()
        for action in (laser.start, laser.stop, laser.read_power_w):
            with pytest.raises(VerdiError):
                action()
    assert peer.writes in ([], [b"L=1\r\n"])


def test_one_deadline_includes_write_and_all_bytes(peer, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("coherent_verdi.controller.monotonic", lambda: now[0])
    read = peer.read

    def delayed(size):
        now[0] += 0.004
        return read(size)

    monkeypatch.setattr(peer, "read", delayed)
    peer.responses.append(b"1.234\r\n")
    with VerdiController("FAKE-ONLY", timeout_s=0.01) as laser:
        with pytest.raises(VerdiError, match="timed out"):
            laser.read_power_w()
    assert now[0] == 0.012


def test_complete_reply_after_deadline_rejected(peer, monkeypatch):
    now = [0.0]
    monkeypatch.setattr("coherent_verdi.controller.monotonic", lambda: now[0])
    read = peer.read

    def late_terminator(size):
        result = read(size)
        if result == b"\n":
            now[0] = 0.02
        return result

    monkeypatch.setattr(peer, "read", late_terminator)
    peer.responses.append(b"\r\n")
    with VerdiController("FAKE-ONLY", timeout_s=0.01, allow_writes=True) as laser:
        with pytest.raises(VerdiError, match="timed out"):
            laser.start()


def test_many_callers_cannot_mix_replies(peer):
    peer.responses.extend([b"1.234\r\n"] * 80)
    with VerdiController("FAKE-ONLY") as laser:
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(lambda _: laser.read_power_w(), range(80))) == [1.234] * 80
    assert len(peer.writes) == 80


@pytest.mark.parametrize("failure", [OSError("open failure"), KeyboardInterrupt()])
def test_failed_open_cleans_up_without_commands(peer, failure):
    peer.open_failure = failure
    laser = VerdiController("FAKE-ONLY")
    with pytest.raises((VerdiError, KeyboardInterrupt)):
        laser.connect()
    assert peer.closes == 1 and not peer.writes
    with pytest.raises(VerdiError):
        laser.connect()


def test_cleanup_failure_can_be_retried_without_reviving_connection(peer):
    laser = VerdiController("FAKE-ONLY")
    laser.connect()
    peer.close_failure = OSError("close failure")
    with pytest.raises(VerdiError):
        laser.disconnect()
    with pytest.raises(VerdiError):
        laser.read_power_w()
    peer.close_failure = None
    laser.disconnect()
    laser.disconnect()
    assert peer.closes == 2
    with pytest.raises(VerdiError):
        laser.connect()


def test_primary_error_survives_failed_context_cleanup(peer):
    peer.close_failure = OSError("close failure")
    with pytest.raises(RuntimeError, match="experiment failure") as caught:
        with VerdiController("FAKE-ONLY"):
            raise RuntimeError("experiment failure")
    assert "close failure" in caught.value.__notes__[0]


@pytest.mark.parametrize("reply", [b"SYSTEM OK", b"0", b"OK"])
def test_unverified_active_clear_reply_blocks_writes(peer, reply):
    peer.responses.append(reply + b"\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True) as laser:
        with pytest.raises(VerdiError):
            laser.read_faults()
        with pytest.raises(VerdiError):
            laser.start()
    assert peer.writes == [b"?F\r\n"]


def test_display_source_flag_cannot_enable_unverified_fault_parsing(peer):
    peer.responses.append(b"SYSTEM OK\r\n")
    with VerdiController("FAKE-ONLY") as laser:
        laser.is_simulated = True
        with pytest.raises(VerdiError):
            laser.read_faults()
    assert peer.writes == [b"?F\r\n"]


@pytest.mark.parametrize("clear", ["SYSTEM OK", "0"])
def test_verified_clear_reply_is_used_only_for_active_faults(peer, clear):
    peer.responses.extend([clear.encode() + b"\r\n", b"SYSTEM OK\r\n", b"30&999\r\n"])
    with VerdiController("FAKE-ONLY", active_fault_clear_reply=clear) as laser:
        assert laser.read_faults() == laser.read_faults(history=True) == []
        known, unknown = laser.read_faults()
        assert known == 30
        assert unknown == 999
