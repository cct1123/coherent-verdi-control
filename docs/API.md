# Python API

The package exports `VerdiController`, `SimulatedVerdi`, `VerdiError` and `DeviceError`.

```text
VerdiController(port, *, model="V5", baudrate=19200, timeout_s=1.0,
                allow_writes=False, power_limit_w=None, active_fault_clear_reply=None)
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
| `connect()` / `disconnect()` | Open / release the port; neither sends instructions |
| `read("?P")` | One of 42 queries, including PRINT/? long-name aliases; float, integer, string or fault-code list |
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
| `command(instruction)` | One Table 5-3 long/short command, using `=` or `:`, through the typed validation paths |

For example, `read("PRINT LIGHT")` and `read("?LIGHT")` both transmit `?P`.
`command("LBO HEATER:1")` transmits `LBOH=1`. `POWER`/`LIGHT`, `>=n`,
bare `LBOOPT`, and section 5's `SERIAL BAUDRATE=n` spelling are supported.
Inputs use uppercase ASCII without terminators; every exchange remains one
CR/LF-terminated instruction. Unknown names, batching and injected controls fail
before transmission. Power aliases enforce `power_limit_w` as typed setters do.

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

## Transaction evidence and errors

`last_transaction` returns a copy of the most recent attempted transaction, or None
before the first attempt. Local validation, disabled writes and disconnected/failed
session refusals do not replace it. `capture(query)` returns the same flat record:

| Field | Meaning |
| --- | --- |
| `instruction`, `request`, `response` | Instruction text, encoded request bytes and consumed reply bytes |
| `payload` | Undecorated text when available, otherwise None |
| `timestamp_utc`, `duration_s` | ISO 8601 UTC start and elapsed seconds |
| `port`, `model`, `baudrate`, `timeout_s`, `simulated` | Connection configuration and source |
| `write_attempted`, `pending_bytes` | Whether transmission was attempted; unexpected queued-byte count |
| `outcome`, `error` | Result and diagnostic text, or None for no error |

Outcomes are `ok` for a parsed query, `captured` for raw capture, `acknowledged`
for a successful command, `rejected` for a complete device rejection, `failed` for
a query failure, and `not_sent` or `unknown` for a failed command. `unknown` means
the command may have executed; never automatically replay it. An acknowledgment
establishes protocol acceptance, not physical execution. Partial and late consumed
bytes remain in `response`; queued bytes left unread are reported in `pending_bytes`.

`ValueError` and `PermissionError` reject local inputs before I/O. `VerdiError.transaction`
is an independent transaction record when an exchange failed, otherwise None.
`DeviceError` also retains `instruction` and `response` text for a complete documented
rejection; that aligned session remains usable. Catch `DeviceError` before `VerdiError`.
Other communication or parsing failures retire the session. No method clears the
failure latch, retries commands or purges input. Unexpected/interrupted I/O also
retires the session and propagates. Disconnect remains available; cleanup errors add
a note to an already-active exception.

Applications own logging: inspect `last_transaction` after a successful operation
or `error.transaction` on `VerdiError`. Byte fields need explicit encoding for JSON.

## Commissioning

`capture(query)` accepts the 42 catalogued queries and their PRINT/? aliases only
on a read-only controller.
It enforces ASCII and one CR/LF frame, removes documented echo/prompt decoration,
and permits empty payloads. It bypasses value, state and fault interpretation;
documented device errors still raise `DeviceError`. Capturing an empty or
clear-looking `?F` reply does not establish no faults or configure its clear token.
Normal `read()` and `status()` retain their parsing requirements.

```powershell
verdi --port COM3 --model V5 commission
verdi --port COM3 --model V5 commission --query ?SV --query ?F
```

The default sends one `?SV`. Repeat `--query` for the exact ordered sequence.
Each attempt emits one JSONL record to stdout, with `request_hex`/`response_hex`
replacing the bytes. Commissioning stops at the first rejection, framing or
communication error with exit code 2. It needs no fault-clear configuration;
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
- Operate: power Apply, Start/reset faults, Standby, shutter Open/Close. Start
  and Open require the operator readiness checkbox. Editing a field sends no
  instruction, and refreshes do not replace unsent input.
- Advanced: LBO heater, optimization, FLASH, Coherent chiller ON/temperature,
  panel-lock integer, all menu/button commands, baud, echo and prompt.

`gui --allow-writes --power-limit-w N` enables controls; defaults remain read-only.
The same controller limits apply to browser requests. Write permission, fresh
overview data and readiness acknowledgments are checked on the server. Standby
and shutter-close remain available without fresh telemetry while the connection
is usable. These are protocol controls, not independent emergency interlocks.

Results distinguish `queued`, `running`, `acknowledged`, `verified` (query matches
the request), `mismatch`, `readback_failed`, `rejected`, `failed`, and `cancelled`.
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

The browser watchdog disables writes after 10 s without a server heartbeat.
Server-side permissions and telemetry checks remain authoritative. All controls
share the same connection owner; do not add another acquisition caller or serial
client. Hardware and service-sequence limitations in PROTOCOL.md still apply.

## Package layout

[Developer walkthrough](DEVELOPMENT.md) traces a click to its transaction and
explains how to extend the package.

`catalogue.py` is the shared query catalogue: names, units, reply constraints and
overview acquisition order. `controller.py` contains the hardware API, protocol
parsing, bounded chunked serial I/O, transaction evidence encoding and errors.
`simulator.py` supplies independent in-memory replies through the same API.
`gui.py` contains the optional monitoring cache and Dash view; `gui_session.py`
coordinates its request queue, readback and evidence. `__init__.py` exports
the four public types; `__main__.py` implements read commands and explicitly
enabled writes through `command --allow-writes`. Importing the
package starts no threads and opens no ports. pySerial loads on physical connect;
Dash loads only when creating the app.
