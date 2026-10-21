# Protocol reference and implementation boundary

Authoritative source: [Coherent Verdi V-2/V-5/V-6 Operator's Manual](../verdi.manual_v5.pdf),
part **0171-750-00, Rev IB**, © 08/2005. The supplied PDF has 130 pages and SHA-256
`d4a7a8a2a1e0c678bb00a5fd70be6ea1d649be063ab752de485a59daa3103f73`.
Printed section 5 corresponds to PDF pages 49–58. No newer firmware behavior is assumed.

## Wire contract

- Section 5, pp. 5-1–5-4: ASCII instruction terminated by CR/LF or semicolon;
  this library emits **CR/LF only**, one instruction per transaction.
- `PRINT ` and `?` are equivalent query prefixes; `:` and `=` are equivalent
  command delimiters (p. 5-3). `read()`/`capture()` accept short queries and
  `PRINT`/`?` long names. `command()` accepts the Table 5-3 long/short names and
  either delimiter. The controller normalizes these to short queries and `=`
  commands before transmission; the simulator receives these canonical forms.
  Inputs are uppercase ASCII without terminators; batching is rejected.
- Replies end in CR/LF; wait for a complete reply before the next instruction.
- Table 5-1, p. 5-2: a successful command replies with an empty CR/LF when echo
  and prompt are off. There is no documented `OK` command acknowledgment.
- Table 5-1 provides four single-line layouts combining optional `Verdi>` prefix
  and echoed instruction. The parser accepts these without writing mode settings
  during connection. Additional lines, control bytes and malformed replies fail.
- Error prefixes: `RANGE ERROR:`, `Command Error:`, `Query Error:`. A device error
  preserves the instruction and reply. It is not retried.
- Multiple results use `&`. Faults are returned as integer lists; unknown positive
  codes are preserved, never discarded or treated as clear.
- Table 5-2: 8 data bits, no parity, 1 stop bit, no hardware/software handshaking.
  Baud rates: 1200, 2400, 4800, 9600, **19200 factory default**, 38400, 57600.
- The port is DCE; only pins 2, 3, 5 are used. No electrical/cable validation has
  occurred. No model-identification query is specified; callers select V2/V5/V6.

The 1 s default transaction deadline, 4096-byte response ceiling, strict decimal
parser and connection failure policy are **software choices**, not manufacturer
response-time or firmware guarantees. A partial response, I/O error or lost
acknowledgment makes the serial session unusable. The command may have executed.
There is no automatic retry, input-buffer purge, mode normalization or state replay.

Before transmitting and after reading a complete frame, the serial adapter checks
`in_waiting`. Unexpected queued bytes reject the transaction and latch failure;
they are never silently discarded. This prevents an already-buffered extra line
from becoming the next query's reply. It cannot identify arbitrarily delayed,
untagged replies or eliminate OS/adapter buffering races. The checks establish no
quiet-time guarantee, and reopening does not establish resynchronization.

Each attempted transaction records consumed bytes, UTC start, duration, settings,
queued-byte count and outcome in `last_transaction`. Exchange errors carry an
independent record in `VerdiError.transaction`. Command failures distinguish
`not_sent` from `unknown`; acknowledgment and documented rejection are explicit
outcomes. There is no automatic retry or replay.

## Complete Table 5-3 command coverage

All 16 distinct write operations are exposed, counting LIGHT/POWER as one
operation and PRINT as a query prefix. Aliases share the same validation,
write permission and failure policy as the typed methods below.

| API | Wire form | Source / meaning |
| --- | --- | --- |
| `set_power_w(watts)` | `P=nn.nnnn` | Table 5-3, pp. 5-5–5-6; light regulation in W |
| `stop()` | `L=0` | p. 5-5; STANDBY overrides the ON keyswitch |
| `start()` | `L=1` | p. 5-5; key must be ON; resets faults and clears fault history |
| `set_shutter(open=...)` | `S=0/1` | p. 5-6; closes/opens the head shutter |
| `set_echo(enabled=...)` | `E=0/1` | p. 5-5; change applies to the following command |
| `set_prompt(enabled=...)` | `PROMPT=0/1` | p. 5-6; **0 enables, 1 disables** prompt; `>=n` is its alternate spelling |
| `set_baudrate(baudrate)` | `B=n` | p. 5-5 and pp. 5-3–5-4; persistent device setting, followed by host reconfiguration |
| `chiller_on()` | `CHILLER=ON` | p. 5-5; only for Coherent chiller part 1037271 |
| `set_chiller_temperature_c(celsius)` | `CHILLER=XX.X` | p. 5-5; rounded to one decimal; physical range unspecified |
| `exit_screen()` | `EXIT=1` | p. 5-5; EXIT button |
| `flash()` | `FL=1` | p. 5-5; flash below lasing threshold for etalon recentering |
| `knob_down()` | `KNOBDN=1` | p. 5-5; KNOB DOWN button |
| `set_lbo_heater(enabled=...)` | `LBOH=0/1` | p. 5-5; cool down / heating |
| `optimize_lbo()` | `LBOOPT=1` | p. 5-5; initiate optimization |
| `set_front_panel_lock(value)` | `LFP=n` | p. 5-5; integer operand, valid values and unlock mapping unspecified |
| `menu_down()` | `MENUDN=1` | p. 5-5; MENU DOWN button |
| `menu_select()` | `SELECT=1` | p. 5-5; MENU SELECT button |
| `menu_up()` | `MENUUP=1` | p. 5-5; MENU UP button |

Writes require `VerdiController(..., allow_writes=True)`. Construction, connection,
disconnection and automatic monitoring never issue commands. The optional GUI can
queue explicit writes only when launched with `--allow-writes`. Mode writes are optional explicit
operations; they are not connection prerequisites. `disconnect()` only releases the
communication handle and **does not place the laser in STANDBY**.

`command("LBO HEATER:1")`, for example, calls the same validated path as
`set_lbo_heater(enabled=True)`. All Table 5-3 aliases are accepted, including
`POWER`, `LIGHT`, `>=n` and the table's bare `LBOOPT` spelling (normalized to
`LBOOPT=1`). Section 5's `SERIAL BAUDRATE=n` spelling is accepted as well.
This is a catalogue allowlist; there is no unrestricted raw-write escape hatch.

