# Coherent Verdi Control

A small synchronous Python driver for Coherent Verdi V-2/V-5/V-6 lasers.
Six device operations, all 42 documented queries, a simulator, and optional
monitoring, JSON logging and a Dash GUI. The core has no third-party dependencies
and starts no threads.

Version **0.2.0** introduces the compact API. Existing 0.1.0 callers should follow
the [migration guide](docs/API.md#migration-from-010-to-020) and reinstall the package.

**Software/simulator validation only.** Wiring, firmware behavior and calibration
remain untested. No physical ports are opened or enumerated during development.
See [current results](outputs/REPORT.md) and the
[hardware review procedure](HARDWARE_VALIDATION.md).

## Install

Python 3.11 or later, from this checkout:

```sh
python -m pip install -e .             # Controller + simulator
python -m pip install -e ".[serial]"  # pySerial for approved hardware use
python -m pip install -e ".[gui]"     # Dash / Plotly
```

Optional imports occur only when used. Installing an extra does not connect to
anything. For notebooks install `.[tutorials]`; for development install
`.[dev,serial,gui]`. These commands do not assume a published PyPI release.

## Use the controller

```python
from coherent_verdi import SimulatedTransport, VerdiController

with VerdiController(SimulatedTransport(), model="V5") as laser:
    print(laser.read_power_w(), "W")
    print(laser.read("?LBOT"), "°C")
    print(laser.status())
```

Construction is passive. `with` calls `connect()` then `disconnect()`. An experiment
stack can instead call those methods explicitly and share the connected controller
among its own clients. One controller serializes all I/O on one connection.

A complete **simulated** control sequence:

```python
sim = SimulatedTransport("V2")
sim.set_key(True)  # Fixture only; no remote physical-keyswitch command exists.
with VerdiController(sim, model="V2", allow_writes=True, power_limit_w=0.5) as laser:
    laser.set_power_w(0.25)
    laser.start()  # L=1 also resets faults and clears fault history.
    laser.set_shutter(open=True)
    print(laser.read_power_w(), "W")
    laser.set_shutter(open=False)
    laser.stop()  # Standby; temperature servos remain powered.
```

After candidate review and operator approval, pass an explicit native port instead
of the simulator: `VerdiController(port, model=model, baudrate=baudrate)`.
There is no discovery, initialization command, mode negotiation or automatic retry.
For the first approved interaction, call `connect()` followed by `read("?SV")`.
Full physical status also requires independently verified `active_fault_clear_reply`;
see [protocol uncertainties](docs/PROTOCOL.md#uncertainty-register).

`disconnect()` releases communication only. It never changes laser, shutter,
power or heater state. The shutter is a safety shutter, not a modulation device.
An uncertain reply or interrupted transaction disables that controller session;
verify device state and establish a clean connection before creating another.
Reopening a port alone does not prove delayed replies have cleared.

## Optional monitoring and GUI

```python
from coherent_verdi.monitor import Monitor, to_json

with VerdiController(SimulatedTransport()) as laser:
    monitor = Monitor(laser, history_size=100)
    sample = monitor.poll_once()  # Caller schedules every sample.
    print(to_json(sample))  # Or write to your existing logging system.
```

Monitor has no worker or connection lifecycle. Its bounded cache records failed
samples as gaps. `coherent_verdi.gui.create_app(monitor)` builds a read-only Dash
client of this cache. Monitor acquires through the same public `status()` API.

```sh
verdi status
verdi query '?SV'
verdi --demo watch --count 5 --interval 0.1
verdi --demo gui
```

The CLI always uses a fresh simulator. `--demo` prepares a synthetic 1 W beam.
`watch` emits flushed JSON Lines; `gui` serves
[localhost:8050](http://127.0.0.1:8050/) with debug/reloader off. Its launcher
explicitly starts and joins the polling worker; Ctrl+C ends it before disconnect.
Browser callbacks never query the device. Errors show unknown values, old data is
marked stale, and a browser watchdog warns if server updates stop.

## Learn, integrate and validate

- [Four self-contained notebooks and operator runner](examples/tutorials/README.md)
- [Public API and migration](docs/API.md)
- [Integration, concurrency, async use and shutdown](docs/INTEGRATION.md)
- [Eight-module architecture](ARCHITECTURE.md)
- [Protocol](docs/PROTOCOL.md) and [simulator policies](docs/SIMULATOR.md)

```sh
python -m pip install -e ".[dev,serial,gui]"
python scripts/validate.py
```

Validation covers behavior tests, hardware-guarded notebook kernels, lint/format,
strict typing, builds, installed-wheel/core/GUI checks, examples and the browser
watchdog. Node.js is required (`VERDI_NODE` can specify its path). The extras check
uses pip's registry/cache. Results and source hashes go to `records/validation.json`;
generated logs and notebook outputs accompany it. CI declares Windows/Linux and
Python 3.11–3.13; only executed environments have PASS evidence.

[STATE.md](STATE.md), [PROJECT.md](PROJECT.md) and [records](records/RECORDS.md)
preserve engineering continuity and the hardware review gate. [Template
provenance](records/FRAMEWORK.md) remains independent of runtime device control.
