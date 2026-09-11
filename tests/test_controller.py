"""TEST-003/004: controller ownership, model limits and simulator behavior."""

import asyncio
import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, get_ident

import pytest

from coherent_verdi import DeviceError, SimulatedVerdi, VerdiController, VerdiError
from coherent_verdi.controller import QUERIES


@pytest.mark.parametrize("query", ["?P;L=1", "?P\r\nL=1", "?BAD", "", None, 1, []])
def test_invalid_queries_are_rejected_before_io(query):
    with SimulatedVerdi() as laser:
        with pytest.raises(ValueError):
            laser.read(query)
        assert laser.requests == ()
        assert laser.read_power_w() == 0


def test_plain_results_are_json_ready_and_cannot_change_device_state():
    import json

    with SimulatedVerdi() as laser:
        laser.set_faults(2, 999)
        status = laser.status()
        assert json.loads(json.dumps(status, allow_nan=False)) == status
        status["faults"].clear()
        status["power_w"] = 100
        faults = laser.read_faults()
        faults.append(30)
        assert laser.status()["faults"] == [2, 999]
        assert laser.read_power_w() == 0


def test_status_duration_includes_every_query(monkeypatch):
    ticks = [10.0]
    monkeypatch.setattr("coherent_verdi.controller.monotonic", lambda: ticks[0])

    class TimedSimulator(SimulatedVerdi):
        def _exchange(self, request):
            ticks[0] += 0.125
            return super()._exchange(request)

    sim = TimedSimulator(model="V5")
    with sim as laser:
        status = laser.status()
    assert len(sim.requests) == 14
    assert status["duration_s"] == 1.75


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "V9"},
        {"model": "V5", "allow_writes": "yes"},
        {"model": "V2", "power_limit_w": 3},
    ],
)
def test_constructor_settings_are_runtime_validated(kwargs):
    with pytest.raises(ValueError):
        SimulatedVerdi(**kwargs)


@pytest.mark.parametrize("reply", [True, "", " ", "1", "30", "1&2", "OK\r\n", "é", "X" * 129])
def test_invalid_or_fault_code_clear_override_rejected(reply):
    with pytest.raises(ValueError, match="active_fault_clear_reply"):
        VerdiController("FAKE-ONLY", active_fault_clear_reply=reply)


@pytest.mark.parametrize("history", ["False", "True", 0, 1, None])
def test_fault_selector_rejects_nonboolean_before_querying(history):
    sim = SimulatedVerdi()
    with sim as laser:
        with pytest.raises(ValueError, match="history must be a bool"):
            laser.read_faults(history=history)
        assert sim.requests == ()
        assert laser.read_faults() == []  # Local rejection leaves the session usable.
        assert sim.requests == (b"?F\r\n",)


@pytest.mark.parametrize("query", ["?D1SS", "?LBOSS"])
@pytest.mark.parametrize("model,invalid", [("V2", 6), ("V6", 5)])
def test_model_specific_servo_codes_reject_invalid_firmware_data(query, model, invalid):
    sim = SimulatedVerdi(model)
    sim.inject(f"{invalid}\r\n".encode())
    with sim as c:
        with pytest.raises(VerdiError, match="not documented"):
            c.read(query)
        with pytest.raises(VerdiError):
            c.read_power_w()
    assert len(sim.requests) == 1


@pytest.mark.parametrize("query", ["?D1SS", "?LBOSS"])
@pytest.mark.parametrize("model,valid", [("V2", 5), ("V6", 6), ("V5", 5), ("V5", 6)])
def test_model_specific_servo_codes_preserve_supported_and_unresolved_v5_variant(
    query, model, valid
):
    sim = SimulatedVerdi(model)
    sim.inject(f"{valid}\r\n".encode())
    with sim as c:
        assert c.read(query) == valid


