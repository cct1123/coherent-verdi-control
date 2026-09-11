"""TEST-003/004: controller ownership, model limits and simulator behavior."""

import asyncio
import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, get_ident

import pytest

from coherent_verdi import (
    DeviceError,
    LaserState,
    Model,
    ProtocolError,
    Query,
    ServoState,
    SimulatedTransport,
    TransportError,
    VerdiController,
)


def controller(model=Model.V5, *, writes=True, **kwargs):
    sim = SimulatedTransport(model, **kwargs)
    laser = VerdiController(sim, model=model, allow_writes=writes)
    laser.connect()
    return sim, laser


def test_status_duration_includes_every_query(monkeypatch):
    ticks = [10.0]
    monkeypatch.setattr("coherent_verdi.controller.monotonic", lambda: ticks[0])

    class TimedSimulator(SimulatedTransport):
        def exchange(self, request):
            ticks[0] += 0.125
            return super().exchange(request)

    sim = TimedSimulator()
    with VerdiController(sim, model=Model.V5) as laser:
        status = laser.status()
    assert len(sim.requests) == 14
    assert status.duration_s == 1.75


@pytest.mark.parametrize(
    "kwargs",
    [
        {"model": "V9"},
        {"model": Model.V5, "allow_writes": "yes"},
        {"model": Model.V2, "power_limit_w": 3},
    ],
)
def test_constructor_settings_are_runtime_validated(kwargs):
    with pytest.raises(ValueError):
        VerdiController(SimulatedTransport(), **kwargs)


@pytest.mark.parametrize("reply", [True, "", " ", "1", "30", "1&2", "OK\r\n", "é", "X" * 129])
def test_invalid_or_fault_code_clear_override_rejected(reply):
    with pytest.raises(ValueError, match="active_fault_clear_reply"):
        VerdiController(SimulatedTransport(), active_fault_clear_reply=reply)


@pytest.mark.parametrize("history", ["False", "True", 0, 1, None])
def test_fault_selector_rejects_nonboolean_before_querying(history):
    sim = SimulatedTransport()
    with VerdiController(sim) as laser:
        with pytest.raises(ValueError, match="history must be a bool"):
            laser.read_faults(history=history)
        assert sim.requests == ()
        assert laser.read_faults() == ()  # Local rejection leaves the session usable.
        assert sim.requests == (b"?F\r\n",)


@pytest.mark.parametrize("query", [Query.DIODE_SERVO, Query.LBO_SERVO])
@pytest.mark.parametrize("model,invalid", [(Model.V2, 6), (Model.V6, 5)])
def test_model_specific_servo_codes_reject_invalid_firmware_data(query, model, invalid):
    sim = SimulatedTransport(model)
    sim.inject(f"{invalid}\r\n".encode())
    with VerdiController(sim, model=model) as c:
        with pytest.raises(ProtocolError, match="not documented"):
            c.read(query)
        with pytest.raises(TransportError):
            c.read_power_w()
    assert len(sim.requests) == 1


@pytest.mark.parametrize("query", [Query.DIODE_SERVO, Query.LBO_SERVO])
@pytest.mark.parametrize(
    "model,valid", [(Model.V2, 5), (Model.V6, 6), (Model.V5, 5), (Model.V5, 6)]
)
def test_model_specific_servo_codes_preserve_supported_and_unresolved_v5_variant(
    query, model, valid
):
    sim = SimulatedTransport(model)
    sim.inject(f"{valid}\r\n".encode())
    with VerdiController(sim, model=model) as c:
        assert c.read(query) == valid


@pytest.mark.parametrize("operand", ["1e-1", "0_1", "nan", "inf", "-1", "6"])
def test_simulator_power_rejects_undocumented_numeric_syntax_and_software_limits(operand):
    sim = SimulatedTransport(Model.V5)
    sim.connect()
    try:
        instruction = f"P={operand}".encode()
        assert sim.exchange(instruction + b"\r\n") == b"RANGE ERROR: " + instruction + b"\r\n"
        assert sim.exchange(b"?SP\r\n") == b"0.0000\r\n"
    finally:
        sim.disconnect()


@pytest.mark.parametrize("wire", [b"?P;L=1;", b"?P\r\nL=1\r\n", b"\xff;", b";"])
def test_simulator_never_accepts_batched_or_malformed_instructions(wire):
    sim = SimulatedTransport()
    sim.connect()
    try:
        with pytest.raises(ValueError):
            sim.exchange(wire)
        assert sim.exchange(b"?L\r\n") == b"0\r\n"
    finally:
        sim.disconnect()


