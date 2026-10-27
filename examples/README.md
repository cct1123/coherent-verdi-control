# First steps with your Verdi

These are **hardware-only tutorial notebooks** for a human operator. Each notebook
is split into short numbered sections: a few sentences of explanation, then a
small code cell you run and check before moving on. Each notebook is independent.
None uses shared helper code or a simulation switch.

Read-only serial communication on a V2, firmware 6.05, was exercised in lessons
01-03 on 2026-10-26. Emission control, optical behavior and calibration remain
unverified on hardware. Work with your lab's laser operator and follow the
[hardware setup guide](../docs/HARDWARE.md) and [operator manual](../verdi.manual_v5.pdf).

## 1. Install and open the notebooks

Use Python **3.11 or later** and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Open a terminal in the repository folder, then run:

```sh
uv sync
uv run --with jupyter jupyter lab examples
```

`uv sync` creates `.venv` with the controller and pySerial. The second command
starts JupyterLab in that environment, adding Jupyter only for this session, and
opens the `examples` folder in your browser. In VS Code, you can instead open a
notebook and choose the `.venv` interpreter as its kernel.

Connect the computer to the Verdi power supply using RS-232, or a USB-to-RS-232
adapter. A USB-to-TTL UART adapter is a different electrical interface and is not
suitable. Verify cable pinout/DCE orientation against manual Figure 5-1.

[Lesson 0](00_device_discovery.ipynb) finds the port and shows where to read
the model and baud rate. Section 1 of lessons 1–6 lists the settings to enter:
port, model and baud rate, plus the verified no-fault reply for lessons 5–6 and the approved watts for
lessons 5–6. Ask the operator to confirm each value. Keep one serial connection
owner: close other terminal programs, dashboards or notebooks that use this port.
The driver uses 8 data bits, no parity, 1 stop bit and no flow control. It never
scans ports or detects baud automatically.

## 2. Work through the lessons

Do the lessons in order. Lesson 0 opens no port; lessons 1–4 only read. Lessons 5 and 6 change the
instrument and need the operator's approved conditions and limits.

| Lesson | What you do |
| --- | --- |
| [0. Find the port](00_device_discovery.ipynb) | Identify the adapter's port from the operating system's device list. Opens no port and sends nothing. |
| [1. First connection](01_connect.ipynb) | Open the port, read the software version and release the port. |
| [2. Quick status](02_quick_status.ipynb) | Read power, laser state, shutter, keyswitch and active faults. |
| [3. Health check](03_health_check.ipynb) | Inspect 41 queries in nine subsystem sections (`?DIOS` skipped after device rejection), preserving byte payloads without changing settings. |
| [4. Pre-key-on readiness](04_pre_key_on_readiness.ipynb) | Check warm-up, refresh serial readiness readings and verify front-panel and physical conditions. Queries only. |
| [5. Set power in standby](05_set_power.ipynb) | Check standby, closed shutter and no faults, then store and verify a setpoint. Never enables or opens the shutter. |
| [6. One controlled session](06_controlled_session.ipynb) | Check readiness, store power, enable, open the safety shutter once, read power, close the shutter and verify standby. |

Run the cells one at a time (Shift+Enter) and read each result before the next.
Creating the controller sends nothing. Every connecting lesson has two separate
sections: **Open the serial port** and **Start serial communication**. The first
cell calls only `connect()` and prints its Boolean result. Inspect it before
proceeding. `True` confirms the local port opened; it does not confirm a laser reply
or readiness. Opening errors raise an exception. The communication section
explicitly purges host queues once before its first query. The
last cell, **Disconnect**, releases the port. Cells that write ask you to type `SET` or
`RUN`; any other answer cancels. Those confirmations record your intended action.
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

All connecting lessons use `laser.read(b"?SV")`. The method consumes the full
CR/LF reply and terminal prompt before returning the payload bytes, with echo
and framing removed. The full wire reply stays in `laser.last_transaction["response"]`.
The lessons require the instrument prompt to be enabled
and do not change its echo/prompt settings. No fault-clear text is needed to
capture raw status bytes. Lesson 5 uses `write(b"P=...")` and compares byte payloads explicitly to verify
the stored setpoint, standby, closed shutter and the verified no-fault reply.
Lesson 6 also uses raw `read()`/`write()` calls, explicitly comparing byte
payloads before enabling, opening, closing and returning to standby. Replies
and command acknowledgments remain available as raw byte records.

Saved outputs remain unchanged from the original hardware runs. In lessons 01–02,
the saved replies include framing and the transaction records contain historical
fields; current `read()` returns only the payload and current records use the
[documented six fields](../docs/API.md#transaction-evidence-and-errors).
Lessons 05–06 have no saved hardware outputs. Software checks replay all lessons
with simulated serial peers; they do not regenerate or replace the hardware evidence.

### Before writing in lessons 5–6: establish the fault-clear payload

The manual gives `SYSTEM OK` for fault **history**, `?FH`, but leaves the
no-active-fault reply to `?F` unspecified. Do not guess it or copy a simulator's
value. Have the operator establish the actual reply and its meaning using the
single-owner capture procedure in the [hardware guide](../docs/HARDWARE.md#fault-clear-reply-and-full-status).

Enter it as `ACTIVE_FAULT_CLEAR_REPLY` in section 1: payload bytes in both lessons
(e.g. `b"SYSTEM OK"` only if verified). `None` means "not
configured". It is not a reply sent to the instrument. An empty reply is not
supported by the current parser.

### Lesson 6: emission requires an operator-ready system

Have the operator complete warmup and establish the correct key-ON / remote-standby
configuration with shutter closed. **Turning the physical key can itself enable
the laser**; do not turn it merely to satisfy a software check. Confirm cooling,
interlocks, approved beam termination and a physical abort procedure first.

The emission sequence is one cell, so nothing waits for keyboard input while the
laser is enabled or the shutter is open. Never use the head safety shutter as an
experimental modulator.

## 3. What to do when a cell stops

**When a cell raises an error, stop.** Do not re-run cells or retry commands. Run
the **Disconnect** cell, then resolve the cause with the operator.

| Message or symptom | Meaning and next action |
| --- | --- |
| Fill in settings / invalid model / invalid watts | A required setting is missing or invalid. Correct it in section 1 and run the cells again from the top. The port has not been opened. |
| Port cannot open | Confirm the selected port, adapter/driver and other connection owners with the operator. Do not scan by opening other ports. If you re-run section 2 while connected, run **Disconnect** first. |
| `invalid fault list` | The no-fault response is unverified or unexpected. Preserve the exact error and establish its meaning; do not assume it means no faults. |
| Not in standby / shutter open / servo not locked / active faults | A required starting condition is absent. The cell stops before writing. Resolve it through the operator's procedure. |
| `Cancelled` | You did not type `SET` or `RUN`. Nothing further was sent. |
| Timeout, malformed reply, readback mismatch or kernel interrupt | Stop. A write may already have executed. Use the physical abort procedure when needed; do not retry or reconnect blindly. |

After a communication failure the controller refuses further commands. Restart
the kernel to begin a new session once the link is understood. The notebooks send
no automatic cleanup writes over an uncertain link. If failure occurs after enable
or shutter opening, **the laser may remain on or the shutter may remain open**.
Interrupting the kernel, closing the notebook and disconnecting the port are not
emergency stops. Use the operator's physical procedure.

These notebooks are tested with fake serial peers only. Testing the code does not
establish the real instrument's timing, wiring, safety or optical calibration.