@pytest.mark.parametrize("operand", ["1e-1", "0_1", "nan", "inf", "-1", "6"])
def test_simulator_power_rejects_undocumented_numeric_syntax_and_software_limits(operand):
    sim = SimulatedVerdi("V5")
    sim.connect()
    try:
        instruction = f"P={operand}".encode()
        assert sim._exchange(instruction + b"\r\n") == b"RANGE ERROR: " + instruction + b"\r\n"
        assert sim._exchange(b"?SP\r\n") == b"0.0000\r\n"
    finally:
        sim.disconnect()


@pytest.mark.parametrize("wire", [b"?P;L=1;", b"?P\r\nL=1\r\n", b"\xff;", b";"])
def test_simulator_never_accepts_batched_or_malformed_instructions(wire):
    sim = SimulatedVerdi()
    sim.connect()
    try:
        with pytest.raises(ValueError):
            sim._exchange(wire)
        assert sim._exchange(b"?L\r\n") == b"0\r\n"
    finally:
        sim.disconnect()


def test_closed_shutter_idle_is_not_diode_off_and_fault_cuts_current():
    c = SimulatedVerdi(allow_writes=True)
    c.connect()
    with c:
        c.set_key(True)
        c.start()
        assert c.read("?S") == 0
        assert c.read("?D1C") > 0  # Magnitude is a fixture, not a hardware claim.
        assert c.read("?C") == c.read("?D1C")
        c.set_faults(30)
        assert c.read("?D1C") == 0
        assert c.read("?S") == 0
        assert c.read_laser_state() == 2


@pytest.mark.parametrize("options", [{"echo": "0"}, {"prompt": "0"}])
def test_simulator_mode_configuration_does_not_coerce_strings(options):
    with pytest.raises(ValueError, match="bools"):
        SimulatedVerdi(**options)


@pytest.mark.parametrize("model,limit", [("V2", 2), ("V5", 5), ("V6", 6)])
def test_model_ceiling_and_units(model, limit):
    c = SimulatedVerdi(model, allow_writes=True)
    c.connect()
    c.set_power_w(limit)
    assert c.read("?SP") == limit
    with pytest.raises(ValueError):
        c.set_power_w(limit + 0.0001)
    assert c.status()["model"] == model
    assert b"P=" + f"{limit:.4f}".encode() + b"\r\n" in c.requests


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "1.0", 10**1000])
def test_bad_setpoints_do_not_reach_transport(value):
    c = SimulatedVerdi(allow_writes=True)
    c.connect()
    with pytest.raises(ValueError, match="finite"):
        c.set_power_w(value)
    assert not c.requests


def test_site_ceiling_rounding():
    sim = SimulatedVerdi(model="V5", allow_writes=True, power_limit_w=0.12346)
    c = sim
    with pytest.raises(ValueError, match="rounded"):
        c.set_power_w(0.12346)
    assert not sim.requests


def test_default_read_only_and_no_implicit_state_changes():
    c = SimulatedVerdi(allow_writes=False)
    c.connect()
    assert not c.requests
    with pytest.raises(PermissionError):
        c.start()
    with pytest.raises(PermissionError):
        c.stop()
    assert not c.requests
    assert c.status()["laser_state"] == 0
    assert all(r.startswith(b"?") for r in c.requests)
    before = c.requests
    c.disconnect()
    c.disconnect()
    assert c.requests == before
    with pytest.raises(VerdiError):
        c.read_power_w()


def test_fault_history_enable_and_key_semantics():
    c = SimulatedVerdi(allow_writes=True)
    c.connect()
    c.start()
    assert c.read_laser_state() == 0
    c.set_key(True)
    c.start()
    c.set_power_w(1.5)
    c.set_shutter(open=True)
    assert c.read_power_w() == 1.5
    c.set_faults(2, 8, 999)
    assert c.read_laser_state() == 2
    assert c.read_faults()[-1] == 999
    c.set_faults()
    assert c.read_laser_state() == 2  # no automatic re-enable on fault clearing
    assert len(c.read_faults(history=True)) == 3
    c.start()
    assert c.read_faults(history=True) == []
    assert c.read_laser_state() == 1
    c.stop()
    assert c.read_laser_state() == 0


