# Four first Verdi tutorials

Work through these in order. Each takes a few minutes and defaults to a fresh
**in-memory Verdi simulator**. Each also has an implemented real-hardware path
for a human operator, available in its self-contained notebook or the terminal runner.
Expected outputs below describe synthetic fixtures. Simulator mode needs no serial
dependency or physical connection; development and testing remain simulator-only.

| Lesson | Notebook | Terminal lesson | What you learn |
| --- | --- | --- | --- |
| 1. Read status | [01_read_status.ipynb](01_read_status.ipynb) | `read-status` | Queries, units, state, diagnostics and write protection |
| 2. Set power in standby | [02_set_power.ipynb](02_set_power.ipynb) | `set-power` | Bounded setpoint, readback and rejected input |
| 3. One controlled session | [03_controlled_session.ipynb](03_controlled_session.ipynb) | `controlled-session` | Preconditions, enable, safety shutter and verified standby |
| 4. Diagnose and stop | [04_handle_faults.ipynb](04_handle_faults.ipynb) | `faults` | Active/history faults, unknown codes and uncertain write outcomes |

## Start here

Use Python **3.11 or later**, activate the repository's virtual environment, then
run these commands from the repository root:

```sh
python -m pip install -e ".[tutorials]"
python -m jupyterlab examples/tutorials
```

Open lesson 1 and choose the Python kernel from this environment. Use **Restart
Kernel and Run All Cells** for a complete run, or run cells from top to bottom
with Shift+Enter. Each notebook contains the application source, explanations
and expected output. All demonstration, connection and cleanup functions are visible
in separate cells; no notebook imports or runs a tutorial script. Its simulator
execution cell creates a fresh fixture and closes the controller before returning.
The final hardware section defaults to disabled and calls the notebook's own
functions directly. Neither mode leaves a connection waiting between cells.

All terminal equivalents live in [run_tutorial.py](run_tutorial.py), with small
functions for each lesson and no dynamic script loading. They need only the
dependency-free core (`python -m pip install -e .`) and default to simulation:

```sh
python examples/tutorials/run_tutorial.py read-status
python examples/tutorials/run_tutorial.py set-power
python examples/tutorials/run_tutorial.py controlled-session
python examples/tutorials/run_tutorial.py faults
```

These commands replace the former separate `read_status.py`, `set_power.py`,
`controlled_session.py` and `handle_faults.py` files. Notebook filenames and the
runner's arguments are unchanged.

If an import fails, check that the selected kernel uses the environment where
you installed the checkout. Install packages in the terminal, then restart the
kernel. Do not add serial connection code to resolve a notebook setup error.

## Common command vocabulary

`?` starts a query. `=` sets a value. The controller sends ASCII with CR/LF,
waits for a complete reply, and parses it before sending the next instruction.
Successful commands normally have an empty acknowledgment when echo/prompt are
off; no `OK` acknowledgment is expected. Construction and `close()` send nothing.

`status()` expands to `?L, ?K, ?S, ?P, ?SP, ?D1C, ?D1T, ?D1HST, ?BT, ?LBOT,
?LBOSS, ?ET, ?VT, ?F`. It is a sequential sample, not a simultaneous measurement.
`diagnostics()` expands to `?SV, ?HH, ?PSH, ?D1H, ?FH`. The configured V5 model
is supplied by the caller; `?SV` reports software, not model identity.

These commands follow the supplied [operator manual](../../verdi.manual_v5.pdf),
Tables 5-1, 5-3 and 5-4 (printed pp. 5-2, 5-5 through 5-10). See the
[protocol reference](../../docs/PROTOCOL.md) for exact mappings and uncertainty.

## 1. Read status and diagnostics

Query `?SV`, `status()` and `diagnostics()`. The simulator reports V5,
STANDBY, key OFF, shutter closed, 0 W, LBO 148 °C / LOCKED, 100 head hours
and no faults. The write-protection exercise catches `WritesDisabled` without
transmitting a command. Query failures stop the run rather than present partial
data as healthy. See [lesson 1](01_read_status.ipynb) for code and an exercise.

