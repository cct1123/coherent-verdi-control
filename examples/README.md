# First steps with your Verdi

These are **hardware-only tutorial notebooks** for a human operator. Each notebook
is split into short numbered sections: a few sentences of explanation, then a
small code cell you run and check before moving on. Each notebook is independent.
None uses shared helper code or a simulation switch.

The operator confirmed successful runs of notebooks 00–07 on 2026-10-27 using
the V2 / firmware 6.05 setup. Notebook 08 remains unresolved: the optional
shutter-close example records a timeout with extra firmware diagnostics. The
[hardware validation record](../docs/HARDWARE.md#validation-record-2026-10-27)
separates that report, saved evidence and remaining limits.
Work with your lab's laser operator and follow the
[hardware setup guide](../docs/HARDWARE.md) and [operator manual](../verdi.manual_v5.pdf).

## 1. Install and open the notebooks

Use Python **3.11 or later** and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Open a terminal in the repository folder, then run:

```sh
uv sync
uv run --with jupyter jupyter lab examples
```

`uv sync` creates `.venv` with the controller, pySerial and Matplotlib. The second command
starts JupyterLab in that environment, adding Jupyter only for this session, and
opens the `examples` folder in your browser. In VS Code, you can instead open a
notebook and choose the `.venv` interpreter as its kernel.

Connect the computer to the Verdi power supply using RS-232, or a USB-to-RS-232
adapter. A USB-to-TTL UART adapter is a different electrical interface and is not
suitable. Verify cable pinout/DCE orientation against manual Figure 5-1.

[Lesson 0](00_device_discovery.ipynb) finds the port and shows where to read
the model and baud rate. Section 1 of lessons 1–8 lists the settings to enter:
port, model and baud rate, plus the approved power settings for
lessons 5–7. Ask the operator to confirm each value. Keep one serial connection
owner: close other terminal programs, dashboards or notebooks that use this port.
The driver uses 8 data bits, no parity, 1 stop bit and no flow control. It never
scans ports or detects baud automatically.

## 2. Work through the lessons

Lessons 0–4 cover discovery and read-only checks. Lessons 5 and 6 are independent
write procedures with different starting conditions and need the operator's
approved conditions and limits. Lesson 6 assumes the key is already ON and does
not require completing lesson 5 first.

| Lesson | What you do |
| --- | --- |
| [0. Find the port](00_device_discovery.ipynb) | Identify the adapter's port from the operating system's device list. Opens no port and sends nothing. |
| [1. First connection](01_connect.ipynb) | Open the port, read the software version and release the port. |
| [2. Quick status](02_quick_status.ipynb) | Read power, laser state, shutter, keyswitch and active faults. |
| [3. Health check](03_health_check.ipynb) | Inspect 41 queries in nine subsystem sections (`?DIOS` skipped after device rejection), preserving byte payloads without changing settings. |
| [4. Pre-key-on readiness](04_check_readiness.ipynb) | Check warm-up, refresh serial readiness readings and verify front-panel and physical conditions. Queries only. |
| [5. Set power with the key OFF](05_set_power.ipynb) | Verify physical key OFF, laser OFF, closed shutter and clear active faults; store and verify power. Never enables or opens the shutter. |
| [6. One controlled session](06_key_on_and_run.ipynb) | Start with the physical key already ON and shutter closed; verify readiness and power, run one confirmed shutter cycle, then leave the laser ON with the shutter closed. |
| [7. Settling study and power sweep](07_power_current_sweep.ipynb) | First record a fixed-power time trace; then wait at each approved power setting and record one settled point. Save both stages in one CSV. |
| [8. Controller API guide](08_controller_api_ref.ipynb) | Test every public controller method in executable cells, including getters, setters and byte transport. Hardware writes are enabled individually. |

Lesson 7 starts with the laser already ON and shutter closed; it sends no enable
or standby commands. It records a shutter-opening time trace at the first approved
setpoint, closes for review, then sweeps the settings: set, wait, read one row.
`SETTLING_SAMPLE_COUNT` controls the trace length. `SETTLING_SAMPLE_PAUSE_S` is an
extra pause after acquisition/readiness checks, not the total sampling interval.
Choose `SWEEP_DWELL_S` after the completed study. Readiness checks remain before opening
and before accepting data. Both stages finish with shutter closed and laser ON.

Each sweep row has setpoint, reported power, diode current, diode/heatsink
temperatures and elapsed time. One UTC-stamped CSV contains both stages, identified
by `stage = study` or `stage = sweep`. `elapsed_s` is relative to each stage's start;
fields not acquired for a stage remain blank. Study rows retain their UTC timestamps
and read-window durations; sweep rows retain diode and heatsink temperatures.
Optional cells plot the study versus time and the sweep versus setpoint.
Matplotlib is included in the project environment
created by `uv sync`.

Lesson 8 is an independent developer guide to the controller's `get_...` and
`set_...` API. Enter its native port, model and baud settings first. It demonstrates
every getter, then explains every setter by task, including arguments, return
values and relevant readback. Every public controller method has an executable
code cell. By default, execution sends queries only. To test a write, enter the
approved ceiling and enable `OPEN_WRITE_SESSION` in section 9, inspect the port
opening, then run the separate communication cell. Set `RUN_THIS_EXAMPLE = True`
only in the desired command cell and fill in any required approved values.
Reset that flag afterwards; these independent examples are not an operating
sequence. Follow lessons 5–6 for complete operator procedures. Section 15 releases
both reader and optional writer connections. Byte transport, catalogue inspection
and an optional context-manager session also have executable cells.
`TIMEOUT_S` configures serial write and receive waits. Each reply/notice line
and enabled trailing prompt uses a separate `read_until()` call. No combined
transaction deadline or extra inter-query pause is imposed. Echo and prompt
setters remain in the API tour.

Run the cells one at a time (Shift+Enter) and read each result before the next.
Creating the controller sends nothing. Every connecting lesson has two separate
sections: **Open the serial port** and **Start serial communication**. The first
cell calls only `connect()` and prints its Boolean result. Inspect it before
proceeding. `True` confirms the local port opened; it does not confirm a laser reply
or readiness. Opening errors raise an exception. The communication section
explicitly purges host queues once before its first query. The
last cell, **Disconnect**, releases the port. In lesson 6 the physical key remains
ON throughout; no key transition is required. Run cells individually and inspect
each result. Type `SET` before storing power and `RUN` before the shutter cycle;
any other answer cancels. Those confirmations record your intended action.
They do not replace the lab's operating procedure.

### Clear serial buffers before the first query

After updating the package, restart the notebook kernel to load the current API.
Open the port in its own cell:

```python
connected = laser.connect(override=True)
print("Serial port open:", connected)
```

`override=True` closes an older controller-owned connection to the same port in
this Python process before opening the new one. It cannot take a port from a raw
`ser` handle, another kernel or another application; close that owner first.
A failed controller still needs a fresh controller object.

After inspecting the result, start communication in a separate section and cell:

```python
laser.purge_buffers()  # Explicit host TX/RX discard, separate from connection
reply = laser.read(b"?SV")
print(repr(reply))
```

`purge_buffers()` is the single buffer-maintenance method. It requires an open
connection and sends no Verdi instruction. It aborts/discards pending host TX,
then discards RX; it does not wait for transmission.
It does not reset the laser's command parser or clear a controller's failure latch.
Save evidence before discarding bytes after an error; purging does not make a
failed controller reusable. No lesson purges or retries automatically after a failure.

All connecting lessons start with the software-version query `?SV`. Lessons 1–7
use `laser.read(b"?SV")`; lesson 8 introduces `laser.get_value("?SV")` to return
an interpreted value. The native reader consumes each reply through CR/LF, then
the enabled trailing prompt, using `read_until()`. Serial write and receive waits
use `TIMEOUT_S`; it is not a total exchange deadline. `read()` returns payload bytes
with echo, framing, recognized leading notices and prompt removed; it performs no
numeric, boolean or fault-code conversion. Bytes returned by serial reads remain
in `laser.last_transaction["response"]`.

Lesson 2 uses direct sequential `laser.read()` calls. There is no diagnostic pause
setting or added sleep between queries. Its latest saved run contains successful
power and status replies after the version query.

The lessons require the instrument prompt to be enabled
and do not change its echo/prompt settings. Lesson 5 uses `read()` for byte payloads and
`set_power_w()` to store power. The controller formats `P=...` and validates its
acknowledgment; the notebook checks the stored setpoint, physical key OFF, laser
OFF, closed shutter and `SYSTEM OK`. `?K` is the key position; `?L` is a separate laser-state report.
The reported firmware 6.05 combination `?L = 2` / `?F = SYSTEM OK` does not mean
standby: state 2 retains its documented fault-off meaning. Lesson 5 permits
setpoint preparation in state 0 or 2 only with `?K = 0`, shutter closed and
verified clear active faults, and preserves fault history for operator review.
It does not reset that indication or treat it as permission for emission.
Lesson 6 requires `?K = 1` from the start and accepts only ON (1) or remote
standby (0); state 2 stops preparation without a reset.
Lesson 6 uses named controller setters for power, laser state and shutter, with
0.01 W increment validation before opening the port. It compares byte payloads
from `read()` before enabling, opening and closing the shutter. It verifies that
the laser remains ON after shutter closure. Replies
and command acknowledgments remain available as raw byte records.

Saved outputs from the latest operator runs include payload replies and the
[documented six-field transaction records](../docs/API.md#transaction-evidence-and-errors).
They are preserved during documentation updates. Software checks replay all
lessons with simulated serial peers; they do not regenerate or replace hardware
evidence. Notebook 08's shutter-close exception remains in its saved outputs.

An earlier lesson 07 response from 2026-10-27, containing consecutive `level1 set!`
and `level0 set!` notices, is replayed exactly in the parser regression tests.
The completed ten-reading settling study from that earlier session is retained in
[the extracted hardware evidence](data/07_settling_study_20261027T215736Z.json),
including its provenance, completion message and final setpoint transaction.
That archived study used separate opening/acquisition cells and predates the
current merged cell and latest successful notebook run. Keep its provenance
separate from the latest results. Restart the notebook kernel after updating the
driver before beginning a new session.

### Fault replies in lessons 5–6

The controller interprets `SYSTEM OK` as an empty fault list; the raw checks in
lessons 5–6 compare against `b"SYSTEM OK"` directly. Positive codes remain faults,
and empty or unexpected replies stop the sequence. This matches the captured V2
firmware 6.05 reply. For other firmware, inspect raw replies using the
single-owner capture procedure in the [hardware guide](../docs/HARDWARE.md#fault-clear-reply-and-full-status).

### Lesson 6: emission requires an operator-ready system

Lesson 6 assumes the physical key is already ON, with the shutter closed and the
laser either enabled or in remote standby. No key cycling is required. Confirm
cooling, interlocks, approved beam termination and a physical abort procedure.
Readiness checks, fault-history capture, power storage/readback and `RUN`
confirmation all occur with the key ON and shutter closed. A closed shutter does
not establish zero diode current; the laser may already be enabled.

The emission cell rechecks state, faults, shutter, servos and stored power.
If already enabled (`?L = 1`), it skips `L=1`. If in remote standby (`?L = 0`),
it enables once. Fault-off or unexpected states stop without resetting. There
is one `RUN` confirmation at the start of section 9 and no keyboard waits after
the shutter opens. A failure may leave the laser
enabled; use the physical abort procedure when needed. Never use the head safety
shutter as an experimental modulator. Normal completion verifies the shutter
closed, laser ON, key ON, clear active faults and unchanged setpoint. Lesson 6
sends no standby command; disconnecting also leaves that operating state unchanged.

## 3. What to do when a cell stops

**When a cell raises an error, stop.** Do not re-run cells or retry commands. Run
the **Disconnect** cell, then resolve the cause with the operator.

| Message or symptom | Meaning and next action |
| --- | --- |
| Fill in settings / invalid model / invalid watts | A required setting is missing or invalid. Correct it in section 1 and run the cells again from the top. The port has not been opened. |
| Port cannot open | Confirm the selected port, adapter/driver and other connection owners with the operator. Do not scan by opening other ports. If you re-run section 2 while connected, run **Disconnect** first. |
| `invalid fault list` | The no-fault response is unverified or unexpected. Preserve the exact error and establish its meaning; do not assume it means no faults. |
| Wrong key position / unexpected laser state / shutter open / servo not locked / active faults | A required starting condition is absent. The cell stops before writing. Resolve it through the operator's procedure. |
| `Cancelled` | You did not type `SET` or `RUN`. Nothing further was sent. |
| Timeout, malformed reply, readback mismatch or kernel interrupt | Stop. A write may already have executed. Use the physical abort procedure when needed; do not retry or reconnect blindly. |

After a communication failure the controller refuses further commands. Restart
the kernel to begin a new session once the link is understood. The notebooks send
no automatic cleanup writes over an uncertain link. If failure occurs after enable
or shutter opening, **the laser may remain on or the shutter may remain open**.
Interrupting the kernel, closing the notebook and disconnecting the port are not
emergency stops. Use the operator's physical procedure.

Automated notebook tests use fake serial peers. These tests do not
establish the real instrument's timing, wiring, safety or optical calibration.
