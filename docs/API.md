# Python API

The package exports `VerdiController`, `SimulatedVerdi`, `VerdiError` and `DeviceError`.
Constructor signatures:

```text
VerdiController(
    port,  # Explicit native port string; no backend/factory argument
    *, model="V5", baudrate=19200, timeout_s=1.0,
    allow_writes=False, power_limit_w=None, active_fault_clear_reply=None,
    trace=None,
)
SimulatedVerdi(model="V5", *, allow_writes=False, power_limit_w=None,
               clock=time.monotonic, warmup_s=0, echo=False, prompt=False,
               trace=None)
```

Model is `"V2"`, `"V5"` or `"V6"`. The conservative default ceiling is 2/5/6 W;
an explicit ceiling must be finite, nonnegative and no larger. Neither establishes
a safe site limit. Booleans must be actual booleans. Serial settings are 8N1, no
flow control, and 1200/2400/4800/9600/19200/38400/57600 baud. The finite timeout
0.001–60 s covers the entire transaction, including the write; replies are bounded
at 4096 bytes. These are software limits, not measured firmware guarantees.

Physical clear-fault text must be independently verified before configuring
`active_fault_clear_reply`. No physical model discovery or automatic setup exists.

| Method | Result / behavior |
| --- | --- |
| `connect()` / `disconnect()` | Passive open / resource release; neither sends instructions |
| `read("?P")` | One of 42 short queries; float, integer, string or list of fault codes |
| `capture("?F")` | Read-only commissioning exchange; transaction record without interpreting the value or faults |
| `read_power_w()` | Measured-power report in W |
| `read_laser_state()` | Integer: 0 standby, 1 on, 2 fault |
| `read_faults(history=False)` | Fresh `list[int]`; unknown positive codes preserved; boolean selector |
| `read_diagnostics()` | Fresh dictionary: software_version, head_hours, power_supply_hours, diode_hours, fault_history |
| `status()` | Fresh dictionary from 14 sequential queries; fields below |
| `set_power_w(watts)` | Four-decimal light-regulation setpoint; validate input and rounded value |
| `start()` / `stop()` | `L=1` enable/reset faults/clear history / `L=0` standby override |
| `set_shutter(open=bool)` | Explicit safety-shutter operation; never periodic modulation |
| `set_echo(enabled=bool)` | Explicit `E=0/1` |
| `set_prompt(enabled=bool)` | `PROMPT=0` enables; `PROMPT=1` disables |

Status keys: `model`, `simulated`, `sampled_at` (ISO 8601 UTC start), `duration_s`,
`laser_state`, `keyswitch_on`, `shutter_open`, `power_w`, `set_power_w`,
`diode_current_a`, `diode_temp_c`, `heatsink_temp_c`, `baseplate_temp_c`, `lbo_temp_c`,
`lbo_servo`, `etalon_temp_c`, `vanadate_temp_c`, `faults`. Temperatures are °C;
servo values are the manual's integer codes (1 locked, 2 seeking). The timestamp
and duration cover sequential acquisition, not simultaneous measurements.
Changing a returned dictionary/list cannot change the instrument or later results.

`model` is a read-only property; `is_simulated` identifies the implementation.
Configure only through constructor arguments. `with laser:` connects/disconnects.
One object serializes transactions; share it, never create concurrent owners of
one port. Disconnect is not laser shutdown. An acknowledged healthy session can
explicitly reopen; a failed session cannot.

`ValueError` and `PermissionError` reject local inputs/disabled writes before I/O.
`VerdiError` exposes `instruction`, `request` (bytes), `raw_response` (bytes),
`duration_s` and `write_outcome`. The outcome is None for queries; for commands it
is `acknowledged`, `rejected`, `unknown` or `not_sent`. An unknown outcome means
the command may have executed; do not automatically replay it. `DeviceError` also
retains `response`, the existing reply text, for a complete documented rejection;
the session remains usable unless its trace callback also fails. Other `VerdiError`
failures mean disconnected,
uncertain or malformed communication. Retire an uncertain session; no method clears
its failure latch. Interrupted/unexpected I/O errors propagate and also latch failure.
Disconnect remains available; failed cleanup is retryable and adds a note to an
already-active exception. Catch `DeviceError` before `VerdiError` to distinguish them.

