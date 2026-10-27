# Protocol reference and implementation boundary

Authoritative source: [Coherent Verdi V-2/V-5/V-6 Operator's Manual](../verdi.manual_v5.pdf),
part **0171-750-00, Rev IB**, © 08/2005. The supplied PDF has 130 pages and SHA-256
`d4a7a8a2a1e0c678bb00a5fd70be6ea1d649be063ab752de485a59daa3103f73`.
Printed section 5 corresponds to PDF pages 49–58. Captured firmware behavior is
identified separately below; it is not treated as an amendment to the manual.

## Wire contract

- **Encoding policy:** section 5-1 specifies ASCII instructions; Table 5-1 shows
  ASCII response layouts. Table 5-2 specifies 8 data bits, no parity and one stop
  bit, with no flow control. Eight data bits do not specify an extended character
  set. The manual identifies no cp1252, Latin-1 or UTF-8 response encoding.
  The saved V2 firmware 6.05 read-only notebooks contain only ASCII-compatible
  replies. The [health survey](../examples/03_health_check.ipynb) records 41
  distinct query payloads; `?DIOS` was not captured. No saved receive
  byte has its high bit set. These observations support ASCII as the decoding
  baseline but do not distinguish encodings that share the ASCII subset or
  establish every possible firmware reply.
  Unknown high-bit payloads remain bytes; they are
  neither decoded using a guessed code page nor modified by stripping high bits.
  Raw capture always
  preserves payload bytes, and typed measurements retain their value checks.
- Section 5, pp. 5-1–5-4: ASCII instruction terminated by CR/LF or semicolon;
  this library emits **CR/LF only**, one instruction per transaction.
- `PRINT ` and `?` are equivalent query prefixes; `:` and `=` are equivalent
  command delimiters (p. 5-3). `get_value()`/`get_capture()` accept short queries and
  `PRINT`/`?` long names and normalize them to short queries.
  Byte `read()`/`write()`/`command()` calls preserve supplied bytes; settings use
  canonical short names and `=`. Named setters construct these canonical forms.
  Instructions omit terminators; batching is rejected.
- Replies end in CR/LF; wait for a complete reply before the next instruction.
- Table 5-1, p. 5-2: a successful command replies with an empty CR/LF when echo
  and prompt are off. There is no documented `OK` command acknowledgment.
- Table 5-1 provides four CR/LF-terminated layouts combining an optional leading
  `Verdi>` and instruction echo. Payload interpretation removes matching echo and
  prompt framing from a completed response.
- V2 firmware 6.05 captures show an unterminated `Verdi V-2>` after reply CR/LF.
  The restored native reader uses `read_until()` for the reply, then consumes that
  trailing prompt when `prompt_enabled=True`. `Verdi>` and the exact selected
  model's `Verdi V-N>` are recognized. With the prompt disabled, CR/LF completes
  the exchange. Opening sends no echo/prompt writes, and there is no reply-format
  selection or automatic mode detection.
- Error prefixes: `RANGE ERROR:`, `Command Error:`, `Query Error:`. A device error
  preserves the instruction and reply. It is not retried.
  If `Query Error:` explicitly names a different `?` query, the connection is
  invalidated: a terminated error frame alone does not establish alignment.
- Multiple results use `&`. Faults are returned as integer lists; unknown positive
  codes are preserved, never discarded or treated as clear.
- Table 5-2: 8 data bits, no parity, 1 stop bit, no hardware/software handshaking.
  Baud rates: 1200, 2400, 4800, 9600, **19200 factory default**, 38400, 57600.
- The port is DCE; only pins 2, 3, 5 are used. No electrical/cable validation has
  occurred. No model-identification query is specified; callers select V2/V5/V6.

The 1 s default serial write/receive timeout, 4096-byte response ceiling, strict decimal
parser and connection failure policy are **software choices**, not manufacturer
response-time or firmware guarantees. A partial response, I/O error or lost
acknowledgment makes the serial session unusable. The command may have executed.
There is no automatic retry, recovery purge, mode normalization or state replay.
Explicit `purge_buffers()` discards host TX, then RX queues under the transaction lock. It preserves failure state and
transaction evidence; they do not establish device-side synchronization.
Windows pySerial clears host RX/TX queues when opening the port. That operation
does not clear an unfinished instruction already received by the laser.

`command()` sends one instruction and uses `read_until()` to receive complete
notice lines and one CR/LF reply, followed by the enabled trailing prompt. Value
interpretation occurs only after those reads complete. One lock prevents another
caller from transmitting early. Write and receive waits use the configured timeout;
each `read_until()` has its own timeout rather than one combined exchange deadline.
No per-byte timeout adjustment, queue polling, sleep, recovery purge or replay is
performed. Bytes returned by serial reads, including incomplete lines returned at
timeout, remain in the transaction. An I/O exception or interrupt inside a read can
prevent its internal partial bytes from being returned; earlier completed reads
remain available.

With `prompt_enabled=False`, reply CR/LF completes the exchange. Explicit successful
`PROMPT` writes update their acknowledgment and subsequent prompt expectations;
rejected writes retain the previous mode. Echo is accepted and can be changed only
through an explicit setter.

The supplied manual defines `PROMPT=0` / `>=0` as prompt ON and `PROMPT=1` /
`>=1` as OFF (p. 5-6). The separate Single FAP manual specifies the opposite
`>=n` polarity and different error strings. Those commands are not imported into
this controller's instruction set.

The observed firmware notices `min current set\r\n`, `level1 set!\r\n` and
`level0 set!\r\n` are recognized only as exact leading lines. Up to eight
consecutive notices are accepted, with a separate reply still required. Eight is
a software bound, not a manufacturer guarantee. Lesson 07 captured the exact
response `level1 set!\r\nlevel0 set!\r\n0.114\r\nVerdi V-2>` on V2 firmware
6.05; these messages have no established physical meaning in this driver.
All consumed notice bytes count toward the response limit and remain in the
transaction. Extra readings, excessive notices and unknown lines still fail.
The earlier inferred leading-blank-line exception has been removed now that the
full response is available.

The byte API returns replies without text decoding or numeric conversion.
Write operands are validated while the supplied instruction bytes are preserved.
`read` removes
framing and the echoed query, returning payload bytes. `write` and `command` return
unchanged wire replies. `last_transaction["response"]` always retains the full
wire reply. `get_value` and named helpers explicitly opt into text/value interpretation.
Raw byte commands use canonical short names and `=`. A raw `B=n` leaves the
host baud unchanged; use the named helper to coordinate the host transition.

Each attempted transaction records only `instruction`, `request`, `response`,
`payload`, `outcome` and `error` in `last_transaction`. Exchange errors carry an
independent record in `VerdiError.transaction`. Local refusals preserve the
previous record; a failed command has an `unknown` outcome. Acknowledgment and
documented rejection are explicit outcomes for typed helpers. There is no automatic retry or replay.

## Complete Table 5-3 command coverage

All 16 distinct write operations are exposed, counting LIGHT/POWER as one
operation and PRINT as a query prefix. Aliases share the same validation,
write permission and failure policy as the typed methods below.

| API | Wire form | Source / meaning |
| --- | --- | --- |
| `set_power_w(watts)` | `P=nn.nnnn` | Table 5-3, pp. 5-5–5-6; light regulation in W |
| `set_laser_state(0)` | `L=0` | p. 5-5; STANDBY overrides the ON keyswitch |
| `set_laser_state(1)` | `L=1` | p. 5-5; key must be ON; resets faults and clears fault history |
| `set_shutter(open=...)` | `S=0/1` | p. 5-6; closes/opens the head shutter |
| `set_echo(enabled=...)` | `E=0/1` | p. 5-5; change applies to the following command |
| `set_prompt(enabled=...)` | `PROMPT=0/1` | p. 5-6; **0 enables, 1 disables** prompt; `>=n` is its alternate spelling |
| `set_baudrate(baudrate)` | `B=n` | p. 5-5 and pp. 5-3–5-4; persistent device setting, followed by host reconfiguration |
| `set_chiller_on()` | `CHILLER=ON` | p. 5-5; only for Coherent chiller part 1037271 |
| `set_chiller_temperature_c(celsius)` | `CHILLER=XX.X` | p. 5-5; rounded to one decimal; physical range unspecified |
| `set_exit_screen()` | `EXIT=1` | p. 5-5; EXIT button |
| `set_flash()` | `FL=1` | p. 5-5; flash below lasing threshold for etalon recentering |
| `set_knob_down()` | `KNOBDN=1` | p. 5-5; KNOB DOWN button |
| `set_lbo_heater(enabled=...)` | `LBOH=0/1` | p. 5-5; cool down / heating |
| `set_lbo_optimization()` | `LBOOPT=1` | p. 5-5; initiate optimization |
| `set_front_panel_lock(value)` | `LFP=n` | p. 5-5; integer operand, valid values and unlock mapping unspecified |
| `set_menu_down()` | `MENUDN=1` | p. 5-5; MENU DOWN button |
| `set_menu_select()` | `SELECT=1` | p. 5-5; MENU SELECT button |
| `set_menu_up()` | `MENUUP=1` | p. 5-5; MENU UP button |

Writes require `VerdiController(..., allow_writes=True)`. Construction, connection,
disconnection and automatic monitoring never issue commands. The optional GUI can
queue explicit writes only when launched with `--allow-writes`. Mode writes are optional explicit
operations; they are not connection prerequisites. `disconnect()` only releases the
communication handle and **does not place the laser in STANDBY**.

`write(b"LBOH=1")` returns the raw reply. `set_lbo_heater(enabled=True)`
uses the same byte transport and explicitly interprets the acknowledgment.
`set_value("LBOH=1")` uses `write()` and validates the acknowledgment. Named
`set_...` helpers use `set_value()`; named `get_...` helpers use `get_value()`
and the byte `read()` method. Both paths use `command()` for the single exchange.
Text command aliases are not normalized.

Baud changes send `B=n` and receive the acknowledgment at the original baud,
then update the host port under the same lock. The manual specifies host
reinitialization but not the acknowledgment baud or transition timing. Firmware
that switches before replying may time out and retire the session. An unknown
outcome is never retried; establish the actual device baud independently before
using a fresh controller. A host-reconfiguration failure also retires the session;
its transaction retains `acknowledged` plus the host error. Following successful
reconfiguration, transactions use the new rate.

The chiller's temperature range and `LFP=n` valid values are not defined by this
manual. The API checks finite decimal temperature and integer panel-lock syntax,
with the existing instruction-length bound; firmware may reject a value. It does
not assume a physical chiller limit or that a particular LFP operand unlocks the
panel. Only the documented chiller `ON` and numeric forms are supported, not OFF.
Service sequencing and physical completion remain the application's responsibility.

## Query coverage

All **42** queries from Table 5-4 are accepted by `get_value()` as short strings or
their documented long names, prefixed with `?` or `PRINT `.
Direct parsing groups in [controller.py](../src/coherent_verdi/controller.py) distinguish
raw text, documented integer codes and decimal numbers. Source pages are below;
independent test vectors retain units and long names as manual reference data.

For commissioning, `get_capture()` accepts the same query catalogue only on a
read-only controller. It enforces a single CR/LF frame, permits an empty
payload, and removes documented echo/prompt decoration at the byte level without interpreting
values or faults. Documented device errors are still rejected and recorded.
The returned transaction record is evidence, not a claim about device health.
CLI `commission` exposes this path as JSONL. Capture payloads are bytes; text
queries return strings for ASCII data or bytes for non-ASCII data. No character
encoding is guessed. Numeric, code and fault parsing retains its validation.

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
   `?F` is not explicit in the manual. The parser accepts `SYSTEM OK` for both,
   consistent with the captured V2 firmware 6.05 reply. Positive fault codes/lists
   remain faults; malformed data invalidates the session. Empty replies can be
   captured for evidence but remain unsupported by normal fault parsing.
   Other firmware still requires raw capture and physical verification.
2. **Echo framing:** Table 5-1's one-line layouts and the captured V2 firmware
   6.05 standalone `Verdi V-2>` prompt are supported. That capture establishes
   prompt text and delayed arrival, not a timing bound. Real character echo timing,
   separately terminated echo lines, other firmware and prompt transition ordering
   still require capture; the parser never consumes arbitrary additional lines.
   The saved notebook 08 shutter-close attempt includes extra `incr` and `prom#`
   diagnostic lines and a timeout. Those lines remain unsupported and preserved
   in the transaction; see the [hardware run record](HARDWARE.md#validation-record-2026-10-27).
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
