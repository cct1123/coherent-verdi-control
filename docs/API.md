# Python API

## Byte communication

```python
from coherent_verdi import VerdiController

with VerdiController("COM5", model="V2", baudrate=19200, timeout_s=2) as laser:
    reply = laser.read(b"?SV")
    print(repr(reply))  # e.g. b'6.05'
```

`read`, `write` and `command` require `bytes` instructions without terminators.
A CR/LF terminator is appended, and the complete reply and prompt are consumed.
`read` removes framing and the echoed query, returning payload bytes without
text decoding or numeric conversion. `write` and `command` return unchanged wire
bytes. The complete reply always remains in `last_transaction["response"]`;
`read` also stores its byte payload in `last_transaction["payload"]`.

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

Use `read(b"?P")` for a query and `write(b"P=0.25")` for a setting.
Both delegate to the single `command(bytes)` implementation, which also accepts
both instruction types directly. `read` returns payload bytes; `write` and `command`
return full wire bytes. `get_value("?P")` opts
into query normalization and value parsing. `set_value("P=0.25")` sends a
canonical text instruction and validates the acknowledgment, returning None.
Named query helpers use `get_value()` → `read()` → `command()`; named setting
helpers use `set_value()` → `write()` → `command()`. The transaction lock covers
the exchange, reply validation and evidence updates together. `_interpret_reply()`
only interprets a completed reply; it never sends an instruction.

Device query helpers consistently use `get_...` and device write helpers use
`set_...`. Lifecycle methods (`connect`, `disconnect`, `purge_buffers`) and the
shared `command()` transport retain their names.
The byte methods are `read(query: bytes)` and `write(instruction: bytes)`.
`set_laser_state(1)` enables/resets faults and `set_laser_state(0)` enters standby;
only integer 0/1 can be set, although `get_laser_state()` can also report fault
state 2. One-shot operations use `set_...`, such as `set_flash()` and
`set_lbo_optimization()`.

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
baud. The finite `timeout_s` of 0.001–60 s applies separately to each write/read
stage; consumed replies are bounded at 4096 bytes in total. These are software limits.

Physical clear-fault text must be independently verified before configuring
`active_fault_clear_reply`. There is no device discovery or automatic setup.

| Method | Result / behavior |
| --- | --- |
| `connect(override=True)` / `disconnect()` | Open and return `True` / release the port; neither sends instructions; failures raise |
| `purge_buffers()` | Purge TX, then RX, while holding the transaction lock |
| `read(b"?P")` | Payload bytes after removing echo, CR/LF and prompt; full wire reply retained in transaction evidence |
| `write(b"S=0")` | Canonical byte command; complete acknowledgment and prompt as bytes |
| `get_value("?P")` | One of 42 queries, including PRINT/? long-name aliases; float, integer, string, bytes or fault-code list |
| `set_value("P=0.25")` | Canonical text command through `write()`; validate acknowledgment and return None; device rejections raise `DeviceError` |
| `get_capture("?F")` | Read-only exchange; transaction record without interpreting values or faults |
| `get_power_w()` | Measured-power report in W |
| `get_laser_state()` | Integer: 0 standby, 1 on, 2 fault |
| `get_faults(history=False)` | Fresh list of positive fault codes, including unknown codes |
| `get_diagnostics()` | Software version, head/power-supply/diode hours and fault history |
| `get_status()` | Dictionary from 14 sequential queries; fields below |
| `set_power_w(watts)` | Four-decimal light-regulation setpoint |
| `set_laser_state(1)` / `set_laser_state(0)` | `L=1` enable/reset faults/clear history / `L=0` standby override |
| `set_shutter(open=bool)` | Safety-shutter operation; never periodic modulation |
| `set_echo(enabled=bool)` | Explicit `E=0/1` |
| `set_prompt(enabled=bool)` | `PROMPT=0` enables; `PROMPT=1` disables |
| `set_baudrate(baudrate)` | `B=n`, then host baud change after acknowledgment at the old rate |
| `set_chiller_on()` | `CHILLER=ON`, Coherent chiller part 1037271 only |
| `set_chiller_temperature_c(celsius)` | Finite temperature rounded to one decimal; physical range unspecified |
| `set_exit_screen()` / `set_knob_down()` | `EXIT=1` / `KNOBDN=1` front-panel buttons |
| `set_flash()` | `FL=1`, flash below lasing threshold for etalon recentering |
| `set_lbo_heater(enabled=bool)` | `LBOH=0/1`, cool down / heat |
| `set_lbo_optimization()` | `LBOOPT=1`, initiate optimization without waiting for completion |
| `set_front_panel_lock(value)` | `LFP=n`, integer operand; manual does not define valid values/unlock mapping |
| `set_menu_down()` / `set_menu_select()` / `set_menu_up()` | `MENUDN=1` / `SELECT=1` / `MENUUP=1` |

