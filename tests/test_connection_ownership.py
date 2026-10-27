"""Replace only handles owned by this driver in the same Python process."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
import serial
from fakes import SerialPeer

from coherent_verdi import VerdiController, VerdiError


@pytest.fixture
def ports(monkeypatch):
    handles, events = [], []
    active = [None]

    class Peer(SerialPeer):
        def __init__(self, **settings):
            super().__init__(**settings)
            self.index = len(handles)
            handles.append(self)

        def open(self):
            if active[0] is not None:
                raise PermissionError(13, "Access is denied")
            super().open()
            active[0] = self
            events.append(("open", self.index))

        def close(self):
            super().close()
            if active[0] is self:
                active[0] = None
            events.append(("close", self.index))

    monkeypatch.setattr(serial, "Serial", Peer)
    return handles, events, active


def test_connect_replaces_previous_controller_without_sending_commands(ports):
    handles, events, active = ports
    first = VerdiController("COM5")
    second = VerdiController("COM5")
    try:
        assert first.connect() is True
        assert second.connect() is True
        assert events == [("open", 0), ("close", 0), ("open", 1)]
        assert active[0] is handles[1]
        with pytest.raises(VerdiError, match="disconnected"):
            first.read(b"?SV")
        first.disconnect()  # Must not unregister or close the replacement.
        third = VerdiController("COM5")
        with pytest.raises(VerdiError, match="another controller"):
            third.connect(override=False)
        assert active[0] is handles[1]
        assert all(not handle.writes for handle in handles)
    finally:
        first.disconnect()
        second.disconnect()


def test_override_false_preserves_current_owner(ports):
    handles, events, active = ports
    first, second = VerdiController("COM5"), VerdiController("COM5")
    try:
        first.connect()
        with pytest.raises(VerdiError, match="override=True"):
            second.connect(override=False)
        assert len(handles) == 1 and not second.failed
        assert active[0] is handles[0] and events == [("open", 0)]
    finally:
        first.disconnect()


def test_new_controller_can_release_failed_previous_session_without_replay(ports):
    handles, events, active = ports
    first, second = VerdiController("COM5"), VerdiController("COM5")
    try:
        first.connect()
        with pytest.raises(VerdiError, match="timed out"):
            first.read(b"?SV")
        evidence = first.last_transaction
        assert second.connect() is True
        assert first.failed and first.last_transaction == evidence
        assert handles[0].writes == [b"?SV\r\n"] and not handles[1].writes
    finally:
        first.disconnect()
        second.disconnect()


def test_failed_owner_close_prevents_opening_replacement(ports):
    handles, events, active = ports
    first, second = VerdiController("COM5"), VerdiController("COM5")
    try:
        first.connect()
        handles[0].close_failure = OSError("close failed")
        with pytest.raises(VerdiError, match="close failed"):
            second.connect()
        assert len(handles) == 1 and active[0] is handles[0]
    finally:
        handles[0].close_failure = None
        first.disconnect()
        second.disconnect()


def test_override_waits_for_in_flight_transaction(ports, monkeypatch):
    handles, events, active = ports
    waiting, release, replacing = Event(), Event(), Event()
    first, second = VerdiController("COM5", model="V2"), VerdiController("COM5", model="V2")
    try:
        first.connect()
        original_read = handles[0].read
        handles[0].responses.append(b"6.05\r\nVerdi V-2>")

        def read(size):
            waiting.set()
            assert release.wait(2)
            return original_read(size)

        def replace():
            replacing.set()
            return second.connect()

        monkeypatch.setattr(handles[0], "read", read)
        with ThreadPoolExecutor(max_workers=2) as pool:
            query = pool.submit(first.read, b"?SV")
            try:
                assert waiting.wait(2)
                connection = pool.submit(replace)
                assert replacing.wait(2)
                assert not connection.done()
                assert events == [("open", 0)]
            finally:
                release.set()
            assert query.result() == b"6.05"
            assert connection.result() is True
        assert events == [("open", 0), ("close", 0), ("open", 1)]
    finally:
        first.disconnect()
        second.disconnect()


def test_external_owner_error_explains_override_limit(monkeypatch):
    class Denied(SerialPeer):
        def open(self):
            raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(serial, "Serial", Denied)
    with pytest.raises(VerdiError, match="other notebook kernel or application"):
        VerdiController("COM5").connect()
