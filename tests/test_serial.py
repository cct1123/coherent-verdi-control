"""TEST-002/003/009: real controller API through a fake pySerial handle, never a port."""

from collections import deque
from concurrent.futures import ThreadPoolExecutor

import pytest
import serial

from coherent_verdi import VerdiController, VerdiError


class FakeSerial:
    """A byte-oriented peer: it rejects overlapping transactions."""

    def __init__(self, **settings):
        self.settings = settings
        self.responses = deque()
        self.pending = bytearray()
        self.writes = []
        self.opens = self.closes = 0
        self.write_failure = self.read_failure = self.open_failure = self.close_failure = None
        self.partial = False

    def open(self):
        self.opens += 1
        if self.open_failure:
            raise self.open_failure

    def write(self, data):
        if self.write_failure:
            raise self.write_failure
        assert not self.pending, "overlapping requests"
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
        with pytest.raises((VerdiError, VerdiError), match=error):
            laser.read_power_w()
        for action in (laser.read_power_w, laser.connect):
            with pytest.raises(VerdiError, match="failed"):
                action()
        laser.disconnect()
        with pytest.raises(VerdiError, match="failed"):
            laser.connect()
    assert peer.writes == [b"?P\r\n"]


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
