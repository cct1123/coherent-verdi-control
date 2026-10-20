"""Adversarial test fixture operations, deliberately outside the public package."""

from collections import deque

from coherent_verdi import SimulatedVerdi, VerdiError


class RecordingVerdi(SimulatedVerdi):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._requests = deque(maxlen=4096)

    @property
    def requests(self):
        with self._lock:
            return tuple(self._requests)

    def _exchange(self, request):
        with self._lock:
            self._requests.append(request)
            return super()._exchange(request)


class FaultyVerdi(RecordingVerdi):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._injections = deque()

    def inject(self, response, *, after_apply=False):
        self._injections.append((response, after_apply))

    def inject_timeout(self, *, after_apply=False):
        self.inject(VerdiError("simulated response timeout"), after_apply=after_apply)

    def _exchange(self, request):
        if not self._injections:
            return super()._exchange(request)
        response, after_apply = self._injections.popleft()
        if after_apply:
            super()._exchange(request)
        else:
            self._requests.append(request)
        if isinstance(response, Exception):
            raise response
        return response
