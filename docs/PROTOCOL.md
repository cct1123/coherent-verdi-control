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
| `standby()` | `L=0` | p. 5-5; STANDBY overrides the ON keyswitch |
| `enable_laser()` | `L=1` | p. 5-5; key must be ON; resets faults and clears fault history |
| `set_shutter(open=...)` | `S=0/1` | p. 5-6; closes/opens the head shutter |
| `set_echo(enabled=...)` | `E=0/1` | p. 5-5; change applies to the following command |
| `set_prompt(enabled=...)` | `PROMPT=0/1` | p. 5-6; **0 enables, 1 disables** prompt |

Writes require `ControllerConfig(..., allow_writes=True)`. Construction, close,
replacement and telemetry never issue commands. Mode writes are optional explicit
operations; they are not connection prerequisites. `close()` only releases the
communication handle and **does not place the laser in STANDBY**.

The manual also documents service/front-panel operations (baud-rate changes,
chiller, FLASH, LBO heater/optimization, panel lock and menu buttons). They are
outside the public operational API in 0.1.0. There is no unrestricted raw-write
escape hatch. Chiller operand details and service sequencing are insufficiently
specified for this controller's scope. Extending this subset needs a documented
use case, source review and software tests.

## Query coverage

All **42** short-form queries from Table 5-4 are represented by `Query`.
`QUERY_SPECS` in [protocol.py](../src/coherent_verdi/protocol.py) maps each query to
its printed page, documented unit and response parser.

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
Servo codes 5/6 are returned as reported; distinctions involving V5 UNO are not
inferred from the caller's V5 selection.

## Uncertainty register

1. **No active faults:** `SYSTEM OK` is explicit for `?FH`; the clear reply for
   `?F` is not explicit. The parser tolerates `SYSTEM OK` for `?F`, and the
   simulator uses it as a fixture convention. This is not a verified firmware
   claim. Empty data, `0` and `OK` are rejected. Record the actual reply in the
   first read-only validation and add a source-grounded fixture before adapting.
2. **Echo framing:** the implementation follows Table 5-1's one-line layouts.
   Real character echo timing, any separately terminated echo lines and prompt
   transition ordering require capture; the parser deliberately fails on layouts
   beyond the table instead of consuming arbitrary lines.
3. **Power limits:** Table 2-1 rates models at 2/5/6 W. Those ratings are used as
   conservative software ceilings, not claimed firmware maximum setpoint ranges.
   A caller can lower the ceiling. No current, temperature or calibration tuning
   commands are implemented.
4. **Shutter behavior:** Table 4-2 (p. 4-8) describes idle at minimum power while
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

## Software references

The serial adapter's port-less construction, explicit open, read/write timeouts
and disabled flow control follow the [pySerial API](https://pyserial.readthedocs.io/en/latest/pyserial_api.html).
The optional client uses Dash callbacks and `dcc.Interval` as described by
[Dash live updates](https://dash.plotly.com/live-updates). Browser refreshes read
cached service data, rather than creating device polling workers.
