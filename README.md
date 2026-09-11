# Coherent Verdi Control

A small synchronous Python driver for Coherent Verdi V-2/V-5/V-6 lasers: direct
serial I/O, 42 manual queries, six command forms and a hardware-free simulator.
Three substantive modules, four public exports, no required runtime dependencies.
GUI and monitoring are optional. The driver starts no threads.

**0.3.0 is a breaking simplification.** Results are plain dictionaries, strings,
numbers and fault-code lists. Follow the [migration guide](docs/API.md#migration-to-030)
and reinstall the package. This checkout has software/simulator validation only;
physical behavior and calibration remain untested. See [results](outputs/REPORT.md)
and the [hardware review procedure](HARDWARE_VALIDATION.md).

## Install and read

Python 3.11 or later, from this checkout:

```sh
python -m pip install -e .             # Core and simulator
python -m pip install -e ".[serial]"  # pySerial, for approved hardware use
python -m pip install -e ".[gui]"     # Optional Dash / Plotly
```

```python
import json
from coherent_verdi import SimulatedVerdi

with SimulatedVerdi("V5") as laser:
    print(laser.read_power_w(), "W")
    print(laser.read("?LBOT"), "°C")
    print(json.dumps(laser.status(), indent=2))
```

For approved hardware use, construct `VerdiController(port, model=model,
baudrate=baudrate)` with an operator-identified native port. Both classes expose
the same `connect`, `disconnect`, `read_*`, `set_*`, `start`, `stop` and `status`
methods. Construction does nothing; `with` connects and disconnects. An experiment
stack can call those methods explicitly and share one connected object among clients.
All I/O, including complete status groups, is serialized by that object.

There is no port discovery, automatic initialization, reconnect or command replay.
Begin approved physical integration with passive `connect()` and one `read("?SV")`.
Full status needs independently verified `active_fault_clear_reply` for that firmware.

## Control and shutdown

This complete example operates only on a simulator:

```python
with SimulatedVerdi("V2", allow_writes=True, power_limit_w=0.5) as laser:
    laser.set_key(True)  # Fixture only; the real keyswitch is physical.
    laser.set_power_w(0.25)
    laser.start()  # L=1 also resets faults and clears their history.
    laser.set_shutter(open=True)
    print(laser.status()["power_w"], "W")
    laser.set_shutter(open=False)
    laser.stop()  # Standby; temperature servos remain powered.
```

Writes default to disabled. Inputs and the rounded wire setpoint must fit the
configured ceiling. The example ceiling and model ratings are not site safety limits.
`disconnect()` releases communication; it never changes laser or shutter state.
After timeout, malformed reply or interruption, cease commands and retire the session.
Use the site's physical abort procedure if needed; closing/reopening cannot prove
late untagged replies have cleared. See [API behavior](docs/API.md).

## Integrate, log or display

Log ordinary results with `json.dumps(laser.status())` or your application's logger.
There is no custom serializer or logging service. The [async example](examples/async_integration.py)
keeps connect/read/cleanup together in one worker. Cancelling an await cannot stop
serial I/O; drain the worker before releasing its connection.

For a GUI, import `Monitor` and `create_app` from `coherent_verdi.gui`. One application
caller schedules `monitor.poll_once()`; browser callbacks read only `snapshot()`.
The cache is bounded, copies returned data, marks stale readings and records errors
as gaps. Neither object opens connections or starts workers. Dash loads only when
`create_app(monitor)` is called.

```sh
verdi status
verdi query '?SV'
verdi watch --count 5 --interval 0.1
verdi gui
```

The CLI is read-only and always uses a fresh simulator. `watch` emits flushed JSON
Lines. `gui` serves [localhost:8050](http://127.0.0.1:8050/) and explicitly starts
and joins its polling worker. Ctrl+C drains acquisition before disconnecting.
Keep debug/reloader off; larger web stacks should share one controller, not create
one per web worker. The display and its connection watchdog are not interlocks.

## Examples and validation

- [Four self-contained notebooks and operator runner](examples/tutorials/README.md)
- [API, result fields and migration](docs/API.md)
- [Architecture](ARCHITECTURE.md), [protocol](docs/PROTOCOL.md), [simulator policies](docs/SIMULATOR.md)

```sh
python -m pip install -e ".[dev,serial,gui]"
python scripts/validate.py
```

Notebooks additionally need `.[tutorials]` for JupyterLab. Validation exercises
guarded notebook kernels, protocol/serial behavior, lint/format, strict typing,
builds, isolated installations, examples and the browser watchdog. Node.js is
required (`VERDI_NODE` can specify its path); extras installation uses pip's registry/cache.
`records/validation.json` captures results and source hashes. CI declares Windows/Linux
and Python 3.11–3.13; only executed environments have PASS evidence.

[STATE.md](STATE.md), [PROJECT.md](PROJECT.md), [records](records/RECORDS.md) and
[template provenance](records/FRAMEWORK.md) preserve engineering continuity.
