# Five first steps with your Verdi

These are **hardware-only Python scripts** for a human operator. Each script is
independent: it imports the installed controller, shows every device command and
closes its serial connection before returning. There are no notebooks, shared
helper scripts or simulation switches.

Read each script before running it. Physical communication and optical behavior
have not yet been validated with this package. Work with your lab's laser operator
and follow the [hardware setup guide](../docs/HARDWARE.md) and
[operator manual](../verdi.manual_v5.pdf).

## 1. Install and find the settings

Use Python **3.11 or later**. Open a terminal in the repository folder, then run:

```sh
python -m pip install .
```

This installs the Python controller and pySerial. No Jupyter or Dash is needed.
Use the same Python environment to run the examples.

Connect the computer to the Verdi power supply using RS-232, or a USB-to-RS-232
adapter. A USB-to-TTL UART adapter is a different electrical interface and is not
suitable. Verify cable pinout/DCE orientation against manual Figure 5-1.

Ask the operator to confirm these values, then edit the settings near the top of
each script you use:

| Setting | What to enter |
| --- | --- |
| `PORT` | Your known serial port, for example `"COM3"` on Windows or `"/dev/ttyUSB0"` on Linux. In Windows, the adapter's COM number is shown in Device Manager under Ports. |
| `MODEL` | `"V2"`, `"V5"` or `"V6"`, matching the actual laser. The version query cannot discover this for you. |
| `BAUDRATE` | The baud selected on the front panel. `19200` is the factory default; verify it rather than assuming. |
| `ACTIVE_FAULT_CLEAR_REPLY` | Lessons 2–5 need the exact independently verified no-active-fault text returned by `?F`, as a Python string. See below. |
| `TARGET_W` | Lessons 4–5 only: the operator-approved power request in watts, as a number. |
| `POWER_LIMIT_W` | Lessons 4–5 only: the site's maximum permitted setpoint for this session, in watts. It may be lower than the model rating. |

Keep one serial connection owner: close other terminal programs, dashboards or
scripts that use this port. The driver uses 8 data bits, no parity, 1 stop bit and
no flow control. It never scans ports or detects baud automatically.

## 2. Run the lessons

Run the commands below **one at a time** from the repository folder. The first
three only read. Lessons 4 and 5 change the instrument and need the operator's
approved conditions and limits.

| Lesson | Command | What it does |
| --- | --- | --- |
| [1. First connection](01_connect.py) | `python examples/01_connect.py` | Opens the selected port, reads one software-version query and releases the port. |
| [2. Read status](02_read_status.py) | `python examples/02_read_status.py` | Displays state, power, temperatures and active fault codes. |
| [3. Diagnose faults](03_read_faults.py) | `python examples/03_read_faults.py` | Displays active faults and history without clearing either or restarting the laser. |
| [4. Set power in standby](04_set_power.py) | `python examples/04_set_power.py` | Checks standby/closed shutter/no faults, changes the setpoint and verifies the result. Never enables or opens the shutter. |
| [5. One controlled session](05_controlled_session.py) | `python examples/05_controlled_session.py` | Checks readiness, sets power, enables, opens the safety shutter once, samples power, closes the shutter and verifies standby. |

Each script prints its connection settings and asks you to type `CONNECT` before
opening a port. Check them carefully. Any other answer cancels. Lessons 4 and 5
also ask for `SET` or `RUN` before the write sequence. These are confirmations
of your intended actions, not replacements for the lab's operating procedure.

### Lesson 1: understand a query

`laser.read("?SV")` means "ask the instrument for its software version." The `?`
prefix requests information. Compare the reported version with the instrument.
If it times out or produces unexpected framing, stop and resolve the link before
running further lessons. A successful version query alone does not validate all
other commands or the physical laser system.

`with laser:` opens the connection. Leaving that block releases the port even
when an error occurs. **Releasing a port does not shut down a laser.**

### Before lesson 2: establish the fault-clear text