Baud changes send `B=n` and receive the acknowledgment at the original baud,
then update the host port under the same lock. The manual specifies host
reinitialization but not the acknowledgment baud or transition timing. Firmware
that switches before replying may time out and retire the session. An unknown
outcome is never retried; establish the actual device baud independently before
using a fresh controller. A host-reconfiguration failure also retires the session;
its transaction retains `acknowledged` plus the host error. The recorded baud is
the rate of the command exchange; following transactions use the new rate.

The chiller's temperature range and `LFP=n` valid values are not defined by this
manual. The API checks finite decimal temperature and integer panel-lock syntax,
with the existing instruction-length bound; firmware may reject a value. It does
not assume a physical chiller limit or that a particular LFP operand unlocks the
panel. Only the documented chiller `ON` and numeric forms are supported, not OFF.
Service sequencing and physical completion remain the application's responsibility.

## Query coverage

All **42** queries from Table 5-4 are accepted by `read()` as short strings or
their documented long names, prefixed with `?` or `PRINT `.
Direct parsing groups in [controller.py](../src/coherent_verdi/controller.py) distinguish
raw text, documented integer codes and decimal numbers. Source pages are below;
independent test vectors retain units and long names as manual reference data.

For commissioning, `capture()` accepts the same query catalogue only on a
read-only controller. It enforces ASCII and a single CR/LF frame, permits an empty
payload, and removes documented echo/prompt decoration without interpreting
values or faults. Documented device errors are still rejected and recorded.
The returned transaction record is evidence, not a claim about device health.
CLI `commission` exposes this path as JSONL;
normal query/status parsing remains unchanged.

| Source | Queries |
| --- | --- |
| 5-6 | `?ACAD`, `?BT`, `?B`, `?C`, `?D1C`, `?D1HST`, `?D1H`, `?D1PC`, `?D1RCF`, `?D1RCM` |
| 5-7 | `?D1SS`, `?D1ST`, `?D1TD`, `?D1T`, `?D15V`, `?DIOS`, `?ED`, `?ESS`, `?EST`, `?ET` |
| 5-8 | `?F`, `?FH`, `?HH`, `?K`, `?L`, `?LBOD`, `?LBOH`, `?LBOOS`, `?LBOST` |
| 5-9 | `?LBOSS`, `?LBOT`, `?P`, `?LRS`, `?M`, `?PSH`, `?SP`, `?S`, `?SV`, `?VST`, `?VT` |
| 5-10 | `?VD`, `?VSS` |

Temperatures, current, hours and power are finite floats with documented units.
States accept only their documented integer codes. Version, servo-drive values,
photocell values, reference voltage representation, aging factor and `?ACAD`
remain **raw text** where the manual does not fully specify units or layout.
No invented second-diode query is added: section 2 describes one diode assembly.
For diode/LBO servo queries, code 5 is excluded for V6 and code 6 is excluded
for V2 (pp. 5-7, 5-9); these mismatches raise `VerdiError`. V5 can mean standard
V5 or V5 UNO, so both codes remain representable until its variant is identified.

