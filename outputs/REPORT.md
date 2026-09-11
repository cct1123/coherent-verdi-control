# Verdi manual verification report

**Software/manual audit complete; physical behavior and calibration UNTESTED.**
Source: supplied Coherent Verdi V2/V5/V6 Operator's Manual, **0171-750-00 Rev IB,
08/2005**, sections 1, 2, 4, 5, 6 and relevant operating principles in section 7.
The original PDF is unchanged. See the [source and protocol matrix](../docs/PROTOCOL.md)
for its hash, printed-page references and implementation boundaries.

## What was checked

| Area | Coverage |
| --- | --- |
| Commands | All six public operations: power, standby, enable, shutter, echo and prompt; five wire families in Table 5-3, operands, aliases and side effects. |
| Queries | All 42 Table 5-4 queries: spelling, units, response type and every documented state code; long forms and PRINT aliases. |
| Wire and errors | Tables 5-1/5-2: CR/LF, semicolon requests, colon/equal delimiters, four echo/prompt layouts, three error prefixes, 8N1/no flow control and supported baud rates. |
| Limits and safety | Model ratings versus firmware bounds; key/standby override, warmup/servo readiness, fault/history reset, shutter idle behavior, no automatic replay and complete shutdown. |

Independent [manual vectors](../tests/test_protocol.py) supplement existing tests.
Service/front-panel writes remain outside the public API. Undocumented layouts and
units remain raw text; no inferred service command or calibration API was added.
The controller, serial transport and independent simulator remain separate; telemetry
and Dash retain their existing ownership and cache boundaries.

## What was corrected

- Added battery-service fault **30** from Table 6-1/Chart 13. Fault **1** now shows
  the manual's conflicting head-interlock/emission-lamp descriptions. All 22 codes
  in the union of the command and troubleshooting tables are represented.
- Removed the assumption that active-fault query `?F` shares `?FH`'s `SYSTEM OK`
  clear reply. Physical configurations now require independently verified
  `active_fault_clear_reply` text. Unexpected clear-looking replies stop the
  session; positive fault codes/lists cannot be configured as clear.
- Enforced documented diode/LBO servo restrictions: V2 excludes code 6; V6 excludes
  code 5. The controlled tutorial checks all four temperature servos before enable.
- Added simulator long/PRINT query forms, colon/semicolon syntax and the short
  prompt command; corrected acknowledgment spacing and rejected Python-only power
  syntax. Enabled, shutter-closed diode current now differs from diode-off current.
- Updated all four self-contained notebooks, terminal examples and documentation.
  Corrected the shutter reference to Table 4-3, p.4-9; clarified key fixture behavior,
  warmup and the below-40 °C LBO condition before AC removal during complete shutdown.

## What remains uncertain

The manual does not settle active-fault clear text, the conflicting code-1 label,
V5 versus V5 UNO servo behavior, real echo timing/prompt transitions, transaction
latency, firmware setpoint bounds/quantization, or fault recovery/latching details.
The 2/5/6 W ratings are software ceilings, not site-approved safe limits. Simulator
power/current values, closed-shutter `?P` and ramps are fixtures, not measurements.
See the [uncertainty register](../docs/PROTOCOL.md#uncertainty-register).

## What requires real hardware validation

Follow [HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md) only after explicit
candidate approval. First: operator-confirmed model/port/baud and passive open,
then one `?SV` query. Compare raw framing, state/servo values and front-panel
readings; independently verify the exact `?F` clear response before configuring it.
Separately approved writes must validate setpoint readback, key/standby behavior,
one shutter cycle, warmup, physical interlocks, fault response and shutdown.
Optical accuracy/calibration require suitable reference measurements.

On communication failure, stop commands and use the operator's physical abort
procedure. A lost acknowledgment may follow an applied command. Closing the port
does not shut down the laser; software rollback cannot undo a physical action.

## Validation

**320 tests passed, 96% library statement coverage**, including eight fresh notebook
executions and 75 tutorial/operator cases. All 11 validation stages passed: tests,
lint, format, strict typing, dependency checks, builds, CLI, synchronous/async
examples, clean core/extras installs and Node watchdog. No tests were removed.
Notebooks retain visible helpers and sections; maximum code-cell length is 23 lines.
Physical serial opening/discovery was blocked in tests and notebook kernels.

[E035/E036 evidence](../records/RECORDS.md#e035), [validation manifest](../records/validation.json).
[Publication review E037](../records/RECORDS.md#e037) found no further code defects;
the same 320 tests and static checks passed again on unchanged implementation files.
Run: `python scripts/validate.py` after installing `.[dev,serial,gui]`.
Windows 11, Python 3.12.14, Node 24.19.0; one non-failing pyzmq warning.
Timestamp: 2026-09-11T00:28:16.330843+00:00. All 52 source hashes and preserved inputs matched.
Candidate SHA-256: `7cee08deb695a9136e4b07749dd7003c2ff5dff6b9f63fd3641503096d34693f`.
