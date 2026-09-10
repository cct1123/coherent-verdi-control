# Simulator contract

`SimulatedTransport` is an in-memory protocol peer. It does not import pySerial,
enumerate ports, open sockets to devices or access a laser. All simulator fixture
operations are local. They are never presented as undocumented RS-232 commands.

The fake defaults to keyswitch OFF, STANDBY, shutter closed, power setpoint 0 W,
no faults and a warm LBO. Pass `warmup_s` and an injected monotonic `clock` to
exercise SEEKING -> LOCKED without sleeping. Default runtime clocks use
`time.monotonic`. Request history is bounded at 4096 entries.

## Documented semantics represented

- All 42 query spellings, CR/LF replies, echo and prompt forms, error prefixes.
- LASER state codes 0/1/2, keyswitch and shutter flags, servo states and fault codes.
- `L=0` enters STANDBY; `L=1` needs key ON and clears the latched history fixture.
- Clearing an injected active fault does not automatically enable the simulated
  laser. The caller must explicitly request it again.
- ECHO settings change the following transaction; PROMPT has reversed 0/1 polarity.

## Deliberate simulation policies, not firmware predictions

- Temperatures (25 °C diode, 148 °C warm LBO, etc.), operating hours, current,
  undocumented-unit responses and software version are synthetic constants.
- Warmup uses a simple linear LBO temperature interpolation. It is configurable,
  not a claim about the real warmup duration or thermal response.
- Measured power jumps to the setpoint when enabled, warm, fault-free and the
  simulated shutter is open. Otherwise it is zero. No optical noise, overshoot,
  current calibration, actual idle power or rate dynamics are modeled.
- The fake closes its shutter on key OFF, STANDBY or injected faults and prevents
  opening unless its key and laser are ON. These conservative fixture policies
  do not establish the device's command acceptance or physical sequencing.
- `SYSTEM OK` for no active `?F` faults is an unverified compatibility convention;
  the manual only explicitly specifies it for `?FH`.
- The old prompt setting formats a setting command's acknowledgment. Transition
  ordering is a fixture choice because the manual does not explicitly define it.
- A timeout injection can be recovered in the fake because no late bytes exist.
  The serial adapter instead poisons a timed-out session. Do not infer real
  reconnect behavior from the simpler fake.

## Failure injection and use

```python
from coherent_verdi import ControllerConfig, Model, SimulatedTransport, VerdiController

clock = [0.0]
sim = SimulatedTransport(Model.V6, clock=lambda: clock[0], warmup_s=30)
with VerdiController(sim, ControllerConfig(Model.V6)) as laser:
    assert laser.status().lbo_servo.name == "SEEKING"
    clock[0] = 30
    assert laser.status().lbo_servo.name == "LOCKED"
    sim.set_faults(2, 999)  # Includes an unknown fault: preserved, not discarded.
    print(laser.faults())
    sim.inject_timeout()  # Next request raises ResponseTimeout.
```

`inject(b"malformed\r\n")` overrides the next response. `inject(Exception(...))`
raises it. The controller makes malformed semantic replies unusable until an
explicit transport replacement. Tests also use byte-stream fakes below the real
serial adapter to cover fragmentation, dropped terminators, cable loss, partial
writes, response bounds and concurrency without a shared parser implementation.

`inject_timeout(after_apply=True)` first applies the request to fake state and
then loses its acknowledgment. This demonstrates why a command exception does
not establish that the command had no effect, and why automatic replay is unsafe.
