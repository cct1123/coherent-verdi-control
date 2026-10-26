# Python API

## Byte communication

```python
with VerdiController("COM5", model="V2", baudrate=19200, timeout_s=2) as laser:
    reply = laser.get(b"?SV")
    print(repr(reply))  # e.g. b'6.05'
```

`get`, `set` and `command` require `bytes` instructions without terminators.
A CR/LF terminator is appended, and the complete reply and prompt are consumed.
`get` removes framing and the echoed query, returning payload bytes without
text decoding or numeric conversion. `set` and `command` return unchanged wire
bytes. The complete reply always remains in `last_transaction["response"]`;
`get` also stores its byte payload in `last_transaction["payload"]`.

With the default `prompt_enabled=True`, completion means a CR/LF reply followed
by the exact `Verdi>` or selected model's `Verdi V-N>` prompt, even if the prompt
arrives after the RX queue becomes empty. The lock covers the entire exchange.
Set `prompt_enabled=False` only when the instrument prompt is already disabled;
then CR/LF completes a reply. Opening does not change instrument settings.
Explicit prompt commands update the expected framing for subsequent requests.

Canonical byte writes use `NAME=value`, enforce write permission and the power
ceiling, and preserve the supplied instruction. Use `set_baudrate()` for baud
changes so the device and host are reconfigured together. Timeouts retain partial
bytes and stop the session without replay. Raw device error replies remain bytes
for the caller to inspect.

Use `get(b"?P")` for a query and `set(b"P=0.25")` for a setting.
Both delegate to the single `command(bytes)` implementation, which also accepts
both instruction types directly. `get` returns payload bytes; `set` and `command`
return full wire bytes. `get_value("?P")` opts
into query normalization and value parsing; named helpers opt into typed settings.
The old `read`, `write`, `command_text` and `_command` methods are removed.

## Typed helpers and connection settings

The package exports `VerdiController`, `SimulatedVerdi`, `VerdiError` and `DeviceError`.

```text
VerdiController(port, *, model="V5", baudrate=19200, timeout_s=1.0,
                allow_writes=False, power_limit_w=None, active_fault_clear_reply=None,
                prompt_enabled=True)
SimulatedVerdi(model="V5", *, allow_writes=False, power_limit_w=None,
               echo=False, prompt=False)
```

Select the actual model: `"V2"`, `"V5"` or `"V6"`. Model ratings provide default
software ceilings of 2/5/6 W. An explicit ceiling must be finite, nonnegative and
no larger; neither establishes a safe site limit. Boolean arguments require booleans.
Serial settings are 8N1 with no flow control and 1200/2400/4800/9600/19200/38400/57600
baud. The finite `timeout_s` of 0.001–60 s covers the entire transaction, including
the write; replies are bounded at 4096 bytes. These are software limits.

Physical clear-fault text must be independently verified before configuring
`active_fault_clear_reply`. There is no device discovery or automatic setup.

| Method | Result / behavior |
| --- | --- |
| `connect(override=True)` / `disconnect()` | Open and return `True` / release the port; neither sends instructions; failures raise |
| `purge_buffers()` | Purge TX, then RX, while holding the transaction lock |
| `get(b"?P")` | Payload bytes after removing echo, CR/LF and prompt; full wire reply retained in transaction evidence |
| `set(b"S=0")` | Canonical byte command; complete acknowledgment and prompt as bytes |
| `get_value("?P")` | One of 42 queries, including PRINT/? long-name aliases; float, integer, string, bytes or fault-code list |
| `capture("?F")` | Read-only exchange; transaction record without interpreting values or faults |
| `read_power_w()` | Measured-power report in W |
| `read_laser_state()` | Integer: 0 standby, 1 on, 2 fault |
| `read_faults(history=False)` | Fresh list of positive fault codes, including unknown codes |
| `read_diagnostics()` | Software version, head/power-supply/diode hours and fault history |
| `status()` | Dictionary from 14 sequential queries; fields below |
| `set_power_w(watts)` | Four-decimal light-regulation setpoint |
| `start()` / `stop()` | `L=1` enable/reset faults/clear history / `L=0` standby override |
| `set_shutter(open=bool)` | Safety-shutter operation; never periodic modulation |
| `set_echo(enabled=bool)` | Explicit `E=0/1` |
| `set_prompt(enabled=bool)` | `PROMPT=0` enables; `PROMPT=1` disables |
| `set_baudrate(baudrate)` | `B=n`, then host baud change after acknowledgment at the old rate |
| `chiller_on()` | `CHILLER=ON`, Coherent chiller part 1037271 only |
| `set_chiller_temperature_c(celsius)` | Finite temperature rounded to one decimal; physical range unspecified |
| `exit_screen()` / `knob_down()` | `EXIT=1` / `KNOBDN=1` front-panel buttons |
| `flash()` | `FL=1`, flash below lasing threshold for etalon recentering |
| `set_lbo_heater(enabled=bool)` | `LBOH=0/1`, cool down / heat |
| `optimize_lbo()` | `LBOOPT=1`, initiate optimization without waiting for completion |
| `set_front_panel_lock(value)` | `LFP=n`, integer operand; manual does not define valid values/unlock mapping |
| `menu_down()` / `menu_select()` / `menu_up()` | `MENUDN=1` / `SELECT=1` / `MENUUP=1` |

