# Simulator

`SimulatedVerdi` provides the controller API through an independent, in-memory
protocol fixture. It never imports pySerial, discovers ports or accesses hardware.
It starts with the key OFF, laser in STANDBY, shutter closed, setpoint 0 W and no
faults. Temperatures and servos represent a warm instrument; no warmup, thermal
dynamics, noise, calibration or physical timing is modeled.

```python
from coherent_verdi import SimulatedVerdi

with SimulatedVerdi("V5", allow_writes=True) as laser:
    laser.set_key(True)  # Local fixture control, never an RS-232 command.
    laser.set_power_w(0.5)
    laser.start()
    laser.set_shutter(open=True)
    assert laser.read_power_w() == 0.5
    laser.set_faults(2, 999)  # Preserve unknown positive fault codes.
    assert laser.read_faults() == [2, 999]
```

The fixture supplies all 42 short queries, the six command forms emitted by the
controller, CR/LF framing and echo/prompt layouts. `echo` and `prompt` constructor
options select initial reply formatting. `last_transaction` provides the latest
exchange record, as on the serial controller. Disconnecting does not change fixture state.

Its simple state rules are deliberate test policies:

- Enabling requires the key ON and no active faults. Setting the key ON alone
  does not enable the fixture. Real keyswitch behavior must be checked separately.
- Key OFF, STANDBY or a fault closes the shutter. The shutter only opens while
  the fixture is enabled and the key is ON.
- Power jumps directly to the setpoint with the shutter open. Otherwise it is
  zero. The enabled diode has a synthetic idle current with the shutter closed.
- `set_faults()` controls active faults and accumulates history. Clearing faults
  never enables the fixture; explicit enable clears its history.
- `SYSTEM OK` for no active faults is a simulator convention. The manual only
  specifies this text for history. Physical controllers require independently
  verified `active_fault_clear_reply` configuration.

Temperatures, hours, currents and other numerical replies are constants or simple
fixture values. They establish no physical performance or calibration claim.
Malformed replies, timeouts, partial writes and queued bytes are exercised by
test doubles in `tests/`, outside the installed package. They use the real serial
transaction path without opening physical ports.
