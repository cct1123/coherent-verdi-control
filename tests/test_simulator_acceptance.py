"""Cold-start faults follow manual pp.4-2 and 5-8; latch policy is explicit."""

import pytest

from coherent_verdi import (
    ControllerConfig,
    LaserState,
    Model,
    SimulatedTransport,
    VerdiController,
)


@pytest.mark.parametrize("model", list(Model))
def test_cold_key_on_reports_lbo_fault_and_needs_explicit_enable_after_warmup(model):
    clock = [0.0]
    sim = SimulatedTransport(model, clock=lambda: clock[0], warmup_s=10)
    with VerdiController(sim, ControllerConfig(model, allow_writes=True)) as laser:
        sim.set_key(True)
        assert laser.laser_state() == LaserState.FAULT
        assert [fault.code for fault in laser.faults()] == [5]
        laser.set_power_w(0.5)
        laser.enable_laser()
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
        assert [fault.code for fault in laser.faults(history=True)] == [5]

        # This conservative simulator latch is not a prediction of firmware
        # auto-resumption. Explicit enable and shutter operations are required.
        laser.enable_laser()
        assert laser.faults(history=True) == ()
        assert laser.laser_state() == LaserState.ON
        assert laser.power_w() == 0
        laser.set_shutter(open=True)
        assert laser.power_w() == 0.5


def test_standby_overrides_cold_key_without_retriggering_warmup_fault():
    sim = SimulatedTransport(clock=lambda: 0.0, warmup_s=10)
    with VerdiController(sim, ControllerConfig(Model.V5, allow_writes=True)) as laser:
        sim.set_key(True)
        assert laser.laser_state() == LaserState.FAULT
        laser.standby()
        assert laser.laser_state() == LaserState.STANDBY
        assert laser.faults() == ()
        assert [fault.code for fault in laser.faults(history=True)] == [5]


def test_finishing_warmup_does_not_remove_an_injected_lbo_fault():
    clock = [0.0]
    sim = SimulatedTransport(clock=lambda: clock[0], warmup_s=10)
    with VerdiController(sim, ControllerConfig(Model.V5, allow_writes=True)) as laser:
        sim.set_key(True)
        sim.set_faults(5, 999)
        assert [fault.code for fault in laser.faults()] == [5, 999]
        clock[0] = 10
        laser.enable_laser()
        assert laser.laser_state() == LaserState.FAULT
        assert [fault.code for fault in laser.faults()] == [5, 999]
