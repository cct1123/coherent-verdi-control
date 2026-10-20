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
| `read("?P")` | One of 42 short queries; float, integer, string or list of fault codes |
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

Status fields are `model`, `simulated`, `sampled_at` (UTC start), `duration_s`,
`laser_state`, `keyswitch_on`, `shutter_open`, `power_w`, `set_power_w`,
`diode_current_a`, `diode_temp_c`, `heatsink_temp_c`, `baseplate_temp_c`, `lbo_temp_c`,
`lbo_servo`, `etalon_temp_c`, `vanadate_temp_c` and `faults`. Temperatures are °C;
servo codes are 1 locked and 2 seeking. A status sample is sequential acquisition,
not a simultaneous measurement. Returned dictionaries and lists are independent copies.

`model` is read-only; `is_simulated` identifies the implementation. Configure through
constructor arguments. `with laser:` connects/disconnects. Share one object between
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

`capture(query)` accepts the 42 catalogued queries only on a read-only controller.
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
`snapshot()` returns `model`, `simulated`, `health`, `error`, `status`, `age_s` and
copied `history`. Health is `NO DATA`, `LIVE`, `STALE` or `ERROR`; age uses a
monotonic clock. Rendering does not wait for device I/O. Use a new monitor for
each session. `create_app(monitor)` builds the
optional Dash view without starting a worker or server. The application owns
scheduling and must finish acquisition before disconnecting.

## Package layout

`controller.py` contains the hardware API, protocol parsing, serial I/O and errors.
`simulator.py` supplies independent in-memory replies through the same API.
`gui.py` contains the optional monitoring cache and Dash view. `__init__.py` exports
the four public types; `__main__.py` implements the read-only CLI. Importing the
package starts no threads and opens no ports. pySerial loads on physical connect;
Dash loads only when creating the app.