def test_virtual_warmup_without_sleep():
    clock = [100.0]
    c = SimulatedVerdi(clock=lambda: clock[0], warmup_s=10, allow_writes=True)
    c.connect()
    c.set_power_w(0.5)
    s = c.status()
    assert s["lbo_servo"] == 2
    assert s["laser_state"] == 0
    assert s["power_w"] == 0
    assert s["lbo_temp_c"] == 25
    clock[0] += 10
    c.set_key(True)
    c.start()
    c.set_shutter(open=True)
    s = c.status()
    assert s["lbo_servo"] == 1
    assert s["power_w"] == 0.5
    assert s["lbo_temp_c"] == 148


@pytest.mark.parametrize("model", ["V2", "V5", "V6"])
def test_cold_key_on_reports_lbo_fault_and_needs_explicit_enable_after_warmup(model):
    clock = [0.0]
    sim = SimulatedVerdi(model, clock=lambda: clock[0], warmup_s=10, allow_writes=True)
    with sim as laser:
        sim.set_key(True)
        assert laser.read_laser_state() == 2
        assert laser.read_faults() == [5]
        laser.set_power_w(0.5)
        laser.start()
        laser.set_shutter(open=True)
        cold = laser.status()
        assert cold["laser_state"] == 2
        assert not cold["shutter_open"]
        assert cold["power_w"] == 0

        clock[0] = 10
        warm = laser.status()
        assert warm["faults"] == []
        assert warm["laser_state"] == 2
        assert not warm["shutter_open"]
        assert warm["power_w"] == 0
        assert laser.read_faults(history=True) == [5]

        # This conservative simulator latch is not a prediction of firmware
        # auto-resumption. Explicit enable and shutter operations are required.
        laser.start()
        assert laser.read_faults(history=True) == []
        assert laser.read_laser_state() == 1
        assert laser.read_power_w() == 0
        laser.set_shutter(open=True)
        assert laser.read_power_w() == 0.5


def test_standby_overrides_cold_key_without_retriggering_warmup_fault():
    sim = SimulatedVerdi(clock=lambda: 0.0, warmup_s=10, model="V5", allow_writes=True)
    with sim as laser:
        sim.set_key(True)
        assert laser.read_laser_state() == 2
        laser.stop()
        assert laser.read_laser_state() == 0
        assert laser.read_faults() == []
        assert laser.read_faults(history=True) == [5]


def test_finishing_warmup_does_not_remove_an_injected_lbo_fault():
    clock = [0.0]
    sim = SimulatedVerdi(clock=lambda: clock[0], warmup_s=10, model="V5", allow_writes=True)
    with sim as laser:
        sim.set_key(True)
        sim.set_faults(5, 999)
        assert laser.read_faults() == [5, 999]
        clock[0] = 10
        laser.start()
        assert laser.read_laser_state() == 2
        assert laser.read_faults() == [5, 999]


def test_explicit_echo_and_reversed_prompt_setting():
    c = SimulatedVerdi(allow_writes=True)
    c.connect()
    c.set_echo(enabled=True)
    c.set_prompt(enabled=True)
    assert c.read_power_w() == 0
    c.set_prompt(enabled=False)
    c.set_echo(enabled=False)
    assert c.read_power_w() == 0
    assert b"PROMPT=0\r\n" in c.requests
    assert b"PROMPT=1\r\n" in c.requests


@pytest.mark.parametrize("model", ["V2", "V5", "V6"])
def test_every_query_through_simulated_protocol(model):
    c = SimulatedVerdi(model, allow_writes=True)
    c.connect()
    for query in QUERIES:
        c.read(query)
    assert c.read_diagnostics()["software_version"].startswith("SIMULATOR")


