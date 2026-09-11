# Later physical validation — not authorized in the current phase

Status: **UNTESTED**. This is a review procedure, not a script to run automatically.
No serial port has been discovered or opened during software development.

Use the supplied [operator manual](verdi.manual_v5.pdf), part 0171-750-00 Rev IB,
particularly sections 1, 3, 4 and 5. This software does not replace the hardware
interlocks, laser safety program or a qualified operator's instructions.

## Candidate review and authorization

1. Review [the engineering report](outputs/REPORT.md), current STATE.md,
   [protocol uncertainties](docs/PROTOCOL.md#uncertainty-register), tests and the
   source fingerprint in `records/validation.json`. Approve a specific candidate.
2. Record the human approval, date, operator, actual laser model and serial number,
   software/firmware version, host/adapter/driver, intended port, front-panel baud
   setting and allowed operations in a new evidence record. Do not discover
   candidate ports by opening them. Have the operator identify the intended link.
3. Begin with **read-only authorization only**. Determine a site-approved beam
   configuration and operating envelope separately before any controlled write.
   General permission to connect does not authorize laser enable or shutter open.
4. Confirm installation, cooling, applicable interlocks and an approved enclosed
   beam path/beam termination according to the manual and local procedures. Record
   initial keyswitch, shutter, laser and front-panel state; do not infer them from
   stale software or previous sessions. Do not intentionally create hazardous faults.

## Stage 1 — passive connection and read-only validation

TEST-010A. Expected: connection sends **no Verdi instructions**. Explicitly selected
native serial port, 8N1, no flow control; the selected baud rate matches the front
panel, with 19200 only the documented factory default. Review cable pinout/DCE
orientation from Figure 5-1. No auto-baud, enumeration, buffer purge or echo/prompt
configuration. Call `VerdiController(port, model=model, baudrate=baudrate).connect()`
only after recorded authorization; explicit connect is the hardware entry point. Keep `allow_writes=False`.

TEST-010B. Issue **one `?SV\r\n` query**. Capture transmitted/received bytes and
timestamps without modifying device state. Compare CR/LF, prompt/echo layout and
version with section 5 and the front panel. Stop on an unexpected reply or timeout;
do not send `L=1`, mode-setting commands, or repeated discovery probes to recover.

TEST-010C. After the first framing test passes, issue these sequentially with
documented CR/LF handshaking, recording raw bytes and parsed values:

| Query group | Exact short queries | Compare / expected representation |
| --- | --- | --- |
| State | `?L`, `?K`, `?S` | 0/1/2 laser; 0/1 key/shutter; compare front panel |
| Power | `?P`, `?SP` | finite decimal W; record closed-shutter reporting semantics |
| Current/diode | `?C`, `?D1C`, `?D1T`, `?D1HST` | A and °C; compare front panel |
| Head temperatures | `?BT`, `?LBOT`, `?ET`, `?VT` | °C; compare front panel |
| Servos | `?D1SS`, `?LBOSS`, `?ESS`, `?VSS`, `?LRS` | documented state codes |
| Hours | `?D1H`, `?HH`, `?PSH` | nonnegative hours |
| Faults | `?F`, `?FH` | preserve raw clear/fault responses and unknown codes |

Record the actual no-active-fault `?F` reply and independently verify its meaning
against the operator's observed state/firmware documentation before setting
`active_fault_clear_reply` to that exact text. `SYSTEM OK` is
specified only for history. A default physical controller deliberately rejects an
unverified clear-looking response. For this one approved framing capture, use one
owner of the serial transport to record the single `?F` exchange before typed
status sampling; do not introduce a concurrent raw-reader/controller pair.
An empty clear reply needs a separately reviewed parser change. Do not clear faults
as part of reading them. If the manual or operator's firmware documentation identifies a side
effect, revise the read procedure before issuing the affected query.

For comparisons, record front-panel resolution, time separation and an agreed
tolerance based on the instrument's specification and measurement uncertainty;
do not invent acceptance tolerances. Record each result PASS/FAIL/INCONCLUSIVE.
Refresh the front panel using its approved controls if needed; p. 5-4 notes that
remote changes may not immediately refresh displayed values.

## Stage 2 — separately authorized controlled writes

Only start after Stage 1 passes and an operator approves exact write scope,
conditions, maximum power and abort procedure for this candidate and device.
Create a fresh controller configuration with `allow_writes=True` and the approved
site ceiling. A model's 2/5/6 W software ceiling is not a site safety limit.
Stop read-only acquisition and disconnect its controller before transferring
connection ownership to a new controller; never open a second owner on the same
link. This transition must not send automatic mode changes or replay prior writes.

1. TEST-010D: under approved conditions issue `L=0`, then read `?L` and verify
   STANDBY. Confirm expected physical/front-panel state. Keep heater/cooling
   behavior under the manual's procedure; communication close is not shutdown.
2. TEST-010E: apply an operator-approved conservative `P=nn.nnnn` setpoint;
   read `?SP` and record quantization and front-panel comparison. No automatic
   ramp sequence is supplied. Do not infer the firmware's full range from ratings.
3. TEST-010F: obtain specific approval for **LASER ON** with key ON and beam path
   conditions confirmed by the operator. **Complete LBO warmup first** and confirm
   LOCKED diode, LBO, etalon and vanadate temperature servos/front-panel readiness
   as described on manual pp. 4-2–4-3; the diode
   cannot turn on during warmup. Verify the safety shutter is closed before enable.
   Capture fault history first, because `L=1` resets faults/history. Issue the
   single authorized enable, then verify actual state, remaining faults and
   measured power; do not repeatedly re-enable a faulted device.
4. TEST-010G: with specific beam-path approval, perform a single controlled
   shutter operation (`S=1` open, `S=0` close), read `?S`, and confirm physical state.
   Treat the head shutter as a
   safety shutter; never cycle it for experimental modulation. Validate its
   closed-state `?P` semantics and reopening behavior against Table 4-3, p. 4-9.

No service menu, chiller, LBO heater/optimization, front-panel locking, calibration
or baud-rate write is within this procedure's default scope.

## Recovery, endurance and evidence

- TEST-010H: after approved nominal behavior, monitor extended telemetry at a
  rate justified by measured reply latency. Record complete/failed samples,
  duration, drift, history bounds and dashboard staleness. The status sample
  comprises 14 sequential queries and is not a simultaneous measurement.
- Validate a communication-loss scenario only when the operator has first placed
  the system in an approved condition. No fault-generating physical scenario is
  required. Confirm timeout reporting and **absence of command replay or auto-enable**.
- A lost acknowledgment means the command outcome is unknown. Verify physical
  state using the operator's procedure. A timed-out connection is unusable; merely
  closing/reopening is not proof that delayed untagged bytes have cleared. Prepare
  and approve the actual resynchronization method using the observed firmware;
  there is no undocumented reset command in the driver.
- Capture sanitized raw replies as regression fixtures, fix software defects,
  rerun `python scripts/validate.py`, and repeat affected physical checks. Scope
  changes affecting reviewed safety assumptions need renewed review.
- Archive candidate hashes, environment versions, observed data, uncertainty,
  screenshots where useful, operator identity and calibration references. Report
  calibration as unverified unless measured with a suitable traceable reference.

Use one evidence row per operation, including failed and inconclusive attempts:

| Field | Required record |
| --- | --- |
| Identity | Candidate/source hash, test ID, operator, approval scope, model and serial number |
| Exchange | Exact transmitted/received bytes, UTC time, monotonic duration, timeout and baud settings |
| Comparison | Parsed value and unit, front-panel/reference observation and its timestamp |
| Acceptance | Agreed tolerance and its specification/uncertainty basis; PASS, FAIL or INCONCLUSIVE |
| Follow-up | Unexpected behavior, captured fixture, corrective action and any renewed approval |

## Abort and shutdown

On unexpected behavior, stop issuing further software commands and involve the
operator. Use the established physical safety procedure; software communication
may already be unavailable. If communication is trustworthy and an explicit
shutdown scope applies, the operator may command shutter closed and STANDBY and
verify them. Stop telemetry before releasing the controller. `disconnect()` only
closes the port. Follow the manual's LBO cool-down and complete-shutdown procedure
(p. 4-5); do not cut AC or power-cycle as a communication-recovery shortcut.
For complete shutdown, that procedure retains AC through LBO cooldown and waits
until LBO temperature is below 40 °C before switching AC off, then stops the chiller.
Standby leaves temperature servos powered. The approximately 30-second emission
warning (p. 1-3) and 30-minute cold-start stabilization are hardware behavior to
verify, not timing guarantees supplied by this software. Fault code 1 has conflicting
manual labels; record the device-specific meaning without deliberately inducing it.

Physical acceptance remains UNTESTED until these observations are recorded. A
software/simulator PASS does not establish hardware safety or release readiness.