## 2. Set power in standby

Check `?L, ?S, ?F`; send `P=0.2500`; verify `?SP, ?L, ?S, ?P`. The
simulator retains STANDBY/closed shutter and reports zero power. Reject 0.6 W
locally against the exercise's 0.5 W ceiling, then explicitly repeat the guarded
sequence with `P=0.0000`. No enable/open occurs. Invalid input or mismatched
readback stops the sequence without retry. [Lesson 2](02_set_power.ipynb) explains
the distinction between setpoint and reported power, and four-decimal readback.

## 3. One start–shutter–standby session

After the local simulator key fixture is ON, check `status()` and `?FH`;
send `P=0.2500, ?SP` → `L=1, ?L, ?F, ?S` → `S=1, ?S, ?F, ?P` →
`S=0, ?S` → `L=0, ?L`. Expect one opening at synthetic 0.250 W, then
verified shutter closed/STANDBY with the setpoint retained. `L=1` clears fault
history; read it first. [Lesson 3](03_controlled_session.ipynb) checks initial
standby, closed shutter, key ON, LBO LOCKED and no active faults, then each result.
The head shutter is a safety shutter, never an experimental modulator. Real idle
power/ramp time are unverified; see [simulator policies](../../docs/SIMULATOR.md).

## 4. Inspect faults and handle a lost acknowledgment

Inject synthetic codes 2 (external interlock) and 999 (unknown); read `?L, ?F, ?FH`.
Remove active fixture conditions and read again: history retains both codes and
state remains FAULT, a simulator policy. A separate standby fixture applies
`P=0.2500` and loses the acknowledgment. The example reports UNKNOWN and ends
after exactly one write; no retry, recovery query, reset or enable occurs.
[Lesson 4](04_handle_faults.ipynb) explains why a missing reply cannot tell the caller
whether a command executed. Unknown codes remain visible and require diagnosis.

## Human-operated hardware

Each notebook explicitly defines its connection, validation and cleanup functions
in section 7 and calls its own application functions. No external tutorial code is
loaded. For terminal use, [run_tutorial.py](run_tutorial.py) calls its own lesson
functions. Both paths open an explicit `SerialConfig` through the controller library's
`open_serial`. No connection code needs to be written by the operator.
The model, port and matching front-panel baud must be supplied; write lessons also
require an explicit target and site ceiling in W. There are no physical power
defaults. The 1 s transaction timeout is configurable with `--timeout-s` and
must be validated for the actual link.

First complete the [hardware review procedure](../../HARDWARE_VALIDATION.md).
These entry points are prepared for an approved human session; their presence
does not establish physical validation or authorize the agent to operate hardware.
The operator needs the manual/site procedure, confirmed connection/model,
cooling/warmup/interlocks, appropriate beam termination and physical abort plan.
Keep a single controller owner and stop competing clients before connecting.

Install the serial adapter in the same environment:

```sh
python -m pip install -e ".[tutorials,serial]"
python examples/tutorials/run_tutorial.py --help
```

**In a notebook:** run section 7's definition cells, then fill `HARDWARE_PORT`, `HARDWARE_MODEL` and
`HARDWARE_BAUDRATE`. For write lessons, also fill `TARGET_W` and `POWER_LIMIT_W`.
Set `RUN_HARDWARE=True` only for an attended, approved session, then run that
configuration cell followed by its hardware-run cell. Notebook 1 defaults to
`IDENTIFY_ONLY=True`; use this for the first `?SV` check, then set it to False
only when broader queries are approved. Return `RUN_HARDWARE` to False afterwards.

**From a terminal:** the following are command templates. Replace every `<...>`
token with operator-verified settings before executing; `<MODEL>` is V2, V5 or V6.
Do not copy simulator exercise values as physical power limits.

