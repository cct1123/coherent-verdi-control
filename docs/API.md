# Python API reference

Import the supported API from `coherent_verdi`. The package is synchronous,
typed (`py.typed`), and has no core runtime dependencies. Import and construction
do not connect to hardware. See [installation and runnable examples](../README.md)
and [application ownership](INTEGRATION.md) before embedding it in a service.

## Configuration and units

| Type | Parameters / contract |
| --- | --- |
| `Model` | `V2`, `V5`, `V6`; conservative software ceilings are 2, 5, 6 W respectively. Select explicitly from verified identity. |
| `ControllerConfig` | `model`, `allow_writes=False`, `power_limit_w=None`, `active_fault_clear_reply=None`. A supplied ceiling must be finite, nonnegative, and no greater than the model rating. Clear-fault text must be verified for the actual firmware; positive fault codes/lists are rejected. Frozen. |
| `SerialConfig` | Explicit native `port`, `baudrate=19200`, `timeout_s=1.0`, `max_response_bytes=4096`. No discovery or URL ports; validated baud values follow manual Table 5-2. Frozen. |
| `Status` | Model, UTC `sampled_at`, `duration_s`, laser/key/shutter states, power/setpoint in W, diode current in A, temperatures in °C, LBO servo, active faults, `simulated`. Frozen. |
| `Diagnostics` | Software version, head/power-supply/diode operating hours, fault history. Frozen. |
| `Fault` | Positive numeric `code`, `description`, `known`. Unknown codes survive decoding with `known=False`. |

Power arguments use watts, not milliwatts or percent. `set_power_w` serializes
four decimal places and checks the rounded value against the configured ceiling.
Booleans, NaN, infinity and out-of-range inputs raise `ValueError` before I/O.
These ceilings constrain software requests; they are not a physical safety system
or evidence of the firmware's full supported range.

The manual defines `SYSTEM OK` for `?FH`, but leaves the no-active-fault `?F` reply
unspecified. Physical `faults()`/`status()` calls fail on a clear-looking reply
until `active_fault_clear_reply` is set to the exact nonempty text verified in
[Stage 1](../HARDWARE_VALIDATION.md). Simulator transports default to `SYSTEM OK`
as a fixture convention only. Never copy that value into a hardware configuration
without verifying its meaning. Fault lists remain readable with the default None.
Model-specific diode/LBO servo values are checked: V2 excludes code 6 and V6
excludes code 5; V5/UNO distinctions remain an explicit identification requirement.

## Controller

Construct `VerdiController(transport, config)`. It owns the transport and supports
`with`. `config` is read-only. `is_simulated` identifies the current transport;
monitoring clients should use the source recorded in a telemetry snapshot instead.

| Method | Result / behavior |
| --- | --- |
| `status()` | `Status`; 14 sequential queries under one lock. Timestamp is the start of acquisition, not a simultaneous measurement. |
| `diagnostics()` | `Diagnostics`; serialized version, operating-hour and fault-history reads. |
| `power_w()` | `float`, measured power in W as reported by the device/fixture. |
| `laser_state()` | `LaserState.STANDBY`, `.ON`, or `.FAULT`. |
| `faults(history=False)` | `tuple[Fault, ...]`; pass `history=True` for history. |
| `query(Query.X)` | Catalogued query only; returns `float`, `int`, `str`, or fault tuple according to the [protocol catalog](PROTOCOL.md). Undocumented composite formats remain text. |
| `set_power_w(value)` | Send `P=nn.nnnn`; does not enable the laser. |
| `standby()` | Send `L=0`. |
| `enable_laser()` | Send `L=1`; also resets faults and clears history according to the manual. Requires operator prerequisites, including completed warmup and key ON. |
| `set_shutter(open=bool)` | Send `S=0/1` for the safety shutter. Never use it for experimental modulation. |
| `set_echo(enabled=bool)` | Explicit `E=0/1`; no connection-time mode changes. |
| `set_prompt(enabled=bool)` | Handles the documented reversed `PROMPT=0` ON / `1` OFF convention. |
| `replace_transport(fresh)` | Close old transport, install a caller-prepared different transport; no commands, reset, retries or settings replay. Closed controllers cannot be revived. |
| `close()` | Release communication; no change to laser/shutter/heaters. Repeated successful closes are harmless. Failed resource release can be retried with another `close()`. |

Every state-changing operation requires `allow_writes=True`. A normal return
means an acknowledgment was parsed, not that a requested physical state was
independently verified. Status reads and local validation are not interlocks.

```python
from coherent_verdi import ControllerConfig, Model, Query, SimulatedTransport, VerdiController

with VerdiController(SimulatedTransport(Model.V6), ControllerConfig(Model.V6)) as laser:
    print(laser.query(Query.SOFTWARE))
    for fault in laser.faults():
        print(fault.code, fault.description, fault.known)
```

## Telemetry and client ownership

`TelemetryService(controller, interval_s=1.0, history_size=600)` borrows the
controller. Its controller reference and validated interval are read-only;
construct a new service to reconfigure them. `start()` (or entering `with`)
starts one worker. `poll_once()` performs one synchronous sample, serialized
with worker polling. Neither construction nor reading the cache starts acquisition.

`history` returns a bounded immutable tuple of `TelemetrySample` objects.
`snapshot()` atomically returns that history, model, source kind, sample age and
interval without taking the controller lock. A failed sample has `status=None`,
`error` and `error_type`; callers must not substitute stale success values.
`running` reports worker liveness. `stop(timeout_s=30.0)` waits for the worker;
if it times out, keep the controller open and retry after acquisition finishes.

Use `coherent_verdi.gui.create_app(service)` for a cache-only Dash client.
The caller owns service start/stop and controller cleanup. For async ownership,
multiple web workers, logging and freshness rules, see [integration](INTEGRATION.md).

## Transports and failures

`Transport` describes `is_simulated`, `exchange(request: bytes) -> bytes` and
`close()`. `SerialTransport` wraps an injected byte stream and provides serialized,
bounded I/O. `open_serial(config, hardware_allowed=False)` refuses physical
access by default. Later opt-in is governed by [HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md).
Custom transports must enforce bounded I/O, unambiguous response ownership and
cleanup. Do not share a transport between controllers.

| Exception | Application response |
| --- | --- |
| `ValueError` | Correct invalid local input; nothing was sent. |
| `WritesDisabled` | The session did not authorize writes. |
| `DeviceError` | Inspect its `instruction` and `response`; the device reported rejection. |
| `ResponseTimeout`, `TransportError` | Outcome may be unknown, including after an applied write. Serial sessions become unusable. Do not replay automatically. |
| `ProtocolError` | Preserve evidence of malformed/unsupported data. Controller becomes unusable until explicit replacement. |
| `ConnectionUnusable` | Prepare a fresh session explicitly; reopening a physical port alone does not prove delayed bytes have cleared. |

All domain errors derive from `VerdiError`; `ValueError` is a separate local-input
error. The simulator's recoverable injected timeout is an explicit fixture policy,
not a serial recovery guarantee. See [simulator contracts](SIMULATOR.md).
