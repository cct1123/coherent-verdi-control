# Coherent Verdi Control

A small Python RS-232 controller for **Coherent Verdi V-2, V-5 and V-6** lasers.
Read power, temperatures and faults; set power; control standby, enable and the
safety shutter. Includes a simulator and an optional Dash control panel, read-only
by default, with explicit write enablement.
All commands and queries in the manual's Tables 5-3 and 5-4 are exposed, including
service and front-panel commands, plus documented long/short query aliases.

**Read-only serial communication was exercised on a Verdi V-2, firmware 6.05,
in notebooks 01–03 on 2026-10-26. Emission control, optical behavior and
calibration remain unverified on hardware.**

## Install

Requires Python **3.11+** and [uv](https://docs.astral.sh/uv/getting-started/installation/).
From a downloaded or cloned checkout:

```sh
uv sync
```

This creates `.venv` from the locked `uv.lock`, with the controller, pySerial and
the development tools. Run commands and scripts inside it with `uv run`, for example
`uv run verdi status` or `uv run python my_script.py`; no activation is needed.
Use `uv sync --extra gui` to add the optional Dash dashboard (Dash and
dash-bootstrap-components); a later plain
`uv sync` removes it again.

To use the controller from another uv project, add it from the repository
(requires Git):

```sh
uv add "coherent-verdi-control @ git+https://github.com/cct1123/coherent-verdi-control.git"
```

pySerial is installed automatically. The dashboard dependencies are optional. No background
service or project configuration files are needed to use the package. The package
is standard; `pip install .` also works outside uv.

## Connect and read

The simplest interface sends and receives bytes:

```python
from coherent_verdi import VerdiController

with VerdiController("COM5", model="V2", baudrate=19200, timeout_s=2) as laser:
    print(repr(laser.get(b"?SV")))
```

`get()` returns payload bytes after removing echo, CR/LF and the prompt.
The complete wire reply remains in `last_transaction["response"]`. The next
instruction waits until both the reply and prompt have arrived. No automatic
encoding or decoding occurs. The instrument prompt must be enabled; use
`prompt_enabled=False` only for an instrument already configured without prompts.
See lessons [1](examples/01_connect.ipynb) and [2](examples/02_quick_status.ipynb).
The examples below use explicit typed helpers for interpreted values.

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
    print("Software:", laser.get_value("?SV"))
    print("Laser state:", laser.read_laser_state())  # 0 standby, 1 on, 2 fault
    print("Power:", laser.read_power_w(), "W")
    print("LBO temperature:", laser.get_value("?LBOT"), "°C")
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
uv run verdi --port COM3 --model V5 --baudrate 19200 commission
uv run verdi --port COM3 --model V5 --baudrate 19200 commission --query ?F
```

Each attempt produces a JSON line with instruction, request/reply bytes as hex,
payload, outcome and any error. `captured` means evidence was
collected; it does not interpret the reply or establish no faults. No fault-clear
setting is required for capture. Stop on a failed exchange; no recovery or replay
is attempted. Details and communication limits are in the hardware guide.

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
default timeout is 1 s per write/read stage; configure `timeout_s` for the actual link.

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
    if laser.read_laser_state() != 0 or laser.get_value("?S") != 0 or laser.read_faults():
        raise RuntimeError("Require standby, shutter closed and no active faults")
    laser.set_power_w(TARGET_W)
    print("Setpoint:", laser.get_value("?SP"), "W")
```

The setpoint remains stored. The API also provides `start()`, `stop()` and
`set_shutter(open=True/False)`. Laser enable and shutter opening require the
operator's beam, cooling, interlock and readiness checks. `start()` clears faults
and fault history; capture them first. The [controlled-session notebook](examples/06_controlled_session.ipynb)
shows readiness checks and verified normal completion.

The API also exposes baud changes, the Coherent chiller, LBO heater/optimization,
etalon FLASH, panel locking and menu buttons. Use named methods or a validated
manual command such as `laser.set(b"LBOH=1")`. Long query forms such as
`laser.get_value("PRINT LIGHT")` are accepted too. See the [complete API](docs/API.md)
and [manual mapping](docs/PROTOCOL.md#complete-table-5-3-command-coverage).
Chiller limits, panel-lock values and baud-transition acknowledgment timing are
not fully specified by the manual; their physical behavior requires verification.

On timeout or malformed communication, a command may already have executed.
The driver stops that session without retry or replay. Use the physical abort
procedure; do not send blind cleanup commands or power-cycle to recover serial
communication. `stop()` means standby; full shutdown follows the manual's
heater/cooling procedure. Use the head shutter only as a safety shutter.

## Command line

The `verdi` command, run through `uv run`, reads hardware when given an explicit
port and model (`--no-prompt` only when the device prompt is disabled):

```sh
uv run verdi --port COM3 --model V5 --baudrate 19200 query ?SV
uv run verdi --port COM3 --model V5 query ?P
uv run verdi --port COM3 --model V5 diagnostics
```

For `status` or `watch`, also supply
`--active-fault-clear-reply "<VERIFIED_TEXT>"` before the subcommand. `watch`
accepts `--count` and `--interval` in seconds. These operations never enable writes.
Without `--port`, commands use the simulator:

```sh
uv run verdi status
uv run verdi watch --count 10 --interval 1
```

To execute a write, use `command` with one quoted manual instruction and the
explicit `--allow-writes` flag. The same power ceiling and operand validation as
the Python API apply. For example, this changes only the power setpoint:

```sh
uv run verdi --port COM3 --model V5 command "P=0.25" --allow-writes --power-limit-w 0.5
```

Select the port, model and site-approved setpoint/ceiling for your setup. Writes
are rejected without `--allow-writes`. Each attempted write emits its transaction
evidence as JSONL; failures return exit code 2 and are never replayed. Omitting
the global serial `--port` uses the simulator, including for command execution.

`uv run python -m coherent_verdi` is equivalent to `uv run verdi`. Python
applications can inspect `last_transaction` after a call or `VerdiError.transaction` after an
exchange failure; commissioning writes those records as JSONL.

## Simulator and optional dashboard

```python
from coherent_verdi import SimulatedVerdi

with SimulatedVerdi("V5") as laser:
    print(laser.status())
```

Synthetic readings do not establish hardware accuracy or timing.
For the optional dashboard, sync the GUI extra from the checkout:

```sh
uv sync --extra gui
uv run verdi gui
```

Open [http://127.0.0.1:8050](http://127.0.0.1:8050/). For hardware, supply the same
global connection settings and verified fault-clear text before `gui`. The
dashboard uses one shared connection. Its overview, all 42 queries, diagnostics
and fault history are available in read-only mode. Raw capture also requires a
read-only session. `gui --commission` starts with overview polling paused so an
unverified active-fault reply can be captured before any automatic status reads.
`gui --port 8051` changes the HTTP port. Ctrl+C drains acquisition and closes
communication without changing laser state.

The dashboard opens with a replica of the Verdi power-supply front panel: AC ON
and LASER EMISSION indicators, key switch, two-line display, MENU UP/DOWN,
SELECT, EXIT, SHUTTER OPEN, POWER LEVEL 1/2 and the POWER ADJUST knob. The
display is synthesized from queries; the laser's own LCD cannot be read over
RS-232, so MENU keys change the laser's menu but not the replica. The knob only
edits the target (SET POWER sends it), POWER LEVEL presets are stored in the
browser rather than the laser, and the key switch is read-only. Indicators without
a live sample show as hollow (unknown), never as off. Bootstrap's stylesheet is
bundled with the package, so the dashboard works without internet access.

For example, a hardware dashboard on HTTP port 8051 uses:

```sh
uv run verdi --port COM3 --model V5 --baudrate 19200 --active-fault-clear-reply "<VERIFIED_TEXT>" gui --port 8051
```

Enable the GUI's full set of power, laser, shutter, service and front-panel
controls explicitly, with your site-approved power ceiling:

```sh
uv run verdi --port COM3 --model V5 --active-fault-clear-reply "<VERIFIED_TEXT>" gui --allow-writes --power-limit-w 0.5
```

For hardware-free exploration: `uv run verdi gui --allow-writes --power-limit-w 0.5`.
Inputs apply only when clicked; overview refreshes preserve unsent edits.
Start and shutter-open require the readiness switch. The server validates all
actions; fresh overview data is required for writes other than standby and
shutter-close. Results distinguish acknowledgment, matching readback, mismatch
and failure. Commands without getters report acceptance only.

One acquisition caller drains a bounded request queue. Standby/shutter-close
requests precede routine reads and cancel older queued writes that could change
operation; they cannot interrupt an exchange already in progress. Duplicate
browser events are suppressed, queued requests expire after 10 s, and uncertain
writes are never replayed. Closing the application cancels pending actions and
drains in-flight I/O without changing laser state. See [GUI details](docs/API.md#gui-control-panel).

## Reference and development

- [API](docs/API.md): methods, data, errors and monitoring integration.
- [Developer walkthrough](docs/DEVELOPMENT.md): ownership, request flow and extension points.
- [Hardware setup and commissioning](docs/HARDWARE.md): first connection, checks and recovery.
- [Protocol](docs/PROTOCOL.md): manual mappings and firmware uncertainties.
- [Hardware tutorial notebooks](examples/README.md) and [simulator reference](docs/SIMULATOR.md).

From a checkout, sync every extra and run the software-only checks:

```sh
uv sync --all-extras
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
node scripts/test_watchdog.cjs
uv build
uv run scripts/install_smoke.py
```

`uv sync` installs the project in editable mode plus the `dev` dependency group
(pytest, ruff, mypy); `uv.lock` pins every version, and CI runs
`uv sync --locked` so a stale lock fails. Change dependencies with `uv add` /
`uv remove` (`--dev` for tools, `--optional gui` for the dashboard) and refresh
pins with `uv lock --upgrade`; commit `uv.lock` with `pyproject.toml`.

Tests replace physical serial access with fakes, including the tutorial notebooks.
Node.js is needed only for the dashboard watchdog test. Source distributions
include the manual, tutorial notebooks and tests; wheels contain the controller package.