For example, `get_value("PRINT LIGHT")` and `get_value("?LIGHT")` both transmit `?P`.
Text queries such as `?SV` return a string for printable ASCII or the undecoded
payload as `bytes` for non-ASCII data. No cp1252 or other encoding is guessed.
Numeric, code and fault queries still require valid typed values. To inspect a
reply without interpreting its value, use `laser.capture("?SV")["payload"]`;
capture payloads are always bytes. The complete wire reply remains in `response`.

Byte settings use canonical short names and `=` (for example, `set(b"LBOH=1")`).
They do not normalize text aliases.

All writes require `allow_writes=True`, including service/front-panel commands.
Chiller control accepts only ON or a finite numeric temperature, without inventing
a physical operating range. Panel locking accepts a bounded integer without
assuming an undocumented unlock mapping. Firmware can reject these operands.
These methods do not run a shutdown, optimization or cooling sequence for you.

Baud switching expects the acknowledgment at the original rate before changing
the host setting under the transaction lock. The manual leaves acknowledgment
baud/timing unspecified: physical validation is required. If the device switches
before replying, the timeout retires the session with an unknown outcome. If host
reconfiguration fails after acknowledgment, the session also retires; evidence
retains `outcome="acknowledged"` and the host error. Never replay a baud change
after failure. Exchange records retain the rate used for that exchange.

Status fields are `model`, `simulated`, `sampled_at` (UTC start), `duration_s`,
`laser_state`, `keyswitch_on`, `shutter_open`, `power_w`, `set_power_w`,
`diode_current_a`, `diode_temp_c`, `heatsink_temp_c`, `baseplate_temp_c`, `lbo_temp_c`,
`lbo_servo`, `etalon_temp_c`, `vanadate_temp_c` and `faults`. Temperatures are °C;
servo codes are 1 locked and 2 seeking. A status sample is sequential acquisition,
not a simultaneous measurement. Returned dictionaries and lists are independent copies.

`model` is read-only; `is_simulated` identifies the implementation. Configure through
constructor arguments. `allow_writes` and `power_limit_w` are read-only capability
properties; `failed` exposes the failure latch without waiting for I/O.
`with laser:` connects/disconnects. Share one object between
callers: it serializes transactions and complete status groups. Never create
concurrent owners of one port. Disconnect releases communication without shutting
down the laser. A healthy disconnected controller can reopen; a failed session cannot.

Buffer purges are explicit host operations, available with writes disabled and
after a failed exchange while the connection is still open. They send no Verdi
instructions, keep `last_transaction` intact, and do not clear `failed` or reset
the laser's input parser. A purge error invalidates the session. The simulator
implements them as no-ops because it has no serial queues.

```python
connected = laser.connect()
print("Serial port open:", connected)
```

Inspect the result before running a separate communication cell:

```python
laser.purge_buffers()  # Explicit host queue discard, if intended
reply = laser.get(b"?SV")
print(repr(reply))
```

`True` confirms local port opening, not a reply from the instrument or readiness.
Opening failures raise an exception rather than returning `False`.

`connect(override=True)` (the default) replaces an older `VerdiController` connection
for the same port in this Python process. Replacement waits for the old transaction
lock, closes its handle, then opens the new handle. It sends no instrument commands
and preserves the old transaction record and failure state. `override=False`
refuses replacement. A failed controller itself remains retired: construct a fresh
controller to reconnect. Neither replacement nor reopening proves device synchronization.

Windows will not allow takeover from a raw `serial.Serial` object, another notebook
kernel or another application. Close that owner explicitly. Do not terminate other
processes as an automatic recovery action. Controllers created before loading the
ownership-aware driver are not registered; restart the kernel once after updating.


`purge_buffers()` aborts/discards queued output and discards received input.
It does not wait for transmission, retry a query or wait for incoming bytes to stop.

## Transaction evidence and errors

`last_transaction` returns a copy of the most recent attempted transaction, or None
before the first attempt. Local validation, disabled writes and disconnected/failed
session refusals do not replace it. `capture(query)` returns the same flat record:

| Field | Meaning |
| --- | --- |
| `instruction`, `request`, `response` | Instruction bytes, request bytes and consumed reply bytes |
| `payload` | Undecorated string or bytes when available, otherwise None; capture always uses bytes |
| `outcome`, `error` | Result and diagnostic text, or None for no error |