def test_applied_command_with_lost_acknowledgment_is_not_replayed():
    c = SimulatedVerdi(allow_writes=True)
    c.connect()
    c.set_key(True)
    c.inject_timeout(after_apply=True)
    with pytest.raises(VerdiError):
        c.start()
    with pytest.raises(VerdiError):
        c.read_laser_state()
    # Inspect the independent fixture only: production code cannot reuse the failed session.
    assert c._exchange(b"?L\r\n") == b"1\r\n"
    assert c.requests.count(b"L=1\r\n") == 1


def test_device_rejection_leaves_complete_session_usable():
    sim = SimulatedVerdi(model="V5", allow_writes=True)
    with sim as c:
        sim.inject(b"RANGE ERROR: P=1.0000\r\n")
        with pytest.raises(DeviceError):
            c.set_power_w(1)
        assert c.read_power_w() == 0


def test_malformed_reply_requires_retiring_the_session():
    c = SimulatedVerdi(allow_writes=True)
    c.connect()
    c.inject(b"nan\r\n")
    with pytest.raises(VerdiError):
        c.read_power_w()
    with pytest.raises(VerdiError):
        c.read_power_w()
    fresh = SimulatedVerdi()
    c.disconnect()
    c = fresh
    c.connect()
    assert fresh.requests == ()
    assert c.read_laser_state() == 0


@pytest.mark.parametrize("query", ["?L", "?B", "?F", "?FH"])
def test_integer_conversion_limit_invalidates_session(query):
    original_limit = sys.get_int_max_str_digits()
    sim = SimulatedVerdi(model="V5")
    with sim as controller:
        try:
            # Exercise the interpreter guard deterministically, even when the
            # invoking process has disabled or increased its default limit.
            sys.set_int_max_str_digits(640)
            sim.inject(b"9" * 641 + b"\r\n")
            with pytest.raises(VerdiError, match="conversion limit"):
                controller.read(query)
            before = sim.requests
            with pytest.raises(VerdiError):
                controller.read_laser_state()
            assert sim.requests == before
        finally:
            sys.set_int_max_str_digits(original_limit)

        replacement = SimulatedVerdi()
        controller.disconnect()
        controller = replacement
        controller.connect()
        assert replacement.requests == ()
        assert controller.read_power_w() == 0


def test_compound_snapshot_not_interleaved_with_commands():
    c = SimulatedVerdi(allow_writes=True)
    c.connect()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: c.status() if n % 2 else c.stop(), range(20)))
    requests = c.requests
    for start in (i for i, request in enumerate(requests) if request == b"?L\r\n"):
        assert all(r.startswith(b"?") for r in requests[start : start + 14])
        assert requests[start + 13] == b"?F\r\n"


def test_async_example_keeps_cleanup_with_inflight_worker_on_cancellation(monkeypatch):
    source = Path(__file__).resolve().parents[1] / "examples" / "async_integration.py"
    spec = importlib.util.spec_from_file_location("verdi_async_example", source)
    example = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(example)
    entered, release, closed = Event(), Event(), Event()
    threads = []

    class FakeController:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            threads.append(get_ident())
            return self

        def status(self):
            threads.append(get_ident())
            entered.set()
            assert release.wait(3)
            return object()

        def read_diagnostics(self):
            return object()

        def __exit__(self, *args):
            threads.append(get_ident())
            closed.set()

    monkeypatch.setattr(example, "SimulatedVerdi", FakeController)

    async def scenario():
        task = asyncio.create_task(example.main())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not closed.is_set(), "cleanup overtook the unfinished worker operation"
        finally:
            release.set()
            assert await asyncio.to_thread(closed.wait, 2)

    asyncio.run(scenario())
    assert len(threads) == 3 and len(set(threads)) == 1
    assert threads[0] != get_ident()
