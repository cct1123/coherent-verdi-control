"""TEST-005/017: optional caller-driven monitoring and dependency-free integration."""

import json
import subprocess
import sys
from threading import enumerate as threads

import pytest

from coherent_verdi import SimulatedTransport, VerdiController
from coherent_verdi.monitor import Monitor, to_json


@pytest.mark.parametrize(
    "options",
    [
        {"interval_s": 0},
        {"interval_s": float("nan")},
        {"history_size": 0},
        {"history_size": True},
    ],
)
def test_invalid_monitor_settings(options):
    with pytest.raises(ValueError):
        Monitor(VerdiController(SimulatedTransport()), **options)


def test_sampling_is_explicit_bounded_and_does_not_own_the_connection():
    before = threads()
    sim = SimulatedTransport()
    laser = VerdiController(sim)
    monitor = Monitor(laser, history_size=17)
    assert not sim.requests and monitor.snapshot()["history"] == ()
    laser.connect()
    for _ in range(1000):
        assert monitor.poll_once().error is None
    samples = monitor.snapshot()["history"]
    assert len(samples) == 17 and samples[0].sequence == 984 and samples[-1].sequence == 1000
    assert len(sim.requests) == 4096
    assert threads() == before
    record = json.loads(to_json(samples[-1]))
    assert record["status"]["power_w"] == 0
    assert record["status"]["sampled_at"].endswith("+00:00")
    laser.disconnect()
    failure = monitor.poll_once()
    assert failure.status is None and "TransportError" in failure.error


def test_core_import_does_not_load_optional_clients_or_start_threads():
    code = """
import sys, threading
before = threading.enumerate()
from coherent_verdi import VerdiController, SimulatedTransport
with VerdiController(SimulatedTransport()) as laser:
    assert laser.read('?P') == 0
assert threading.enumerate() == before
for name in ('serial', 'dash', 'plotly', 'coherent_verdi.gui', 'coherent_verdi.monitor'):
    assert name not in sys.modules, name
"""
    subprocess.run([sys.executable, "-c", code], check=True, timeout=15)