Raw byte operations use `received`: a complete frame was received, without interpreting acceptance or a device error.
Outcomes for explicit typed helpers are `ok` for a parsed query, `captured` for raw capture, `acknowledged`
for a successful command, `rejected` for a complete device rejection, `failed` for
a query failure, and `unknown` for a failed command. `unknown` means
the command may have executed; never automatically replay it. An acknowledgment
establishes protocol acceptance, not physical execution. Partial consumed bytes
remain in `response`. The record has exactly six fields: `instruction`, `request`,
`response`, `payload`, `outcome` and `error`. Connection metadata and timing are not recorded.

`ValueError` and `PermissionError` reject local inputs before I/O. `VerdiError.transaction`
is an independent transaction record when an exchange failed, otherwise None.
`DeviceError` also retains `instruction` and `response` text for a complete documented
rejection; that aligned session remains usable. Catch `DeviceError` before `VerdiError`.
An explicit `Query Error:` naming a different `?` query raises `VerdiError` and
invalidates the session because request/reply alignment is uncertain.
Other communication or parsing failures retire the session. No method clears the
failure latch or retries commands. Buffer purges are explicit only; the driver
never automatically purges input for recovery. Windows pySerial
purges host RX/TX queues during port opening; this does not reset the device's
input parser. Unexpected/interrupted I/O also
retires the session and propagates. Disconnect remains available; cleanup errors add
a note to an already-active exception.

Applications own logging: inspect `last_transaction` after a successful operation
or `error.transaction` on `VerdiError`. Byte fields need explicit encoding for JSON.

## Commissioning

`capture(query)` accepts the 42 catalogued queries and their PRINT/? aliases only
on a read-only controller.
It enforces one CR/LF frame, removes documented echo/prompt decoration,
and returns a byte payload, including empty, non-ASCII and control bytes.
It bypasses value, state and fault interpretation;
documented device errors still raise `DeviceError`. Capturing an empty or
clear-looking `?F` reply does not establish no faults or configure its clear token.
Normal `get_value()` and `status()` retain their parsing requirements.

```powershell
verdi --port COM3 --model V5 commission
verdi --port COM3 --model V5 commission --query ?SV --query ?F
```

The default sends one `?SV`. Repeat `--query` for the exact ordered sequence.
Each attempt emits one JSONL record to stdout, with `request_hex`/`response_hex`
replacing the bytes. Commissioning stops at the first rejection, framing or
communication error with exit code 2. Byte payloads are also encoded in
`payload_hex`; `payload` contains ASCII text when decodable, otherwise null.
The CLI's ordinary query/diagnostics output and GUI cache represent byte-valued
results as `{"bytes_hex": "..."}`. This preserves bytes without text conversion.
Commissioning needs no fault-clear configuration;
interpreting and verifying captured data remains the operator's responsibility.

## Optional monitoring

Import `Monitor` and `create_app` from `coherent_verdi.gui`. Construct
`Monitor(laser, interval_s=1, history_size=600)`, then call `poll_once()` from one
acquisition caller. It returns `attempted_at`, `status` or None, and `error` or None.
A `paused: true` or `interrupted: true` return is not added to history; it indicates
that polling is paused/closing or that a write invalidated an incomplete sample.
`snapshot()` returns `model`, `simulated`, `health`, `error`, `status`, `age_s` and
copied `history`. `latest()` returns the same current fields without history.
`power_history(after=0)` returns `(sample_counter, points)`, where each point is
`(attempted_at, measured_power_w, set_power_w)`, with None powers for failures.
Pass a previous counter to retrieve only newer retained points; a new browser
starts at zero. Both copies are bounded, independent of device I/O, and safe to
read from callbacks. Health is `NO DATA`, `LIVE`, `STALE` or `ERROR`; age uses a
monotonic clock. Rendering does not wait for device I/O. Use a new monitor for
each session. `create_app(monitor)` builds the
optional Dash view without starting a worker or server. The application owns
scheduling and must finish acquisition before disconnecting.

## GUI control panel

Each `Monitor` constructs one shared `monitor.controls` queue. Continue to
call `monitor.poll_once()` from exactly one acquisition caller: it handles queued
actions and reads the overview one transaction at a time. Browser callbacks only
submit requests or render cached data; creating the app sends nothing. Custom
launchers should use `monitor.wait(stop_event)` between polls (new actions wake
it early). The wait subtracts elapsed acquisition/action time from the interval;
an overview longer than the interval starts its next cycle immediately.
On shutdown, set the stop event, call `monitor.close()`, join the acquisition
caller, then disconnect. Close cancels pending requests and sends no device cleanup commands.

