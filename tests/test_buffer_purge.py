"""Explicit buffer maintenance through fake serial handles, never hardware."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import serial
from test_serial import FakeSerial

from coherent_verdi import SimulatedVerdi, VerdiController, VerdiError


class PurgeSerial(FakeSerial):
    def __init__(self):
        super().__init__()
        self.tx_pending = bytearray()
        self.purges = []
        self.purge_failure = None

    def reset_input_buffer(self):
        self.purges.append("rx")
        if self.purge_failure == "rx":
            raise OSError("RX reset failed")
        self.pending.clear()

    def reset_output_buffer(self):
        self.purges.append("tx")
        if self.purge_failure == "tx":
            raise OSError("TX reset failed")
        self.tx_pending.clear()


@pytest.fixture
def peer(monkeypatch):
    handle = PurgeSerial()
    monkeypatch.setattr(serial, "Serial", lambda **settings: handle)
    return handle


@pytest.mark.parametrize("allow_writes", [False, True])
def test_explicit_purge_discards_only_requested_queues_without_transmitting(peer, allow_writes):
    with VerdiController("FAKE-ONLY", allow_writes=allow_writes, prompt_enabled=False) as laser:
        peer.pending.extend(b"stale RX")
        peer.tx_pending.extend(b"queued TX")
        assert laser.purge_buffers() is None
        assert not peer.pending
        assert not peer.tx_pending
        assert peer.purges == ["tx", "rx"]
        assert not peer.writes and not laser.failed
        assert laser.last_transaction is None


@pytest.mark.parametrize("was_connected", [False, True])
def test_purge_requires_an_open_connection(peer, was_connected):
    laser = VerdiController("FAKE-ONLY", prompt_enabled=False)
    if was_connected:
        laser.connect()
        laser.disconnect()
    with pytest.raises(VerdiError, match="disconnected"):
        laser.purge_buffers()
    assert not peer.purges and not peer.writes
    assert not laser.failed


def test_purge_after_failed_exchange_preserves_failure_latch_and_evidence(peer):
    peer.responses.append(b"partial")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        with pytest.raises(VerdiError, match="timed out"):
            laser.get_value("?SV")
        evidence = laser.last_transaction
        peer.pending.extend(b"late RX")
        peer.tx_pending.extend(b"late TX")
        laser.purge_buffers()
        assert peer.purges == ["tx", "rx"]
        assert laser.failed and laser.last_transaction == evidence
        with pytest.raises(VerdiError, match="failed"):
            laser.get_value("?SV")
        with pytest.raises(VerdiError, match="failed"):
            laser.connect()
    assert peer.writes == [b"?SV\r\n"]


@pytest.mark.parametrize("direction,attempted", [("tx", ["tx"]), ("rx", ["tx", "rx"])])
def test_purge_error_latches_failure_without_retry_or_replacing_exchange(
    peer, direction, attempted
):
    peer.responses.append(b"6.05\r\n")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        assert laser.get_value("?SV") == "6.05"
        evidence = laser.last_transaction
        peer.purge_failure = direction
        with pytest.raises(VerdiError, match="serial buffer purge failed") as caught:
            laser.purge_buffers()
        assert isinstance(caught.value.__cause__, OSError)
        assert peer.purges == attempted
        assert laser.failed and laser.last_transaction == evidence
    assert peer.writes == [b"?SV\r\n"]


def test_purge_waits_for_transaction_lock(peer):
    started, finished = Event(), Event()
    with (
        VerdiController("FAKE-ONLY", prompt_enabled=False) as laser,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):

        def purge():
            started.set()
            laser.purge_buffers()
            finished.set()

        with laser._lock:
            future = pool.submit(purge)
            assert started.wait(1)
            assert not finished.wait(0.05)
            assert not peer.purges
        future.result(timeout=1)
        assert finished.is_set() and peer.purges == ["tx", "rx"]
        assert not peer.writes


def test_simulator_purge_has_no_device_effect_and_retains_failure_state(monkeypatch):
    with SimulatedVerdi() as laser:
        before = laser.status()
        evidence = laser.last_transaction
        laser.purge_buffers()
        assert laser.last_transaction == evidence and not laser.failed
        after = laser.status()
        assert {k: v for k, v in before.items() if k not in ("sampled_at", "duration_s")} == {
            k: v for k, v in after.items() if k not in ("sampled_at", "duration_s")
        }
        monkeypatch.setattr(laser, "_simulate_response", lambda request: b"bad\r\n")
        with pytest.raises(VerdiError):
            laser.get_value("?L")
        failed_evidence = laser.last_transaction
        laser.purge_buffers()
        assert laser.failed and laser.last_transaction == failed_evidence
