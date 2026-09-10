"""TEST-003/004: API, model policies, explicit writes and simulation scenarios."""

from concurrent.futures import ThreadPoolExecutor

import pytest

from coherent_verdi import (
    ConnectionUnusable,
    ControllerConfig,
    LaserState,
    Model,
    ProtocolError,
    Query,
    ResponseTimeout,
    ServoState,
    SimulatedTransport,
    VerdiController,
    WritesDisabled,
)


def test_applied_command_with_lost_acknowledgment_is_not_replayed():
    sim, c = controller()
    sim.set_key(True)
    sim.inject_timeout(after_apply=True)
    with pytest.raises(ResponseTimeout):
        c.enable_laser()
    assert c.laser_state() == LaserState.ON  # The exception does not mean it stayed off.
    assert sim.requests.count(b"L=1\r\n") == 1


def controller(model=Model.V5, *, writes=True, **kwargs):
    sim = SimulatedTransport(model, **kwargs)
    return sim, VerdiController(sim, ControllerConfig(model, allow_writes=writes))


@pytest.mark.parametrize("model,limit", [(Model.V2, 2), (Model.V5, 5), (Model.V6, 6)])
def test_model_ceiling_and_units(model, limit):
    sim, c = controller(model)
    c.set_power_w(limit)
    assert c.query(Query.SET_POWER) == limit
    with pytest.raises(ValueError):
        c.set_power_w(limit + 0.0001)
    assert c.status().model == model
    assert b"P=" + f"{limit:.4f}".encode() + b"\r\n" in sim.requests


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True, "1.0"])
def test_bad_setpoints_do_not_reach_transport(value):
    sim, c = controller()
    with pytest.raises(ValueError):
        c.set_power_w(value)
    assert not sim.requests


def test_site_ceiling_rounding():
    sim = SimulatedTransport()
    c = VerdiController(sim, ControllerConfig(Model.V5, True, 0.12346))
    with pytest.raises(ValueError, match="rounded"):
        c.set_power_w(0.12346)
    assert not sim.requests


def test_default_read_only_and_no_implicit_state_changes():
    sim, c = controller(writes=False)
    assert not sim.requests
    with pytest.raises(WritesDisabled):
        c.enable_laser()
    with pytest.raises(WritesDisabled):
        c.standby()
    assert not sim.requests
    assert c.status().laser_state == LaserState.STANDBY
    assert all(r.startswith(b"?") for r in sim.requests)
    before = sim.requests
    c.close()
    c.close()
    assert sim.requests == before
    with pytest.raises(ConnectionUnusable):
        c.power_w()


def test_fault_history_enable_and_key_semantics():
    sim, c = controller()
    c.enable_laser()
    assert c.laser_state() == LaserState.STANDBY
    sim.set_key(True)
    c.enable_laser()
    c.set_power_w(1.5)
    c.set_shutter(open=True)
    assert c.power_w() == 1.5
    sim.set_faults(2, 8, 999)
    assert c.laser_state() == LaserState.FAULT
    assert not c.faults()[-1].known
    sim.set_faults()
    assert c.laser_state() == LaserState.FAULT  # no automatic re-enable on fault clearing
    assert len(c.faults(history=True)) == 3
    c.enable_laser()
    assert c.faults(history=True) == ()
    assert c.laser_state() == LaserState.ON
    c.standby()
    assert c.laser_state() == LaserState.STANDBY


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
    c.enable_laser()
    c.set_shutter(open=True)
    s = c.status()
    assert s.lbo_servo == ServoState.LOCKED
    assert s.power_w == 0.5
    assert s.lbo_temp_c == 148


def test_explicit_echo_and_reversed_prompt_setting():
    sim, c = controller()
    c.set_echo(enabled=True)
    c.set_prompt(enabled=True)
    assert c.power_w() == 0
    c.set_prompt(enabled=False)
    c.set_echo(enabled=False)
    assert c.power_w() == 0
    assert b"PROMPT=0\r\n" in sim.requests
    assert b"PROMPT=1\r\n" in sim.requests


@pytest.mark.parametrize("model", list(Model))
def test_every_query_through_simulated_protocol(model):
    _, c = controller(model)
    for query in Query:
        c.query(query)
    assert c.diagnostics().software_version.startswith("SIMULATOR")


def test_malformed_reply_requires_explicit_replacement():
    sim, c = controller()
    sim.inject(b"nan\r\n")
    with pytest.raises(ProtocolError):
        c.power_w()
    with pytest.raises(ConnectionUnusable):
        c.power_w()
    fresh = SimulatedTransport()
    c.replace_transport(fresh)
    assert fresh.requests == ()
    assert c.laser_state() == LaserState.STANDBY


def test_compound_snapshot_not_interleaved_with_commands():
    sim, c = controller()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: c.status() if n % 2 else c.standby(), range(20)))
    requests = sim.requests
    for start in (i for i, request in enumerate(requests) if request == b"?L\r\n"):
        assert all(r.startswith(b"?") for r in requests[start : start + 14])
        assert requests[start + 13] == b"?F\r\n"