```text
python examples/tutorials/run_tutorial.py read-status --hardware --port <PORT> --model <MODEL> --baudrate <BAUD> --identify-only
python examples/tutorials/run_tutorial.py read-status --hardware --port <PORT> --model <MODEL> --baudrate <BAUD>
python examples/tutorials/run_tutorial.py set-power --hardware --port <PORT> --model <MODEL> --baudrate <BAUD> --target-w <TARGET_W> --power-limit-w <CEILING_W>
python examples/tutorials/run_tutorial.py controlled-session --hardware --port <PORT> --model <MODEL> --baudrate <BAUD> --target-w <TARGET_W> --power-limit-w <CEILING_W>
python examples/tutorials/run_tutorial.py faults --hardware --port <PORT> --model <MODEL> --baudrate <BAUD>
```

Configuration is validated **before opening**. The runner then asks for `CONNECT`,
opens only the specified port, and sends `?SV` first. Identification-only mode
ends there. Otherwise it displays the reported version and planned actions and
asks for `RUN` before any lesson queries/writes. Verify the device/version against
the reviewed configuration; `?SV` does not identify the model. Any other answer
cancels, and no lesson action is sent. These prompts confirm intent; they do not
replace recorded candidate/site approval. There is no unattended confirmation flag.

| Lesson | Real-hardware path and normal end state |
| --- | --- |
| Read status | `?SV` first, then the status/diagnostic function after RUN; writes disabled. No deliberate write-rejection exercise. |
| Set power | Read preconditions, set the supplied target and verify readback/state/power. Remains in STANDBY with shutter closed and the requested setpoint **stored**. No rejected-input demo or automatic return to zero. |
| Controlled session | Verify readiness/history, set target, enable, open safety shutter once, read power once, close shutter and enter STANDBY with readbacks. Target remains stored. This immediate sample does not prove optical settling or calibration. |
| Faults | Read `?L, ?F, ?FH` once; retain actual/unknown codes. Writes disabled. No injection, removal, reset or lost-write exercise. |

Hardware command sequences use the functions shown in the notebooks; only the
fixture-specific exercises are omitted. No synthetic keyswitch/readiness changes
are applied. Exact setpoint-readback comparison must be validated against firmware
precision in Stage 1/2 before write lessons are used. No port discovery, mode
normalization, fallback to simulation or automatic reconnect is performed.

On error/Ctrl+C, the session stops subsequent commands and releases communication.
A lost reply may follow an executed command. Follow the physical abort procedure;
there are no blind cleanup writes over an uncertain connection. Closing a connection
is not laser shutdown. The controlled lesson performs its verified shutter-close/
standby sequence on normal completion; full heater/cooling shutdown still follows
the manual. Physical behavior and calibration remain **UNTESTED**.

## Maintainer checks

```sh
python -m pip install -e ".[dev,serial,gui]"
python -m pytest tests/test_tutorials.py -q
python scripts/validate.py
```

TEST-011/012/013 check all models, command order/readbacks, rejected states/inputs,
failure stopping, terminal entry points, and notebook execution in fresh kernels.
Every notebook function is checked against its equivalent in `run_tutorial.py`.
Notebook code cells are kept below 30 lines, and each notebook
executes in an empty working directory to prove it needs no adjacent scripts.
Hardware cells are tested with a simulated serial factory and scripted human
answers; no real port is opened. Tests cover configuration and cancellation before
open, `?SV` first, no writes without RUN, no fault injection and no reconnect/replay.
Update both source forms when editing. Executed notebook copies go to
`records/tutorial-notebooks/`; source notebooks keep outputs clear. Kernel tests
block real serial opening/discovery before tutorial imports. The clean-install
check runs all four terminal lessons and the default with only the core wheel installed.

Notebook execution uses the [NBClient API](https://nbclient.readthedocs.io/en/latest/client.html);
interactive startup follows [JupyterLab's guide](https://jupyterlab.readthedocs.io/en/stable/getting_started/starting.html).