For example, `get_value("PRINT LIGHT")` and `get_value("?LIGHT")` both transmit `?P`.
Text queries such as `?SV` return a string for printable ASCII or the undecoded
payload as `bytes` for non-ASCII data. No cp1252 or other encoding is guessed.
Numeric, code and fault queries still require valid typed values. To inspect a
reply without interpreting its value, use `laser.get_capture("?SV")["payload"]`;
capture payloads are always bytes. The complete wire reply remains in `response`.

Byte settings use canonical short names and `=` (for example, `write(b"LBOH=1")`).
They do not normalize text aliases.

`controller.COMMAND_INFO` is the write-command counterpart to `QUERY_INFO`.
It maps canonical names without `=` (such as `"P"` and `"LBOH"`) to `Command`
records containing the manual `name`, `unit`, operand-validation `kind` and
binary operand `labels`. `write()` and `command()` use this catalogue for write
validation. Labels are indexed by operand 0/1; `PROMPT` has `("ON", "OFF")`.
Button commands require `1`; chiller commands accept `ON` or a finite decimal.
An empty labels tuple does not establish a valid range for `LFP`.

```python
from coherent_verdi.controller import COMMAND_INFO

print(COMMAND_INFO["P"].unit)  # W
print(COMMAND_INFO["PROMPT"].labels)  # ('ON', 'OFF')
```

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
after failure. Transaction records do not include connection settings; record those
separately with your experiment metadata.

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
reply = laser.read(b"?SV")
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
processes as an automatic recovery action. Restart notebook kernels after package
updates so every controller uses the current implementation.


`purge_buffers()` aborts/discards queued output and discards received input.
It does not wait for transmission, retry a query or wait for incoming bytes to stop.

## Setting power in standby