def test_closed_shutter_idle_is_not_diode_off_and_fault_cuts_current():
    sim, c = controller()
    with c:
        sim.set_key(True)
        c.start()
        assert c.read(Query.SHUTTER) == 0
        assert c.read(Query.DIODE_CURRENT) > 0  # Magnitude is a fixture, not a hardware claim.
        assert c.read(Query.CURRENT) == c.read(Query.DIODE_CURRENT)
        sim.set_faults(30)
        assert c.read(Query.DIODE_CURRENT) == 0
        assert c.read(Query.SHUTTER) == 0
        assert c.read_laser_state() == LaserState.FAULT


@pytest.mark.parametrize("options", [{"echo": "0"}, {"prompt": "0"}])
def test_simulator_mode_configuration_does_not_coerce_strings(options):
    with pytest.raises(ValueError, match="bools"):
        SimulatedTransport(**options)


@pytest.mark.parametrize("model,limit", [(Model.V2, 2), (Model.V5, 5), (Model.V6, 6)])
def test_model_ceiling_and_units(model, limit):
    sim, c = controller(model)
    c.set_power_w(limit)
    assert c.read(Query.SET_POWER) == limit
    with pytest.raises(ValueError):
        c.set_power_w(limit + 0.0001)
    assert c.status().model == model
    assert b"P=" + f"{limit:.4f}".encode() + b"\r\n" in sim.requests


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "1.0", 10**1000])
def test_bad_setpoints_do_not_reach_transport(value):
    sim, c = controller()
    with pytest.raises(ValueError, match="finite"):
        c.set_power_w(value)
    assert not sim.requests


def test_site_ceiling_rounding():
    sim = SimulatedTransport()
    c = VerdiController(sim, model=Model.V5, allow_writes=True, power_limit_w=0.12346)
    with pytest.raises(ValueError, match="rounded"):
        c.set_power_w(0.12346)
    assert not sim.requests


def test_default_read_only_and_no_implicit_state_changes():
    sim, c = controller(writes=False)
    assert not sim.requests
    with pytest.raises(PermissionError):
        c.start()
    with pytest.raises(PermissionError):
        c.stop()
    assert not sim.requests
    assert c.status().laser_state == LaserState.STANDBY
    assert all(r.startswith(b"?") for r in sim.requests)
    before = sim.requests
    c.disconnect()
    c.disconnect()
    assert sim.requests == before
    with pytest.raises(TransportError):
        c.read_power_w()


def test_fault_history_enable_and_key_semantics():
    sim, c = controller()
    c.start()
    assert c.read_laser_state() == LaserState.STANDBY
    sim.set_key(True)
    c.start()
    c.set_power_w(1.5)
    c.set_shutter(open=True)
    assert c.read_power_w() == 1.5
    sim.set_faults(2, 8, 999)
    assert c.read_laser_state() == LaserState.FAULT
    assert not c.read_faults()[-1].known
    sim.set_faults()
    assert c.read_laser_state() == LaserState.FAULT  # no automatic re-enable on fault clearing
    assert len(c.read_faults(history=True)) == 3
    c.start()
    assert c.read_faults(history=True) == ()
    assert c.read_laser_state() == LaserState.ON
    c.stop()
    assert c.read_laser_state() == LaserState.STANDBY


def test_virtual_warmup_without_sleep():
    clock = [100.0]
    sim, c = controller(clock=lambda: clock[0], warmup_s=10)
    c.set_power_w(0.5)
    s = c.status()
    assert s.lbo_servo == ServoState.SEEKING
    assert s.laser_state == LaserState.STANDBY
    assert s.power_w == 0
    assert s.lbo_temp_c == 25
    clock[0] += 10
    sim.set_key(True)
    c.start()
    c.set_shutter(open=True)
    s = c.status()
    assert s.lbo_servo == ServoState.LOCKED
    assert s.power_w == 0.5
    assert s.lbo_temp_c == 148


@pytest.mark.parametrize("model", list(Model))
def test_cold_key_on_reports_lbo_fault_and_needs_explicit_enable_after_warmup(model):
    clock = [0.0]
    sim = SimulatedTransport(model, clock=lambda: clock[0], warmup_s=10)
    with VerdiController(sim, model=model, allow_writes=True) as laser:
        sim.set_key(True)
        assert laser.read_laser_state() == LaserState.FAULT
        assert [fault.code for fault in laser.read_faults()] == [5]
        laser.set_power_w(0.5)
        laser.start()
        laser.set_shutter(open=True)
        cold = laser.status()
        assert cold.laser_state == LaserState.FAULT
        assert not cold.shutter_open
        assert cold.power_w == 0

        clock[0] = 10
        warm = laser.status()
        assert warm.faults == ()
        assert warm.laser_state == LaserState.FAULT
        assert not warm.shutter_open
        assert warm.power_w == 0
        assert [fault.code for fault in laser.read_faults(history=True)] == [5]

        # This conservative simulator latch is not a prediction of firmware
        # auto-resumption. Explicit enable and shutter operations are required.
        laser.start()
        assert laser.read_faults(history=True) == ()
        assert laser.read_laser_state() == LaserState.ON
        assert laser.read_power_w() == 0
        laser.set_shutter(open=True)
        assert laser.read_power_w() == 0.5


