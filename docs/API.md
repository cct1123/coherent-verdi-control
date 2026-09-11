# Python API

```python
from coherent_verdi import VerdiController, SimulatedVerdi, VerdiError, DeviceError

VerdiController(
    port,  # Explicit native port string; no backend/factory argument
    *, model="V5", baudrate=19200, timeout_s=1.0,
    allow_writes=False, power_limit_w=None, active_fault_clear_reply=None,
)
SimulatedVerdi(model="V5", *, allow_writes=False, power_limit_w=None,
               clock=time.monotonic, warmup_s=0, echo=False, prompt=False)
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
`DeviceError` retains `instruction` and `response` for a complete documented
rejection; the session remains usable. Other `VerdiError` failures mean disconnected,
uncertain or malformed communication. Retire an uncertain session; no method clears
its failure latch. Interrupted/unexpected I/O errors propagate and also latch failure.
Disconnect remains available; failed cleanup is retryable and adds a note to an
already-active exception. Catch `DeviceError` before `VerdiError` to distinguish them.

## Optional monitoring

`from coherent_verdi.gui import Monitor, create_app`. Construct `Monitor(laser,
interval_s=1, history_size=600)`, then schedule `poll_once()` from one acquisition
caller. Each returned dictionary contains `attempted_at`, `status` or None, and
`error` or None. Use ordinary `json.dumps`; no sequence counter or custom serializer.
`snapshot()` returns model, simulated, copied history, interval_s and monotonic age_s.
Rendering does not wait for device I/O. Use a new monitor for each new session.
`create_app(monitor)` builds the optional Dash view without starting a server/worker.
The application owns scheduling and must finish acquisition before disconnect.

## Migration to 0.3.0

Reinstall with `python -m pip install -e .` and update callers together. No aliases,
deprecated modules or compatibility adapters are retained.

| Previous API | 0.3.0 |
| --- | --- |
| `VerdiController(SimulatedTransport(...), ...)` | `SimulatedVerdi(..., allow_writes=..., power_limit_w=...)` |
| `Model.V5`, `Query.POWER` | `"V5"`, `"?P"` |
| `LaserState.ON`, `ServoState.LOCKED` | Integer 1; use documented code meanings |
| `status.power_w`, `diagnostics.head_hours` | `status["power_w"]`, `diagnostics["head_hours"]` |
| `Fault.code`, `.description`, `.known` | Integer codes; descriptions are in PROTOCOL.md |
| `Status`, `Diagnostics`, `Sample`, datetime objects | Plain dictionaries with ISO UTC strings |
| `TransportError`, `ProtocolError` | `VerdiError`; `DeviceError` remains distinct |
| `coherent_verdi.monitor.Monitor` | `coherent_verdi.gui.Monitor` |
| `to_json(value)` | `json.dumps(value, allow_nan=False)` |
| Sample `.sequence` / CLI result envelope | Removed; CLI prints the result or sample directly |
| CLI writes, `--demo`, `--sim-key-on` | Use the explicit Python control example/tutorials |
| `Connection`, `SerialConnection`, backend injection | Removed; controller handles serial directly |

For 0.1 callers: pass former config fields as constructor keywords and use
`read`, `read_power_w`, `read_faults`, `read_laser_state`, `read_diagnostics`,
`start`, `stop`, `disconnect` instead of the old query/accessor/enable/standby/close
names. Explicitly connect or use a context manager. Transport replacement and
telemetry start/stop/logging callbacks are removed; the host owns orchestration.