## Commissioning and tracing

`capture(query)` is available only when `allow_writes=False` and accepts the same
42 catalogued queries as `read()`. It requires ASCII and one complete CR/LF frame,
removes documented echo/prompt decoration, and allows an empty payload. It bypasses
value, state and fault interpretation; documented device-error replies still raise
`DeviceError` and produce a `rejected` trace record.
An empty or clear-looking `?F` capture therefore does not establish an absence of
faults and does not configure `active_fault_clear_reply`. Normal `read()` and
`status()` retain their existing parsing requirements.

The returned record is a flat dictionary. Passing `trace=callback` delivers the
same record synchronously for each attempted transaction, including failures:

| Field | Meaning |
| --- | --- |
| `instruction`, `request`, `response` | Instruction text, encoded request bytes and received bytes |
| `payload` | Undecorated text when available, otherwise None |
| `timestamp_utc`, `duration_s` | ISO 8601 UTC start and elapsed seconds |
| `port`, `model`, `baudrate`, `timeout_s`, `simulated` | Connection configuration and source |
| `write_attempted`, `pending_bytes` | Whether transmission was attempted; unexpected queued-byte count |
| `outcome`, `error` | Result and diagnostic text, or None for no error |

`outcome` is `ok` for a parsed query, `captured` for a commissioning capture,
`acknowledged` for a successful command, `rejected` for a device rejection,
`failed` for a query failure, and `not_sent` or `unknown` for a failed command.
Do not infer physical execution from `write_attempted` alone.

The callback runs under the transaction lock; keep it short. It cannot issue
device instructions or open/close the connection: these attempts raise
`RuntimeError`. An uncaught callback failure latches the session. Ordinary callback
exceptions annotate a primary transaction error, or raise `VerdiError` while
retaining an already established command outcome. Callback interrupts propagate
when there is no primary transaction error; otherwise that error is preserved
with a note. No transaction is retried. Store the bytes directly or encode them explicitly when
writing JSON.

For CLI commissioning, specify the actual port and model:

```powershell
verdi --port COM3 --model V5 commission
verdi --port COM3 --model V5 commission --query ?SV --query ?F
```

The default is one `?SV` exchange. Repeated `--query` options select the exact
ordered queries. Each attempt emits one JSONL record to stdout, with
`request_hex`/`response_hex` replacing the byte fields. Commissioning stops on the
first device rejection, framing or communication error with exit code 2. It does
not need `--active-fault-clear-reply`; interpreting and verifying the reply remains
the operator's responsibility. Global `--trace` emits the same JSONL format to
stderr for other CLI commands, leaving their usual stdout unchanged.

## Optional monitoring

`from coherent_verdi.gui import Monitor, create_app`. Construct `Monitor(laser,
interval_s=1, history_size=600)`, then schedule `poll_once()` from one acquisition
caller. Each returned dictionary contains `attempted_at`, `status` or None, and
`error` or None. Use ordinary `json.dumps`; no sequence counter or custom serializer.
`snapshot()` returns model, simulated, copied history, interval_s and monotonic age_s.
Rendering does not wait for device I/O. Use a new monitor for each new session.
`create_app(monitor)` builds the optional Dash view without starting a server/worker.
The application owns scheduling and must finish acquisition before disconnect.

## Package layout

`controller.py` contains the public hardware API, protocol parsing, serial I/O and
the two error types. `simulator.py` supplies independent in-memory replies through
the same API. `gui.py` provides the optional monitoring cache and Dash view.
`__init__.py` exports the four public types; `__main__.py` implements the read-only CLI.

The application owns connection lifetime, polling and logging. One I/O lock
serializes individual transactions and complete status groups. Importing the
package starts no threads and opens no ports. pySerial is installed by default
but imported only on physical connect; Dash loads only when creating the app.