The manual gives `SYSTEM OK` for fault **history**, `?FH`, but leaves the
no-active-fault reply to `?F` unspecified. Do not guess it or copy a simulator's
value. Have the operator establish the actual reply and its meaning using the
single-owner capture procedure in the [hardware guide](../docs/HARDWARE.md#fault-clear-reply-and-full-status).

Replace `ACTIVE_FAULT_CLEAR_REPLY = None` with that verified string. `None` means
"not configured"; it is not a reply sent to the instrument. An empty reply is not
supported by the current parser. If the reply is unknown, use lesson 1 and resolve
this question before full status or write operations.

### Lessons 2 and 3: understand the readings

- Laser state codes are `0` standby, `1` on and `2` fault. Shutter/key values are
  displayed as `True` or `False`, meaning the reported state is on/open or off/closed.
- `set_power_w` is the requested setpoint; `power_w` is the instrument's reported
  power. They are different quantities. A closed shutter does not establish a
  particular reported power or diode current.
- Temperatures are degrees Celsius (`degC`), current is amperes (`A`) and power is
  watts (`W`). Compare values with the front panel and the operator's expectations.
- `status()` returns a dictionary: `status["power_w"]` selects its power value.
  It uses 14 sequential queries; values are not all acquired at the same instant.
- Fault lists contain integer codes. `[]` means no faults reported in that list.
  Keep unknown codes and look up meanings in [the protocol reference](../docs/PROTOCOL.md#fault-code-reference).
  A clear history does not prove the current system is safe.

### Lesson 4: a stored request is not optical output

Fill in both watt settings with values approved for your setup; no example watts
are supplied as safe defaults. The driver checks the model ceiling, your lower
site ceiling and the four-decimal value sent to the instrument.

`set_power_w()` sends the power request. `read("?SP")` checks the stored setpoint,
while `read_power_w()` would query reported optical power. The script requires
standby and a closed shutter, then verifies those states and absence of active
faults after the write. Confirm firmware readback precision before using its exact
four-decimal comparison. **The new setpoint remains stored after the script ends.**

### Lesson 5: emission requires an operator-ready system

Have the operator complete warmup and establish the correct key-ON / remote-standby
configuration with shutter closed. **Turning the physical key can itself enable
the laser**; do not turn it merely to satisfy a software check. Confirm cooling,
interlocks, approved beam termination and a physical abort procedure first.

The script requires all four temperature servos to report `LOCKED` (code `1`).
It reads fault history before `start()`, because enable also resets faults/history.
It then performs one sequence without waiting for keyboard input while enabled.
The immediate power sample does not prove optical settling, stability or calibration.
Never use the head safety shutter as an experimental modulator.

On normal completion, shutter closure and standby are read back and verified.
The target remains stored. Standby leaves temperature servos powered; complete
heater/cooling shutdown follows the manual, separately from this script.

## 3. What to do when something stops

| Message or symptom | Meaning and next action |
| --- | --- |
| Edit settings / invalid model / invalid watts | A required setting is missing or invalid. Correct it before connecting; the scripts reject these inputs before opening. |
| Port cannot open | Confirm the selected port, adapter/driver and other connection owners with the operator. Do not scan by opening other ports. |
| `invalid fault list` | The no-fault response is unverified or unexpected. Preserve the exact error and establish its meaning; do not assume it means no faults. |
| Not in standby / shutter open / servo not locked / active faults | A required starting condition is absent. The script stops before writes. Resolve it through the operator's procedure. |
| Timeout, malformed reply, readback mismatch or Ctrl+C | Stop. A write may already have executed. Use the physical abort procedure when needed; do not retry or reconnect blindly. |

The examples stop subsequent commands after a failed step. They release
communication without sending automatic cleanup writes over an uncertain link.
If failure occurs after enable or shutter opening, **the laser may remain on or
the shutter may remain open**. Software exit, Ctrl+C and port disconnection are
not emergency stops. Use the operator's physical procedure.

These examples are tested with fake serial peers only. Testing the code does not
establish the real instrument's timing, wiring, safety or optical calibration.