Pause overview and Resume overview submit explicit states, so rapid clicks and
multiple tabs cannot invert a cached polling state accidentally. Overview and
heartbeat refresh once a second. After initial history load, plots append only
new points, keeping at most `history_size`. Action results refresh every 200 ms
while a request is queued/running, then return to the ordinary refresh rate.

The GUI exposes every documented getter and write operation:

- Overview: power/setpoint graph, laser, key/shutter states, current, six
  temperatures, LBO servo and active faults.
- Query selector: all 42 queries with labels, units, acquisition timestamps and
  decoded state codes; diagnostics read version, hours and fault history.
- Capture: raw payload and wire evidence in read-only sessions. Start the CLI
  with `gui --commission` to pause overview polling before the first read.
- Front-panel replica: AC ON (lit while the laser answers serial queries; there
  is no AC-power query), LASER EMISSION (`?L` ON), read-only key switch (`?K`),
  a two-line display synthesized from the overview, MENU UP/DOWN, SELECT and
  EXIT (`MENUUP`, `MENUDN`, `SELECT`, `EXIT`), SHUTTER OPEN, POWER LEVEL 1/2
  and POWER ADJUST. SHUTTER OPEN toggles: it opens only when the browser
  showed CLOSED and the latest live sample agrees, otherwise it closes. The
  knob (drag, wheel or arrow keys; Shift for ×10) edits the target only;
  SET POWER sends it. POWER LEVEL presets live in browser storage and light
  while the reported setpoint matches. Lamps without a live sample are hollow.
- Remote operation: power Apply, Start/reset faults, Standby, shutter
  Open/Close. Start and Open (including the panel's SHUTTER OPEN) require the
  operator readiness switch. Editing a field or turning the knob sends no
  instruction, and refreshes do not replace unsent input.
- Service commands: LBO heater, optimization, FLASH, Coherent chiller ON/temperature,
  panel-lock integer, all menu/button commands, baud, echo and prompt.

`gui --allow-writes --power-limit-w N` enables controls; defaults remain read-only.
The same controller limits apply to browser requests. Write permission, fresh
overview data and readiness acknowledgments are checked on the server. Standby
and shutter-close remain available without fresh telemetry while the connection
is usable. These are protocol controls, not independent emergency interlocks.

Results distinguish `queued`, `running`, `acknowledged`, `verified` (query matches
the request), `mismatch`, `readback_failed`, `rejected`, `failed`, and `cancelled`.
Reads finish as `read`, raw captures as `captured` and polling changes as `applied`.
Writes retain their own acknowledgment evidence independently of subsequent
readback. A local validation failure or complete device rejection is `rejected`;
an adapter exception after transmission is `failed`, retaining an `unknown`
write outcome even if the Python exception is ValueError. Power reads `?SP`,
laser `?L`, shutter `?S`, heater `?LBOH`, baud `?B`.
Other commands have no documented getter; their acceptance does not establish
physical completion. Open Transaction evidence for exact requests/replies and
errors. Query results are last-acquired values, with individual timestamps.

The shared queue holds at most 16 requests, with a 10 s execution deadline and
one ordinary write pending across tabs. Per-browser action sequence numbers
suppress duplicate/old submissions even after result-history eviction. Standby
and shutter-close take priority and cancel older queued ordinary writes; both
stop/close actions are preserved. The active exchange must finish first. A write
between overview reads discards the incomplete sample; the next poll acquires a
fresh complete sample. Only 128 action records and 64 browser registrations are
retained; an expired browser must reload. Transport failures retire the controller
and reject subsequent actions; no recovery, re-enable or command replay occurs.

The browser watchdog disables every write group (Remote operation, front panel
and service commands) after 10 s without a server heartbeat.
Server-side permissions and telemetry checks remain authoritative. All controls
share the same connection owner; do not add another acquisition caller or serial
client. Hardware and service-sequence limitations in PROTOCOL.md still apply.

## Package layout

[Developer walkthrough](DEVELOPMENT.md) traces a click to its transaction and
explains how to extend the package.

`controller.py` contains the query catalogue (names, units, reply constraints,
code labels and overview acquisition order), the hardware API, protocol parsing,
bounded pySerial reads, transaction evidence encoding and errors.
`simulator.py` supplies independent in-memory replies through the same API.
`gui.py` contains the optional monitoring cache, its request queue with readback
and evidence (`ControlSession`), and the Dash view, built with
dash-bootstrap-components. Its `assets/` hold the bundled Bootstrap 5 stylesheet,
`style.css`, the heartbeat watchdog (`watchdog.js`) and the browser-only knob and
display-contrast handlers (`panel.js`). `__init__.py` exports
the four public types; `__main__.py` implements read commands and explicitly
enabled writes through `command --allow-writes`. Importing the
package starts no threads and opens no ports. pySerial loads on physical connect;
Dash loads only when creating the app.
