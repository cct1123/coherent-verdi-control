# Python API

```python
VerdiController(
    port,                       # Native port string or an unshared connection backend
    *, model="V5", baudrate=19200, timeout_s=1.0,
    allow_writes=False, power_limit_w=None, active_fault_clear_reply=None,
)
```

Model accepts `"V2"`, `"V5"`, `"V6"` or a `Model` member. Select actual hardware
explicitly; no model discovery exists. Serial settings apply to string ports;
injected backends control their own connection settings. Supported baud rates:
1200/2400/4800/9600/19200/38400/57600, 8N1, no flow control. Timeout is a finite
0.001–60 s total transaction budget; the fixed response ceiling is 4096 bytes.
These bounds are software choices, not firmware guarantees.

The default power ceiling is the model's 2/5/6 W rating. A supplied ceiling must
be finite, nonnegative and no larger. Neither establishes a safe site limit.
Physical no-fault `?F` text must be independently verified before setting
`active_fault_clear_reply`; the simulator convention is not firmware evidence.

| Method | Meaning |
| --- | --- |
| `connect()` | Passive open; repeated calls while connected do nothing |
| `disconnect()` | Release resources without changing device state; retryable cleanup |
| `read(query)` | One of 42 `Query` members or short strings such as `"?P"`; no raw writes |
| `read_power_w()` | Measured-power report, watts |
| `read_laser_state()` | `LaserState.STANDBY`, `ON` or `FAULT` |
| `read_faults(history=False)` | Boolean selects active/history faults; returns `Fault(code, description, known)` tuples |
| `read_diagnostics()` | Software version, head/supply/diode hours, fault history |
| `status()` | Frozen `Status`: states, W, A, temperatures in °C, LBO servo, faults, UTC start/duration |
| `set_power_w(watts)` | Four-decimal light-regulation setpoint; validate input and rounded value |
| `start()` | `L=1`: enable, reset faults and clear history; physical key must be ON |
| `stop()` | `L=0`: standby override; temperature servos remain powered |
| `set_shutter(open=bool)` | Explicit safety-shutter operation |
| `set_echo(enabled=bool)` | `E=0/1`; no automatic echo negotiation |
| `set_prompt(enabled=bool)` | `PROMPT=0` enables, `PROMPT=1` disables |

Read-only properties: `model`, `is_simulated`. Status is sequential, not an atomic
measurement or safety guarantee. `with laser:` connects and disconnects. After
I/O/parser failure, reconnect is rejected: retire the controller after cleanup
and establish a clean physical session. A normal acknowledged session can reopen.

`ValueError` means invalid local input; builtin `PermissionError` means writes
were not enabled. Both reject before transmission. Catch `VerdiError` for driver
failures: `TransportError` covers timeout, disconnected/failed sessions and serial
I/O; `ProtocolError` covers malformed/undocumented replies; `DeviceError` retains
`instruction` and `response` for a complete firmware rejection. Nothing retries
automatically. Failed cleanup adds a note to an already-active exception.

## Migration from 0.1.0 to 0.2.0

No internal compatibility layers remain. Pass former `ControllerConfig` and
`SerialConfig` fields as controller keywords; pass the port instead of calling
`open_serial`. `query`, `power_w`, `faults`, `laser_state`, `diagnostics` become
`read`, `read_power_w`, `read_faults`, `read_laser_state`, `read_diagnostics`.
`enable_laser`, `standby`, `close` become `start`, `stop`, `disconnect`. Direct use
requires `connect()`; context managers handle it. `replace_transport` is removed.

`ResponseTimeout` and `ConnectionUnusable` are folded into `TransportError`;
`WritesDisabled` becomes `PermissionError`. Import optional `Monitor` and `to_json`
from `coherent_verdi.monitor`. `poll_once()` is synchronous; `snapshot()` returns a
fresh dictionary containing immutable samples and age. There are no monitor
start/stop methods or logging callbacks. Use the host application's scheduler and
logging system.
