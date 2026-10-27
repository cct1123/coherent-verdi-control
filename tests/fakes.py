"""Adversarial test fixture operations, deliberately outside the public package."""

from collections import deque

import serial

from coherent_verdi import SimulatedVerdi, VerdiError


class RecordingVerdi(SimulatedVerdi):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._requests = deque(maxlen=4096)

    @property
    def requests(self):
        with self._lock:
            return tuple(self._requests)

    def _simulate_response(self, request):
        with self._lock:
            self._requests.append(request)
            return super()._simulate_response(request)


class FaultyVerdi(RecordingVerdi):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._injections = deque()

    def inject(self, response, *, after_apply=False):
        self._injections.append((response, after_apply))

    def inject_timeout(self, *, after_apply=False):
        self.inject(VerdiError("simulated response timeout"), after_apply=after_apply)

    def _simulate_response(self, request):
        if not self._injections:
            return super()._simulate_response(request)
        response, after_apply = self._injections.popleft()
        if after_apply:
            super()._simulate_response(request)
        else:
            self._requests.append(request)
        if isinstance(response, Exception):
            raise response
        return response


class SerialPeer:
    """In-memory serial handle using pySerial's own read_until implementation."""

    def __init__(self, **settings):
        self.settings = settings
        self.responses = deque()
        self.pending = bytearray()
        self.writes = []
        self.opens = self.closes = 0
        self.write_failure = self.read_failure = self.open_failure = self.close_failure = None
        self.partial = False

    @property
    def in_waiting(self):
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

    def read_until(self, expected=b"\n", size=None):
        self._timeout = self.timeout
        return serial.SerialBase.read_until(self, expected, size)

    def close(self):
        self.closes += 1
        if self.close_failure:
            raise self.close_failure

    def reset_output_buffer(self):
        pass

    def reset_input_buffer(self):
        self.pending.clear()
