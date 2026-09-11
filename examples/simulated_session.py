"""Run with python examples/simulated_session.py; no physical hardware is accessed."""

import json

from coherent_verdi import SimulatedVerdi

with SimulatedVerdi(allow_writes=True, power_limit_w=0.5) as laser:
    laser.set_key(True)  # Simulator fixture only; hardware keyswitches are physical.
    laser.set_power_w(0.5)
    laser.start()
    laser.set_shutter(open=True)
    print(json.dumps(laser.status(), indent=2, allow_nan=False))
    # Normal completion only. On uncertain I/O, stop commands and use the site abort procedure.
    laser.set_shutter(open=False)
    laser.stop()
