# Coherent Verdi Control

A small Python RS-232 controller for **Coherent Verdi V-2, V-5 and V-6** lasers.
Read power, temperatures and faults; set power; control standby, enable and the
safety shutter. Includes a simulator and an optional read-only Dash dashboard.

**Software-tested using simulation and fake serial connections. Physical
communication, optical behavior and calibration have not yet been validated.**

## Install

Requires Python **3.11+**. From a downloaded or cloned checkout:

```sh
python -m pip install .
```

Or install directly from the repository (requires Git):

```sh
python -m pip install "git+https://github.com/cct1123/coherent-verdi-control.git"
```

pySerial is installed automatically. Dash is optional. No background
service or project configuration files are needed to use the package.

## Connect and read

Connect the computer's RS-232 port, or a USB-to-**RS-232** adapter, to the Verdi
power supply. Verify the cable against Figure 5-1 of the supplied
[operator manual](verdi.manual_v5.pdf). The Verdi is DCE and uses pins 2, 3 and 5;
a USB-to-TTL UART adapter is not a substitute.

Use the known port and actual model. The driver uses **8N1, no flow control**.
Match the front-panel baud setting; **19200 is the factory default**, not automatic
baud detection. Keep one connection owner and close other serial clients.

```python
from coherent_verdi import VerdiController

with VerdiController("COM3", model="V5", baudrate=19200) as laser:
    print("Software:", laser.read("?SV"))
    print("Laser state:", laser.read_laser_state())  # 0 standby, 1 on, 2 fault
    print("Power:", laser.read_power_w(), "W")
    print("LBO temperature:", laser.read("?LBOT"), "°C")
```

Replace `COM3` with your port, such as `/dev/ttyUSB0` on Linux. Start with one
`?SV` query when commissioning an unverified link. Construction is passive;
opening the connection sends no initialization commands. Writes are disabled by
default. Exiting `with` releases the port; **it does not shut down the laser**.

## Status and faults

`status()` returns a dictionary of power, setpoint, key/shutter state,
temperatures, readiness and active faults. `read_diagnostics()` returns software
version, operating hours and fault history.

Before calling `status()` or `read_faults()` on hardware, independently establish
the firmware's exact no-active-fault `?F` reply. Configure that verified text as
`active_fault_clear_reply` in the constructor. The manual specifies `SYSTEM OK`
for **history**, `?FH`; do not assume it is also the active-fault reply.
Unverified clear-looking replies fail explicitly. See [commissioning](docs/HARDWARE.md).

Use the read-only commissioning command to capture the actual wire evidence.
Start with one version query; after checking that exchange, select the fault query:

```sh
verdi --port COM3 --model V5 --baudrate 19200 commission
verdi --port COM3 --model V5 --baudrate 19200 commission --query ?F
```

Each attempt produces a JSON line with timestamps, connection settings, payload,
encoded request and received response bytes as hex, and any error. `captured` means evidence was
collected; it does not interpret the reply or establish no faults. No fault-clear
setting is required for capture. Stop on a failed exchange; no recovery or replay
is attempted. Details and buffer-check limits are in the hardware guide.

```python
from coherent_verdi import VerdiController

with VerdiController(
    "COM3",
    model="V5",
    baudrate=19200,
    active_fault_clear_reply="<VERIFIED_CLEAR_TEXT>",
) as laser:
    status = laser.status()
    print(status["power_w"], status["set_power_w"], status["faults"])
    print(laser.read_faults(history=True))
```

Status comprises 14 sequential queries, not a simultaneous measurement. The
default transaction deadline is 1 s; configure `timeout_s` for the actual link.

## Set power and control

Enable writes explicitly with `allow_writes=True` and set `power_limit_w` to the
site-approved ceiling. The V2/V5/V6 defaults of 2/5/6 W are software ceilings,
not safe laboratory operating limits.

The following example changes only a setpoint in standby. Replace the port,
model, baud, verified clear text and watt placeholders before running:

```python
from coherent_verdi import VerdiController

TARGET_W = float("<TARGET_W>")
CEILING_W = float("<SITE_CEILING_W>")

with VerdiController(
    "<PORT>",
    model="V5",
    baudrate=19200,
    allow_writes=True,
    power_limit_w=CEILING_W,
    active_fault_clear_reply="<VERIFIED_CLEAR_TEXT>",
) as laser:
    if laser.read_laser_state() != 0 or laser.read("?S") != 0 or laser.read_faults():
        raise RuntimeError("Require standby, shutter closed and no active faults")
    laser.set_power_w(TARGET_W)
    print("Setpoint:", laser.read("?SP"), "W")
```

The setpoint remains stored. The API also provides `start()`, `stop()` and
`set_shutter(open=True/False)`. Laser enable and shutter opening require the
operator's beam, cooling, interlock and readiness checks. `start()` clears faults
and fault history; capture them first. The [controlled-session tutorial](examples/README.md#lesson-5-emission-requires-an-operator-ready-system)
shows readiness checks and verified normal completion.

On timeout or malformed communication, a command may already have executed.
The driver stops that session without retry or replay. Use the physical abort
procedure; do not send blind cleanup commands or power-cycle to recover serial
communication. `stop()` means standby; full shutdown follows the manual's
heater/cooling procedure. Use the head shutter only as a safety shutter.

## Command line

The installed `verdi` command reads hardware when given an explicit port and model:

```sh
verdi --port COM3 --model V5 --baudrate 19200 query ?SV
verdi --port COM3 --model V5 query ?P
verdi --port COM3 --model V5 diagnostics
```

For `status` or `watch`, also supply
`--active-fault-clear-reply "<VERIFIED_TEXT>"` before the subcommand. `watch`
accepts `--count` and `--interval` in seconds. CLI operations never enable writes.
Without `--port`, commands use the simulator:

```sh
verdi status
verdi watch --count 10 --interval 1
```

`python -m coherent_verdi` is equivalent to `verdi`. Python applications can
inspect `last_transaction` after a call or `VerdiError.transaction` after an
exchange failure; commissioning writes those records as JSONL.

## Simulator and optional dashboard

```python
from coherent_verdi import SimulatedVerdi

with SimulatedVerdi("V5") as laser:
    print(laser.status())
```

Synthetic readings do not establish hardware accuracy or timing.
For the optional dashboard, install the GUI extra from the checkout:

```sh
python -m pip install ".[gui]"
verdi gui
```

Open [http://127.0.0.1:8050](http://127.0.0.1:8050/). For hardware, supply the same
global connection settings and verified fault-clear text before `gui`. The
dashboard monitors one shared connection; it provides no write controls.
`gui --port 8051` changes the HTTP port. Ctrl+C drains acquisition and closes
communication without changing laser state.

For example, a hardware dashboard on HTTP port 8051 uses:

```sh
verdi --port COM3 --model V5 --baudrate 19200 --active-fault-clear-reply "<VERIFIED_TEXT>" gui --port 8051
```

## Reference and development

- [API](docs/API.md): methods, data, errors and monitoring integration.
- [Hardware setup and commissioning](docs/HARDWARE.md): first connection, checks and recovery.
- [Protocol](docs/PROTOCOL.md): manual mappings and firmware uncertainties.
- [Five hardware tutorials](examples/README.md) and [simulator reference](docs/SIMULATOR.md).

From a checkout, run the software-only checks:

```sh
python -m pip install -e ".[dev,gui]"
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy
node scripts/test_watchdog.cjs
python -m build
python scripts/install_smoke.py
```

Tests replace physical serial access with fakes, including the hardware examples.
Node.js is needed only for the dashboard watchdog test. Source distributions
include the manual, examples and tests; wheels contain the controller package.
