# Simulator contract

`SimulatedTransport` is an in-memory protocol peer. It does not import pySerial,
enumerate ports, open sockets to devices or access a laser. All simulator fixture
operations are local. They are never presented as undocumented RS-232 commands.

The fake defaults to keyswitch OFF, STANDBY, shutter closed, power setpoint 0 W,
no faults and a warm LBO. Pass `warmup_s` and an injected monotonic `clock` to
exercise SEEKING -> LOCKED without sleeping. Default runtime clocks use
`time.monotonic`. Request history is bounded at 4096 entries.

## Documented semantics represented

- All 42 short queries and the six exact command forms emitted by the controller,
  with CR/LF framing, echo/prompt layouts and documented error prefixes.
  Firmware aliases, long names, alternative separators and semicolon termination
  are outside this fixture's scope. A transaction accepts exactly one instruction.
- LASER state codes 0/1/2, keyswitch and shutter flags, servo states and fault codes.
- `L=0` enters STANDBY; `L=1` needs key ON and clears the latched history fixture.
- Key ON while the simulated LBO is cold reports fault 5 (LBO not locked), as
  described on manual p. 4-2. `L=1` cannot put the cold laser into ON. Warmup must
  complete before the nominal key-ON/enable sequence.
- Clearing an injected active fault does not automatically enable the simulated
  laser. The caller must explicitly request it again.
- ECHO settings change the following transaction; PROMPT has reversed 0/1 polarity.
- A closed shutter leaves the enabled diode at an idle current; STANDBY and faults
  turn the diode off (Tables 4-1/4-3 and p. 4-13). Idle/current magnitudes are fixtures.

## Deliberate simulation policies, not firmware predictions

- Temperatures (25 °C diode, 148 °C warm LBO, etc.), operating hours, current
  (1 A at closed-shutter idle, 12 A open),
  undocumented-unit responses and software version are synthetic constants.
- Warmup uses a simple linear LBO temperature interpolation. It is configurable,
  not a claim about the real warmup duration or thermal response.
- The cold-start fault's active condition clears when the virtual LBO becomes
  ready. Its history and FAULT state remain until explicit enable; the shutter
  stays closed. This conservative latch/re-enable sequence is a **fixture policy**,
  not a claim about firmware automatic resumption. Key OFF or `L=0` cancels the
  fixture's warmup-enable attempt; injected faults remain independently controlled
  by `set_faults()`. An injected fault 5 is never cleared by advancing the clock.
- Measured power jumps to the setpoint when enabled, warm, fault-free and the
  simulated shutter is open. Otherwise it is zero. No optical noise, overshoot,
  current calibration, actual idle power or rate dynamics are modeled.
- Fault-triggered shutter closure and zero diode current follow p. 4-13.
  The fake also closes its shutter on key OFF/STANDBY and prevents
  opening unless its key and laser are ON. These conservative fixture policies
  do not establish the device's command acceptance or physical sequencing.
- `SYSTEM OK` for no active `?F` faults is a simulator convention; the manual only
  explicitly specifies it for `?FH`. Physical controllers require a separately
  verified `active_fault_clear_reply` configuration before treating any reply as clear.
- `set_key()` sets a test fixture, not a physical-key action: setting it ON does not
  automatically enable a warm simulator. The real keyswitch can turn the laser ON
  (p. 4-4); do not translate fixture calls into physical actions. The tutorial's
  key-ON/STANDBY starting state requires an operator-approved RS-232 standby override.
- Command power ranges use conservative model ratings, not verified firmware bounds.
  Python-only numeric forms such as underscores/exponents are rejected; the peer
  accepts the decimal spelling used by the controller. No case-folding is assumed.
- The old prompt setting formats a setting command's acknowledgment. Transition
  ordering is a fixture choice because the manual does not explicitly define it.
- Controller sessions latch failure after injected timeouts exactly as with serial.
  Fixture state remains inspectable directly by tests, but applications must retire
  a failed controller. No simulator behavior establishes real resynchronization.

## Failure injection and use

```python
from coherent_verdi import Model, SimulatedTransport, VerdiController

clock = [0.0]
sim = SimulatedTransport(Model.V6, clock=lambda: clock[0], warmup_s=30)
with VerdiController(sim, model=Model.V6) as laser:
    assert laser.status().lbo_servo.name == "SEEKING"
    clock[0] = 30
    assert laser.status().lbo_servo.name == "LOCKED"
    sim.set_faults(2, 999)  # Includes an unknown fault: preserved, not discarded.
    print(laser.read_faults())
    sim.inject_timeout()  # Next request raises TransportError.
```

`inject(b"malformed\r\n")` overrides the next response. `inject(Exception(...))`
raises it. The controller makes malformed semantic replies unusable; retire that controller after cleanup. Tests also use fake pySerial handles beneath the real
serial connection to cover fragmentation, dropped terminators, cable loss, partial
writes, response bounds and concurrency without a shared parser implementation.

`inject_timeout(after_apply=True)` first applies the request to fake state and
then loses its acknowledgment. This demonstrates why a command exception does
not establish that the command had no effect, and why automatic replay is unsafe.