def test_standby_overrides_cold_key_without_retriggering_warmup_fault():
    sim = SimulatedTransport(clock=lambda: 0.0, warmup_s=10)
    with VerdiController(sim, model=Model.V5, allow_writes=True) as laser:
        sim.set_key(True)
        assert laser.read_laser_state() == LaserState.FAULT
        laser.stop()
        assert laser.read_laser_state() == LaserState.STANDBY
        assert laser.read_faults() == ()
        assert [fault.code for fault in laser.read_faults(history=True)] == [5]


def test_finishing_warmup_does_not_remove_an_injected_lbo_fault():
    clock = [0.0]
    sim = SimulatedTransport(clock=lambda: clock[0], warmup_s=10)
    with VerdiController(sim, model=Model.V5, allow_writes=True) as laser:
        sim.set_key(True)
        sim.set_faults(5, 999)
        assert [fault.code for fault in laser.read_faults()] == [5, 999]
        clock[0] = 10
        laser.start()
        assert laser.read_laser_state() == LaserState.FAULT
        assert [fault.code for fault in laser.read_faults()] == [5, 999]


def test_explicit_echo_and_reversed_prompt_setting():
    sim, c = controller()
    c.set_echo(enabled=True)
    c.set_prompt(enabled=True)
    assert c.read_power_w() == 0
    c.set_prompt(enabled=False)
    c.set_echo(enabled=False)
    assert c.read_power_w() == 0
    assert b"PROMPT=0\r\n" in sim.requests
    assert b"PROMPT=1\r\n" in sim.requests


@pytest.mark.parametrize("model", list(Model))
def test_every_query_through_simulated_protocol(model):
    _, c = controller(model)
    for query in Query:
        c.read(query)
    assert c.read_diagnostics().software_version.startswith("SIMULATOR")


def test_applied_command_with_lost_acknowledgment_is_not_replayed():
    sim, c = controller()
    sim.set_key(True)
    sim.inject_timeout(after_apply=True)
    with pytest.raises(TransportError):
        c.start()
    with pytest.raises(TransportError):
        c.read_laser_state()
    # Inspect the independent fixture only: production code cannot reuse the failed session.
    assert sim.exchange(b"?L\r\n") == b"1\r\n"
    assert sim.requests.count(b"L=1\r\n") == 1


def test_device_rejection_leaves_complete_session_usable():
    sim = SimulatedTransport()
    with VerdiController(sim, model=Model.V5, allow_writes=True) as c:
        sim.inject(b"RANGE ERROR: P=1.0000\r\n")
        with pytest.raises(DeviceError):
            c.set_power_w(1)
        assert c.read_power_w() == 0


def test_malformed_reply_requires_retiring_the_session():
    sim, c = controller()
    sim.inject(b"nan\r\n")
    with pytest.raises(ProtocolError):
        c.read_power_w()
    with pytest.raises(TransportError):
        c.read_power_w()
    fresh = SimulatedTransport()
    c.disconnect()
    c = VerdiController(fresh)
    c.connect()
    assert fresh.requests == ()
    assert c.read_laser_state() == LaserState.STANDBY


@pytest.mark.parametrize("query", [Query.LASER, Query.BAUDRATE, Query.FAULTS, Query.FAULT_HISTORY])
def test_integer_conversion_limit_invalidates_session(query):
    original_limit = sys.get_int_max_str_digits()
    sim = SimulatedTransport()
    with VerdiController(sim, model=Model.V5) as controller:
        try:
            # Exercise the interpreter guard deterministically, even when the
            # invoking process has disabled or increased its default limit.
            sys.set_int_max_str_digits(640)
            sim.inject(b"9" * 641 + b"\r\n")
            with pytest.raises(ProtocolError, match="conversion limit"):
                controller.read(query)
            before = sim.requests
            with pytest.raises(TransportError):
                controller.read_laser_state()
            assert sim.requests == before
        finally:
            sys.set_int_max_str_digits(original_limit)

        replacement = SimulatedTransport()
        controller.disconnect()
        controller = VerdiController(replacement)
        controller.connect()
        assert replacement.requests == ()
        assert controller.read_power_w() == 0


def test_compound_snapshot_not_interleaved_with_commands():
    sim, c = controller()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: c.status() if n % 2 else c.stop(), range(20)))
    requests = sim.requests
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

    monkeypatch.setattr(example, "VerdiController", FakeController)

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