Use the [hardware procedure](HARDWARE.md#controlled-writes) and
[set-power notebook](../examples/05_set_power.ipynb) for readiness and operator checks.
This typed-helper example changes only the stored setpoint. Replace all placeholders
with your instrument settings and site-approved values before running:

```python
from coherent_verdi import VerdiController

TARGET_W = float("<TARGET_W>")
CEILING_W = float("<SITE_CEILING_W>")

laser = VerdiController(
    "<PORT>",
    model="V2",
    baudrate=19200,
    allow_writes=True,
    power_limit_w=CEILING_W,
    active_fault_clear_reply="<VERIFIED_CLEAR_TEXT>",
)
print("Serial port open:", laser.connect())
```

After confirming the connection, run the checks and setting separately:

```python
try:
    if laser.get_laser_state() != 0 or laser.get_value("?S") != 0 or laser.get_faults():
        raise RuntimeError("Require standby, shutter closed and no active faults")
    laser.set_power_w(TARGET_W)
    print("Setpoint:", laser.get_value("?SP"), "W")
finally:
    laser.disconnect()
```

The setpoint remains stored. Disconnecting releases communication without changing
laser state. `set_laser_state(1)` enables the laser and clears faults and fault history;
capture them first and complete the physical readiness procedure before enabling.
`set_laser_state(0)` enters standby; full shutdown follows the manual's heater/cooling procedure.

## Transaction evidence and errors

`last_transaction` returns a copy of the most recent attempted transaction, or None
before the first attempt. Local validation, disabled writes and disconnected/failed
session refusals do not replace it. `get_capture(query)` returns the same flat record:

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

`get_capture(query)` accepts the 42 catalogued queries and their PRINT/? aliases only
on a read-only controller.
It enforces one CR/LF frame, removes documented echo/prompt decoration,
and returns a byte payload, including empty, non-ASCII and control bytes.
It bypasses value, state and fault interpretation;
documented device errors still raise `DeviceError`. Capturing an empty or
clear-looking `?F` reply does not establish no faults or configure its clear token.
Normal `get_value()` and `get_status()` retain their parsing requirements.

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

Import `Monitor` from `coherent_verdi.monitor` and `create_app` from
`coherent_verdi.gui`. Construct `Monitor(laser, interval_s=1, history_size=600)`,
then call `poll_once()` from one acquisition caller. It returns `attempted_at`,
`status` or None, and `error` or None.
A `paused: true` or `interrupted: true` return is not added to history; it indicates
that polling is paused/closing or that a write invalidated an incomplete sample.
`snapshot()` returns `model`, `simulated`, `health`, `error`, `status`, `age_s` and
copied `history`. `latest()` returns the same current fields without history.
`power_history(after=0)` returns `(sample_counter, points)`, where each point is
`(attempted_at, measured_power_w, set_power_w)`, with None powers for failures.
Pass a previous counter to retrieve only newer retained points; a new browser
starts at zero. Both copies are bounded, independent of device I/O, and safe to
read from callbacks. Pass `polling=False` to start with automatic reads paused;
explicit queued queries still run. Health is `NO DATA`, `LIVE`, `STALE` or `ERROR`;
age uses a monotonic clock. Rendering does not wait for device I/O.

## GUI integration

`create_app(monitor)` builds a caller-owned Dash view. It opens no connection,
starts no worker and performs no serial I/O from browser callbacks. Call
`monitor.poll_once()` and `monitor.wait(stop_event)` on one acquisition worker.
On shutdown, close queue admission with `monitor.close()`, stop and join that
worker, then disconnect the controller. Closing the queue sends no device commands.

The CLI uses `GuiSession` from `coherent_verdi.gui` for disconnected
startup and connection ownership. `create_app(session.monitor, session=session)`
adds the connection controls; `run_gui(session, app, port)` owns its worker and
local HTTP server. Connect is passive and Start monitoring is separate.

`monitor.controls` holds the shared, bounded action queue and cached query results.
Its `snapshot()` returns JSON-ready action evidence. Writes retain acknowledgment
and readback separately. The queue permits 16 pending requests, one ordinary
write at a time, and a 10-second execution deadline. Standby and shutter-close
have priority and cancel older queued ordinary writes; an active exchange finishes
first. Browser click counters prevent duplicate delivery, including across connection
changes. Connection changes reset history and query/action results through
`monitor.reset(controller)` on the worker.

`monitor.generation` identifies the current connection. Dash submissions include
that value, checked atomically with queue admission, so an older view cannot send
an action to a replacement connection. `create_app` requires a supplied session
to own the same monitor as the view.

The [GUI guide](GUI.md) describes controls, permissions, commissioning and result
states. The [developer walkthrough](DEVELOPMENT.md) explains queue execution,
cache publication and lock ownership.

## Package layout

[Developer walkthrough](DEVELOPMENT.md) traces a click to its transaction and
explains how to extend the package.

| Module | Responsibility |
| --- | --- |
| `controller.py` | Query catalogue, hardware API, byte transactions, parsing and evidence. |
| `simulator.py` | Independent in-memory replies through the controller API. |
| `monitor.py` | Bounded telemetry cache and request queue with acknowledgment/readback evidence. |
| `gui.py` | Dash layout/callbacks, connection lifetime, acquisition worker and local HTTP server. |
| `__main__.py` | CLI reads, raw capture, explicit writes and GUI launch. |

`assets/` contains bundled styles, the heartbeat watchdog and browser-only knob
handlers. `__init__.py` exports the four controller/simulator/error types. Imports
start no threads and open no ports. pySerial loads on hardware connect; Dash loads
only when creating the view. Monitoring and CLI watch do not depend on Dash.
