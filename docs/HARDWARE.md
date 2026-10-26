# Hardware setup and commissioning

The controller implements the RS-232 interface from the supplied
[Coherent Verdi V-2/V-5/V-6 Operator's Manual](../verdi.manual_v5.pdf),
part 0171-750-00 Rev IB, sections 1, 3, 4 and 5. Physical communication, timing,
optical behavior and calibration remain unverified. Use a qualified operator and
the site's laser procedure for setup, emission and shutdown.

## Connection

- Confirm actual model, serial number, firmware, port and front-panel baud.
  [Lesson 0](../examples/00_device_discovery.ipynb) identifies the port from the
  operating system's device list without opening any port.
- Use RS-232, not TTL UART. Verify cable pinout/DCE orientation against Figure 5-1;
  only pins 2, 3 and 5 are used.
- Use 8 data bits, no parity, 1 stop bit and no flow control. Supported baud rates:
  1200, 2400, 4800, 9600, 19200, 38400 and 57600. 19200 is the factory default.
- Keep one connection owner. No port scanning, auto-baud or mode configuration
  is performed by the driver.
- Confirm cooling, interlocks, keyswitch/shutter/laser state, enclosed beam
  path/termination and the physical abort procedure before operating.

## First read

From the repository root, install the project environment with `uv sync` (see
[installation](../README.md#install)), then run the CLI through `uv run`:

```powershell
uv sync
uv run verdi --help
```

No virtual-environment activation is needed, including from a Conda `(base)`
prompt. If PowerShell reports that `verdi` is not recognized, use `uv run verdi`
instead of bare `verdi`. Specify the model with `--model V2`, `--model V5` or
`--model V6`; a bare model name is not a positional argument.

1. Use the default `allow_writes=False`. Connection sends no Verdi instructions.
2. Capture one `?SV` exchange; compare version and framing with the actual
   instrument and manual section 5. Specify the actual model and port:

   ```powershell
   uv run verdi --port COM5 --model V2 --baudrate 19200 commission > identify.jsonl
   ```

   This sends only `?SV` and records raw request/reply bytes as hexadecimal,
   payload and outcome. Substitute the baud shown
   on the instrument. No mode-setting commands are sent.
3. Stop on timeout or unexpected framing. Do not recover by probing ports,
   changing echo/prompt modes or repeatedly reconnecting.
4. Read `?L`, `?K`, `?S`, then `?P`, `?SP` and temperatures/readiness individually.
   Compare with the front panel, accounting for display resolution and acquisition
   timing. Define tolerances from specifications and uncertainty before testing.

### Joined queries in a rejection

A 2026-10-23 capture returned `?SV Query Error:?K?SV` followed by CR/LF.
The echoed current query is `?SV`, while the rejected text joins `?K` and `?SV`.
This is evidence of a request/reply alignment problem; it is consistent with an
unfinished device-side query or a lost terminator, but does not identify the cause.
It is entirely ASCII and therefore cannot itself explain a non-ASCII decode error.

Preserve the complete transaction (especially `request` and `response`), stop
polling and release the connection. Confirm the single connection owner and
the front-panel baud. Establish the firmware-appropriate parser resynchronization
procedure with the operator before sending another query. A host RX/TX purge
cannot clear an instruction already received by the laser. Do not automatically
send a delimiter to clear unknown pending text: it could complete that instruction.

## Fault-clear reply and full status

The manual specifies `SYSTEM OK` for `?FH`, but does not specify the no-active-fault
`?F` reply. Capture a single raw `?F` exchange through the connection's sole owner
and independently confirm its meaning from instrument state and firmware
documentation. Do not clear faults during this capture. If a query is found to
have side effects on the actual firmware, revise the procedure before issuing it.

```powershell
uv run verdi --port COM5 --model V2 --baudrate 19200 commission --query ?F > active-fault.jsonl
```

`commission` uses the read-only `capture()` API. It validates single-line
framing and preserves byte payloads, including non-ASCII data, without guessing
an encoding. It leaves values and faults uninterpreted. Empty and unknown payloads
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

The API also exposes all documented service/front-panel commands: LBO heater,
chiller, optimization, FLASH, panel locking, menu buttons and baud changes. These
are explicit writes; the sequence above does not validate their physical behavior.
Use the manual's procedure for each operation. Chiller temperature limits and
panel-lock operand meanings are unspecified in this manual. Baud changes expect
an acknowledgment at the old rate before host reconfiguration; transition timing
must be verified on the actual firmware. A failed change retires the session and
must not be replayed. See [command coverage and limits](PROTOCOL.md#complete-table-5-3-command-coverage).
No undocumented calibration or temperature-tuning commands are added.

## Monitoring and communication failure

Choose polling cadence and transaction timeout from observed latency. `status()`
is 14 sequential queries, not simultaneous acquisition. Record sample duration,
failed samples, drift and dashboard staleness over the required run duration.
Python applications can record `last_transaction` after each operation and
`VerdiError.transaction` on exchange failure. Commissioning emits the same wire
evidence as JSONL; see [API.md](API.md#transaction-evidence-and-errors).

Test communication loss only after the operator establishes a safe condition.
Verify error visibility and absence of retries, replay or auto-enable. A lost
acknowledgment means a write's outcome is unknown. A failed controller cannot be
reused. Closing/reopening alone does not prove delayed untagged replies have
cleared: establish a firmware-appropriate resynchronization procedure first.
The driver consumes the CR/LF reply and then one exact terminal prompt (`Verdi>`
or the configured model's `Verdi V-N>`). It does not poll for queued bytes before
transmission. Keep one serial owner and retain the received bytes as evidence;
there is no guarantee against stale or arbitrarily delayed replies buffered by
the instrument, OS or adapter. No quiet-time guarantee is implied.
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