The complete independent query/unit/code vectors are in
[test_protocol.py](../tests/test_protocol.py), `MANUAL_QUERIES`. The driver returns
integer fault codes without metadata wrappers. Unknown positive
codes remain faults. The reference below covers the union of Tables 5-4 and 6-1;
code 47 is listed in Table 5-4 but omitted from Table 6-1.

## Fault-code reference

| Code | Manual meaning |
| --- | --- |
| 1 | Laser head interlock / emission lamp fault (manual labels conflict) |
| 2 | External interlock fault |
| 3 | Power supply cover interlock fault |
| 4 | LBO temperature fault |
| 5 | LBO not locked at set temperature |
| 6 | Vanadate temperature fault |
| 7 | Etalon temperature fault |
| 8 | Diode 1 temperature fault |
| 10 | Baseplate temperature fault |
| 11 | Heatsink 1 temperature fault |
| 16 | Diode 1 over current fault |
| 18 | Over current fault |
| 19 | Diode 1 under voltage fault |
| 21 | Diode 1 over voltage fault |
| 25 | Diode 1 EEPROM fault |
| 27 | Laser head EEPROM fault |
| 28 | Power supply EEPROM fault |
| 29 | Power supply-head mismatch fault |
| 30 | Battery requires service |
| 31 | Shutter state mismatch |
| 40 | Head-diode mismatch fault |
| 47 | Vanadate 2 temperature fault |

## Uncertainty register

1. **No active faults:** `SYSTEM OK` is explicit for `?FH`; the clear reply for
   `?F` is not explicit. Physical controllers therefore reject clear-looking
   replies unless `active_fault_clear_reply` matches the exact
   text independently verified for that firmware. Its default is None;
   malformed/unverified data invalidates the session. Positive fault codes/lists
   cannot be configured as clear tokens. Empty replies can be captured for
   evidence but remain unsupported by normal fault parsing.
   Simulated controllers alone default to the fixture convention `SYSTEM OK`.
   Do not infer physical compatibility from that simulator convention or from ?FH.
2. **Echo framing:** the implementation follows Table 5-1's one-line layouts.
   Real character echo timing, any separately terminated echo lines and prompt
   transition ordering require capture; the parser deliberately fails on layouts
   beyond the table instead of consuming arbitrary lines.
3. **Power limits:** Table 2-1 rates models at 2/5/6 W. Those ratings are used as
   conservative software ceilings, not claimed firmware maximum setpoint ranges.
   A caller can lower the ceiling. Chiller temperature control is exposed as
   documented; no undocumented current, crystal-temperature or calibration
   tuning commands are added.
4. **Shutter behavior:** Table 4-3 (p. 4-9) describes idle at minimum power while
   closed and return/ramp after opening. The minimum power and ramp rates are not
   specified. The simulator's zero closed-shutter power is a synthetic fixture;
   **it does not establish the actual `?P` reading with the shutter closed**.
   The head shutter is used only as a safety shutter, never periodic modulation.
5. **Timing and faults:** no plant model, firmware latency bound, physical fault
   response timing, interlock integrity or safety certification follows from tests.
   Manual p. 4-2 specifies the LBO-not-locked fault for key ON during cold-start
   warmup. The simulator has no warmup model; actual recovery/latching and any
   automatic resumption require physical observation.
6. **Fault-code conflict:** Table 5-4 calls code 1 a laser head interlock fault;
   Table 6-1 and Chart 5 call it an emission lamp fault (pp. 6-2, 6-12). The fault-code
   reference above preserves both labels; verify against device firmware/Coherent support.
   Neither label establishes a laser-head cover interlock: p. 6-1 explicitly warns
   that removing the head cover has no protective cover interlock.
7. **Safety timing and limits:** indicators precede possible emission by approximately
   30 s (p. 1-3); cold-start servo stabilization can take 30 minutes (pp. 4-2–4-3).
   There is no documented per-command delay to substitute for readiness observation.
   The 0.01 W alignment setting (pp. 4-2/4-4) is not a specified RS-232 lower limit.
   Table 2-1's stability figures require warmup and measurement conditions; tests
   do not establish accuracy, calibration, safety or the full firmware setpoint range.

## Software references

The serial adapter's port-less construction, explicit open, read/write timeouts
and disabled flow control follow the [pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html).
The optional client uses Dash callbacks and `dcc.Interval` as described by
[Dash live updates](https://dash.plotly.com/live-updates). Browser refreshes read
cached monitor data or submit bounded requests to the existing acquisition caller;
they do not create additional device polling workers.
