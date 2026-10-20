# Hardware setup and commissioning

The controller implements the RS-232 interface from the supplied
[Coherent Verdi V-2/V-5/V-6 Operator's Manual](../verdi.manual_v5.pdf),
part 0171-750-00 Rev IB, sections 1, 3, 4 and 5. Physical communication, timing,
optical behavior and calibration remain unverified. Use a qualified operator and
the site's laser procedure for setup, emission and shutdown.

## Connection

- Confirm actual model, serial number, firmware, port and front-panel baud.
- Use RS-232, not TTL UART. Verify cable pinout/DCE orientation against Figure 5-1;
  only pins 2, 3 and 5 are used.
- Use 8 data bits, no parity, 1 stop bit and no flow control. Supported baud rates:
  1200, 2400, 4800, 9600, 19200, 38400 and 57600. 19200 is the factory default.
- Keep one connection owner. No port scanning, auto-baud or mode configuration
  is performed by the driver.
- Confirm cooling, interlocks, keyswitch/shutter/laser state, enclosed beam
  path/termination and the physical abort procedure before operating.

## First read

1. Use the default `allow_writes=False`. Connection sends no Verdi instructions.
2. Capture one `?SV` exchange; compare version and framing with the actual
   instrument and manual section 5. Specify the actual model and port:

   ```powershell
   verdi --port COM3 --model V5 --baudrate 19200 commission > identify.jsonl
   ```

   This sends only `?SV` and records raw request/reply bytes as hexadecimal,
   payload, UTC timestamp, duration and configuration. Substitute the baud shown
   on the instrument. No mode-setting commands are sent.
3. Stop on timeout or unexpected framing. Do not recover by probing ports,
   changing echo/prompt modes or repeatedly reconnecting.
4. Read `?L`, `?K`, `?S`, then `?P`, `?SP` and temperatures/readiness individually.
   Compare with the front panel, accounting for display resolution and acquisition
   timing. Define tolerances from specifications and uncertainty before testing.

## Fault-clear reply and full status

The manual specifies `SYSTEM OK` for `?FH`, but does not specify the no-active-fault
`?F` reply. Capture a single raw `?F` exchange through the connection's sole owner
and independently confirm its meaning from instrument state and firmware
documentation. Do not clear faults during this capture. If a query is found to
have side effects on the actual firmware, revise the procedure before issuing it.

```powershell
verdi --port COM3 --model V5 --baudrate 19200 commission --query ?F > active-fault.jsonl
```

`commission` uses the read-only `capture()` API. It validates ASCII and single-line
framing, but leaves values and faults uninterpreted. Empty and unknown payloads
are evidence to inspect; a captured exchange does not establish a healthy laser.
Documented device-error replies are recorded as rejected. It stops on the first
device rejection, framing or communication failure. Use repeated
`--query` options only for the specific sequence you intend to inspect.

Set `active_fault_clear_reply` to the exact verified text in the controller
constructor before using `read_faults()` or `status()`. The default deliberately
rejects unverified clear-looking replies. Empty replies remain unsupported by
normal fault parsing; positive fault codes cannot be configured as clear. The
simulator's `SYSTEM OK` convention does not establish physical compatibility.

After individual reads pass, check complete status and diagnostics. Preserve
unknown fault codes. Record raw/parsed values, units, front-panel observations,
timing and PASS/FAIL/INCONCLUSIVE comparisons. Manual p. 5-4 notes that remote
changes may not immediately refresh the front-panel display.

## Controlled writes

Establish the site's allowed operations, power ceiling and abort conditions before
setting `allow_writes=True`. Model ratings are software ceilings, not site limits.
Stop monitoring and release the read-only controller before opening a write-enabled
controller on the same port. No state or commands are replayed on connection.

1. Verify `stop()` / `?L` gives standby under the operator's procedure.
2. With shutter closed and no active faults, set one conservative site-approved
   power and compare `?SP` with the request and front panel. Record quantization;
   the setpoint remains stored. No automatic ramp or reset is performed.
3. Before `start()`, complete LBO warmup and verify key/standby configuration and
   LOCKED diode, LBO, etalon and vanadate temperature servos (manual pp. 4-2–4-3).
   The keyswitch itself can enable emission; its operation belongs to the operator.
   Confirm the shutter is closed. Capture fault history first: `L=1` resets it.
   Enable once and verify actual state and faults; do not repeatedly enable a faulted laser.
4. With the beam path cleared for emission, perform one shutter open/close cycle,
   verify `?S` and observe physical behavior. Do not use the safety shutter for
   modulation. Closed-shutter `?P` and reopening dynamics require observation;
   the simulator's zero reading is synthetic (manual Table 4-3, p. 4-9).
5. Use a suitable calibrated optical reference if accuracy is required. Define
   setpoints, settling conditions, tolerances and uncertainty before measurement;
   setpoint readback alone is not optical calibration.

Service-menu, heater, chiller, optimization, calibration and baud-rate writes are
outside the controller's public operational API.

## Monitoring and communication failure

Choose polling cadence and transaction timeout from observed latency. `status()`
is 14 sequential queries, not simultaneous acquisition. Record sample duration,
failed samples, drift and dashboard staleness over the required run duration.
Global CLI `--trace` writes transaction JSONL to stderr, separately from normal
command output. Python applications can pass `trace=callback` to record the same
raw evidence; see [API.md](API.md#commissioning-and-tracing).

Test communication loss only after the operator establishes a safe condition.
Verify error visibility and absence of retries, replay or auto-enable. A lost
acknowledgment means a write's outcome is unknown. A failed controller cannot be
reused. Closing/reopening alone does not prove delayed untagged replies have
cleared: establish a firmware-appropriate resynchronization procedure first.
The driver rejects bytes already queued before transmission or after a complete
reply and latches the session without purging. This detects available extra data;
it cannot guarantee alignment against arbitrarily delayed replies or bytes still
buffered by the OS/adapter. No quiet-time guarantee is implied.
Do not deliberately create interlock or other hazardous faults for software tests.

## Abort and shutdown

On unexpected behavior, stop commands and use the physical abort procedure.
If communication is trustworthy, the operator can explicitly close the shutter,
enter standby and verify both. Stop acquisition before disconnecting.
`disconnect()` only releases the port; standby leaves temperature servos powered.

Follow the manual's complete shutdown procedure (p. 4-5): retain AC during LBO
cooldown, wait until LBO temperature is below 40 °C before switching AC off,
then stop the chiller. Do not power-cycle as a serial-recovery shortcut.

Keep the tested software version, instrument configuration, raw evidence and
calibration references with your experiment records. Treat inconclusive checks
as unverified; simulator results do not establish physical readiness.
