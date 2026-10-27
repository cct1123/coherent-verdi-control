# Verdi GUI guide

The optional Dash dashboard uses one controller connection for its overview,
queries and explicit commands. It starts disconnected, with monitoring paused and writes disabled unless explicitly
enabled at launch. Connection status, monitoring status and reported laser state
are shown separately. After connection, the header identifies SIMULATOR or HARDWARE.
The whole dashboard, including the laser panel, follows the system light/dark
preference. An explicit Bootstrap `data-bs-theme="light"` or `"dark"` takes precedence.

The operator confirmed successful runs of notebooks 00–07 on the V2 / firmware
6.05 setup on 2026-10-27; notebook 08 remains unresolved. See the
[hardware validation record](HARDWARE.md#validation-record-2026-10-27).
GUI validation uses serial fakes
and browser simulation. Notebook runs do not establish GUI hardware operation,
optical accuracy or calibration.

## Launch

From the repository root:

```sh
uv sync --extra gui
uv run verdi gui
```

Open [http://127.0.0.1:8050](http://127.0.0.1:8050/). Without a global serial
`--port`, the Source field defaults to Simulator. Click **Connect**, then
**Start monitoring** to explore the synthetic readings. Its Bootstrap stylesheet is bundled, so the
running dashboard needs no internet connection.

For a first hardware session, use the known port, model and front-panel baud:

```sh
uv run verdi --port COM5 --model V2 --baudrate 19200 gui
```

CLI connection options only prefill the form; they do not open a port. You can
also start with `uv run verdi gui`, select Hardware and enter the known port,
model and baud in the GUI. The form also shows device prompt mode and serial
timeout, initially filled from CLI options. No automatic port discovery or model
detection is used.

**Device prompt** describes the laser's existing mode; choosing Enabled or Disabled
changes the reader configuration, not the instrument. When enabled, the reader
consumes reply CR/LF and then the exact trailing prompt. **Serial timeout / s** configures
serial write and receive waits (0.001–60 seconds). Reply lines, notices and the
prompt use separate `read_until()` calls with that configured timeout, so a full
exchange may take longer. Echo is accepted without changing its instrument mode.

Click **Connect** to open the port without queries or settings. Monitoring remains
paused. Select `?SV` and click **Capture bytes**, then inspect **Transaction evidence**.
Capture `?F` separately and inspect its payload with the operator.
Fault parsing accepts `SYSTEM OK` as an empty list and preserves positive codes.
Capture is available only in read-only
sessions and does not interpret fault clearance.

For normal monitoring:

```sh
uv run verdi --port COM5 --model V2 --baudrate 19200 gui --port 8051
```

Click Connect, then Start monitoring.
Open port 8051 in the browser for this example. The global `--port COM5` selects
the serial device; the `--port` after `gui` selects the HTTP listener. Keep one
serial owner and close any notebook connection before launching the GUI.

## Connection and monitoring controls

| Control | Behavior |
| --- | --- |
| Connect / Disconnect | One button: opens the selected connection, then changes to Disconnect. Disconnect cancels queued work, finishes in-flight I/O and releases the connection while keeping the GUI open. |
| Close application | Releases the connection and stops the worker and HTTP server. |
| Start monitoring | Starts repeated reads of power, setpoint, diode current, temperatures and operating state. |
| Pause monitoring | Pauses automatic overview reads; explicit query actions remain available. |
| Apply interval | Applies the overview interval of 0.1-3600 seconds; default 1 second. Each overview sends 14 queries sequentially, with no extra wait between those queries. |

A serial cycle can exceed the target interval. Live readings and sample age show
the last completed overview. Power history is cleared on connection changes;
the plot contains measured power and its setpoint.
The connection button is disabled while connecting or disconnecting. Connecting
sends no device instructions; monitoring still starts separately.
All connection fields are locked while connected or changing connection. Disconnect
before editing the prompt or timeout. Simulator connections use the selected
prompt mode so echo and prompt behavior can be explored without hardware.

Model labels, power limits and knob range follow the connected controller.
Connection changes clear the readiness switch and reject requests sent from an
older browser view; let the view refresh before submitting a new action.

Connect does not prove that the laser answered. A transport failure stops the
controller session; disconnect and connect again to create a new session once
the link is understood. The GUI does not take over another controller-owned port.
Disconnect and Close application do not place the laser in standby or close its shutter.

## Read values and inspect bytes

Queries and live readings appear above the front panel so a single exchange can
be inspected before starting monitoring. Pause monitoring when isolating a query;
otherwise overview queries also use the shared connection. The newest query's
result and full action record appear beside its controls. Its Transaction evidence
summary shows the received byte count; failed and rejected records expand there
automatically. An empty response is explicitly shown as zero received bytes.
Opening or closing the evidence remains under operator control across refreshes;
a new failed query opens its evidence automatically.
The Activity section retains the other action records.

Accepted submissions derive their queued/completed status from the live action
record. Local validation messages appear directly below the connection controls;
a completed request no longer leaves a stale "Queued" message behind.

| Control | Result |
| --- | --- |
| Read value | Interprets a selected query, including numeric values and state-code labels. |
| Capture bytes | Preserves the byte payload and full wire reply without interpreting the value; read-only sessions only. |
| Diagnostics + fault history | Reads software version, operating hours and fault history; does not clear faults. |

The selector lists all 42 queries in the manual. Availability depends on firmware:
the reference V2 rejected `?DIOS`, so notebook 03 excludes it. The remaining
41 queries completed, including the compound `?ACAD` payload `b"0.080.0"`.
The application preserves that compound payload rather than splitting or guessing
its meaning. Optional queries are issued only when selected; overview polling
uses its own fixed set of 14 queries.

The Python byte API returns formatted payloads from `read(b"?SV")`, for example
`b"6.05"`; `write()` and `command()` return the full reply. Each transaction waits
for reply CR/LF and, when enabled, the trailing prompt. The GUI uses
explicit typed helpers for displayed values and named setters for commands.
Recognized firmware notices and partial replies remain available in Transaction
evidence. Long error text wraps within the view. The live overview displays diode
current to 0.01 A so hundredths present in the readback are not hidden by rounding.

## Overview and front panel

| Health | Meaning |
| --- | --- |
| NO DATA | No overview has completed. This is expected before monitoring starts. |
| LIVE | The latest overview completed and is fresh; this does not establish readiness to emit. |
| STALE | The last successful overview is too old for ordinary writes. |
| ERROR | The most recent overview failed; inspect its error and transaction evidence. |

The front-panel display is synthesized from serial queries. It does not mirror
the laser's actual menu screen. The keyswitch indicator is read-only. AC ON
indicates a live serial response, and LASER EMISSION follows the reported laser
state; neither measures optical output. Lamps are hollow when the overview is
not live.

POWER ADJUST edits the target only; **SET POWER** sends it. POWER LEVEL 1/2
presets are stored in this browser. Targets, presets and knob edits use **0.01 W
increments**. Finer targets are rejected before queueing or device I/O, including
old browser presets. Knob edits stay at or below the configured ceiling; a ceiling
between steps uses the highest valid step below it. MENU UP/DOWN, SELECT and EXIT remain disabled:
the current menu and selection cannot be read over RS-232. Navigation actions,
including KNOB DOWN, are unavailable in the Service menu and rejected by the GUI
request queue. SHUTTER OPEN opens only
when the browser and current live overview both report closed; otherwise it
requests closure. Overview refreshes preserve unsent edits.

## Enable explicit commands

Add write permission and your site-approved power ceiling after `gui`:

```sh
uv run verdi --port COM5 --model V2 --baudrate 19200 gui --allow-writes --power-limit-w 0.5
```

The example ceiling is a software limit to replace for your setup. Changing a
setpoint does not enable the laser or open its shutter. Start/reset faults and
shutter-open require the operator readiness switch. Start also clears fault
history; inspect it beforehand. Use [lesson 04](../examples/04_check_readiness.ipynb)
and the [hardware procedure](HARDWARE.md) for preparation.

Ordinary writes require a fresh overview. Standby and shutter-close can be
requested without fresh telemetry while the connection remains usable. They take
priority over queued ordinary writes, but cannot interrupt an exchange already
in progress. Service controls include heater, optimization, FLASH, chiller,
panel-lock, baud, echo and prompt settings. Their availability is not a readiness
check or confirmation that an operation completed physically.

Acknowledged hardware baud changes and acknowledged prompt-mode changes update
the form and are retained for the next Connect.
The connection form reflects the updated baud. If another application changes
the link settings, establish the current settings independently before reconnecting.

## Results and transaction evidence

An action is first queued, then executed by the single acquisition worker.
Results distinguish acceptance from readback:

| Result | Meaning |
| --- | --- |
| acknowledged | The command reply was accepted; no matching readback has been established. |
| verified | A documented getter reported the requested value. |
| mismatch / readback_failed | Readback disagreed or could not be obtained; inspect the evidence. |
| rejected | Local validation or a complete device reply rejected the action. |
| failed | Communication or execution failed; a transmitted command may have executed. |
| cancelled | A queued action was cancelled before execution. |

**Transaction evidence** retains the controller's six fields: `instruction`,
`request`, `response`, `payload`, `outcome` and `error`. Request and full response
bytes are represented as hexadecimal in the GUI's JSON view; byte payloads also
retain `payload_hex`. Query/action acquisition timestamps belong to the GUI cache,
not the controller transaction record. See the [record format](API.md#transaction-evidence-and-errors).

A timeout retires the controller session. The GUI does not retry a write or send
cleanup commands over the failed connection. Its heartbeat watchdog disables
write groups after 10 seconds without a server heartbeat; it cannot stop a laser
independently. Close application or Ctrl+C drains acquisition and releases the port. It does not close
the shutter or place the laser in standby. Follow the operator's physical abort
procedure when required.

An unexpected acquisition-worker failure also releases the port and stops the
server; the CLI reports the error with exit code 2.

For worker ownership and custom integrations, see the
[monitoring API](API.md#optional-monitoring) and [developer walkthrough](DEVELOPMENT.md).
