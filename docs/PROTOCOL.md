# Protocol reference and implementation boundary

Authoritative source: [Coherent Verdi V-2/V-5/V-6 Operator's Manual](../verdi.manual_v5.pdf),
part **0171-750-00, Rev IB**, © 08/2005. The supplied PDF has 130 pages and SHA-256
`d4a7a8a2a1e0c678bb00a5fd70be6ea1d649be063ab752de485a59daa3103f73`.
Printed section 5 corresponds to PDF pages 49–58. Table 5-1 and the relevant
command/fault tables were also rendered and visually inspected, including the
poorly spaced fault codes 19, 21, 25, 27 and 28. No newer firmware behavior is assumed.

## Wire contract

- Section 5, pp. 5-1–5-4: ASCII instruction terminated by CR/LF or semicolon;
  this library emits **CR/LF only**, one instruction per transaction.
- `PRINT ` and `?` are equivalent query prefixes; `:` and `=` are equivalent
  command delimiters (p. 5-3). The controller emits catalogued short queries and
  `=` commands; the simulator supports the same emitted subset, not all firmware aliases.
- Replies end in CR/LF; wait for a complete reply before the next instruction.
- Table 5-1, p. 5-2: a successful command replies with an empty CR/LF when echo
  and prompt are off. There is no documented `OK` command acknowledgment.
- Table 5-1 provides four single-line layouts combining optional `Verdi>` prefix
  and echoed instruction. The parser accepts these without writing mode settings
  during connection. Additional lines, control bytes and malformed replies fail.
- Error prefixes: `RANGE ERROR:`, `Command Error:`, `Query Error:`. A device error
  preserves the instruction and reply. It is not retried.
- Multiple results use `&`. Fault codes remain numeric; unknown positive codes
  are retained with `known=False`, never discarded or treated as clear.
- Table 5-2: 8 data bits, no parity, 1 stop bit, no hardware/software handshaking.
  Baud rates: 1200, 2400, 4800, 9600, **19200 factory default**, 38400, 57600.
- The port is DCE; only pins 2, 3, 5 are used. No electrical/cable validation has
  occurred. No model-identification query is specified; callers select V2/V5/V6.

The 1 s default transaction deadline, 4096-byte response ceiling, strict decimal
parser and connection failure policy are **software choices**, not manufacturer
response-time or firmware guarantees. A partial response, I/O error or lost
acknowledgment makes the serial session unusable. The command may have executed.
There is no automatic retry, input-buffer purge, mode normalization or state replay.

## Exposed operational commands

| API | Wire form | Source / meaning |
| --- | --- | --- |
| `set_power_w(watts)` | `P=nn.nnnn` | Table 5-3, pp. 5-5–5-6; light regulation in W |
| `stop()` | `L=0` | p. 5-5; STANDBY overrides the ON keyswitch |
| `start()` | `L=1` | p. 5-5; key must be ON; resets faults and clears fault history |
| `set_shutter(open=...)` | `S=0/1` | p. 5-6; closes/opens the head shutter |
| `set_echo(enabled=...)` | `E=0/1` | p. 5-5; change applies to the following command |
| `set_prompt(enabled=...)` | `PROMPT=0/1` | p. 5-6; **0 enables, 1 disables** prompt; `>=n` is its alternate spelling |

Writes require `VerdiController(..., allow_writes=True)`. Construction, connection,
disconnection and monitoring never issue commands. Mode writes are optional explicit
operations; they are not connection prerequisites. `disconnect()` only releases the
communication handle and **does not place the laser in STANDBY**.

The manual also documents service/front-panel operations (baud-rate changes,
chiller, FLASH, LBO heater/optimization, panel lock and menu buttons). They are
outside the public operational API in 0.2.0. There is no unrestricted raw-write
escape hatch. Chiller operand details and service sequencing are insufficiently
specified for this controller's scope. Extending this subset needs a documented
use case, source review and software tests.

## Query coverage

All **42** short-form queries from Table 5-4 are represented by `Query`.
Direct parsing groups in [protocol.py](../src/coherent_verdi/protocol.py) distinguish
raw text, documented integer codes and decimal numbers. Source pages are below;
independent test vectors retain units and long names as manual reference data.

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
for V2 (pp. 5-7, 5-9); these mismatches raise `ProtocolError`. V5 can mean standard
V5 or V5 UNO, so both codes remain representable until its variant is identified.

The complete independent query/unit/code vectors are in
[test_protocol.py](../tests/test_protocol.py), `MANUAL_QUERIES`. Fault descriptions
cover the union of Tables 5-4 and 6-1: 22 codes, including battery service code 30.
Code 1 retains both conflicting manual labels (see below). Code 47 remains known
from Table 5-4 even though Table 6-1 omits it. Unknown positive codes remain faults.

## Uncertainty register

1. **No active faults:** `SYSTEM OK` is explicit for `?FH`; the clear reply for
   `?F` is not explicit. Physical controllers therefore reject clear-looking
   replies unless `active_fault_clear_reply` matches the exact
   text independently verified for that firmware in Stage 1. Its default is None;
   malformed/unverified data invalidates the session. Positive fault codes/lists
   cannot be configured as clear tokens. Empty replies remain unsupported.
   Simulated controllers alone default to the fixture convention `SYSTEM OK`.
   Do not infer physical compatibility from that simulator convention or from ?FH.
2. **Echo framing:** the implementation follows Table 5-1's one-line layouts.
   Real character echo timing, any separately terminated echo lines and prompt
   transition ordering require capture; the parser deliberately fails on layouts
   beyond the table instead of consuming arbitrary lines.
3. **Power limits:** Table 2-1 rates models at 2/5/6 W. Those ratings are used as
   conservative software ceilings, not claimed firmware maximum setpoint ranges.
   A caller can lower the ceiling. No current, temperature or calibration tuning
   commands are implemented.
4. **Shutter behavior:** Table 4-3 (p. 4-9) describes idle at minimum power while
   closed and return/ramp after opening. The minimum power and ramp rates are not
   specified. The simulator's zero closed-shutter power is a synthetic fixture;
   **it does not establish the actual `?P` reading with the shutter closed**.
   The head shutter is used only as a safety shutter, never periodic modulation.
5. **Timing and faults:** no plant model, firmware latency bound, physical fault
   response timing, interlock integrity or safety certification follows from tests.
   Manual p. 4-2 specifies the LBO-not-locked fault for key ON during cold-start
   warmup. The simulator represents this fault, but retaining a fault latch until
   a fresh explicit enable after warmup is a conservative fixture policy. Real
   recovery/latching and any automatic resumption require physical observation.
6. **Fault-code conflict:** Table 5-4 calls code 1 a laser head interlock fault;
   Table 6-1 and Chart 5 call it an emission lamp fault (pp. 6-2, 6-12). The returned
   description flags both labels; verify against device firmware/Coherent support.
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
cached service data, rather than creating device polling workers.
