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
    laser.set_laser_state(1)
    laser.set_shutter(open=True)
    assert laser.get_power_w() == 0.5
    laser.set_faults(2, 999)  # Preserve unknown positive fault codes.
    assert laser.get_faults() == [2, 999]
```

The fixture supplies all 42 queries and every Table 5-3 write operation emitted
by the controller, CR/LF framing and echo/prompt layouts. `get_value()` normalizes
long/short query aliases before reaching the fixture; byte `read()`/`write()` calls
preserve the supplied instructions and use canonical short setting commands.
`echo` and `prompt` constructor options select initial reply formatting.
`last_transaction` provides the latest
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
- Baud writes change the fixture's `?B`. The typed `set_baudrate()` helper also
  changes the controller baud setting; raw `write(b"B=9600")` does not change the host.
  The fixture acknowledges at the old rate; it does not establish physical transition timing.
- LBO heater writes change `?LBOH`; no cooling/heating, interlock or fault behavior
  is synthesized. LBO optimization and FLASH only record initiation; servo and
  optical transients or completion are not modeled.
- The fixture includes the optional chiller. It records ON and the temperature
  setpoint without modeling a physical temperature range or cooling response.
- Panel-lock writes retain the integer operand without assigning undocumented
  lock/unlock meanings. Menu/button commands record the last action without a
  front-panel UI model. EXIT does not clear the fixture's fault history.

Temperatures, hours, currents and other numerical replies are constants or simple
fixture values. They establish no physical performance or calibration claim.
Malformed replies, timeouts, partial writes and queued bytes are exercised by
test doubles in `tests/`, outside the installed package. They use the real serial
transaction path without opening physical ports.

The [GUI guide](GUI.md) describes starting the simulated dashboard. The saved
V2 reference tests use recorded payloads independently of this simulator; see
[notebook reference tests](DEVELOPMENT.md#notebook-reference-tests).
