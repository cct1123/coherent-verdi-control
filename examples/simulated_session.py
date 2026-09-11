"""Run with python examples/simulated_session.py; never touches physical hardware."""

from coherent_verdi import (
    Model,
    SimulatedTransport,
    VerdiController,
)
from coherent_verdi.monitor import Monitor, to_json

sim = SimulatedTransport(Model.V5)
sim.set_key(True)  # Fixture configuration, not an RS-232 command.
with VerdiController(sim, model=Model.V5, allow_writes=True) as laser:
    laser.set_power_w(0.5)
    laser.start()  # Explicit, even in this simulated example.
    laser.set_shutter(open=True)
    service = Monitor(laser, history_size=5)
    print(to_json(service.poll_once()))
    laser.set_shutter(open=False)
    laser.stop()
