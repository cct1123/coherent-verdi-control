# Engineering state

## Status

**AWAITING_HUMAN_REVIEW** for future physical integration. The requested manual
audit, corrections, simulator/tests, tutorials and short report are software-complete.
No hardware access is authorized; physical behavior and calibration remain UNTESTED.

## Objective and architecture

[PROJECT.md](PROJECT.md): manual-grounded Verdi V2/V5/V6 controller, diagnostics,
simulator, telemetry, CLI, optional Dash monitor and four beginner tutorials.
One controller owns serialized transactions. Independent serial/protocol/simulator
modules preserve framing and test isolation; telemetry publishes bounded immutable
snapshots and Dash reads only the cache. Six operational methods and all 42 queries
remain available; one optional configuration field was added for verified physical
active-fault clear text. No dependency or module was added by the manual audit.

[Tutorial guide](examples/tutorials/README.md): read status, set power in standby,
one controlled enable/shutter/standby session, and fault/uncertain-write diagnosis.
Terminal functions live in [run_tutorial.py](examples/tutorials/run_tutorial.py).
Each notebook defines every demonstration and hardware helper visibly in named
sections; no notebook loads another tutorial file. Maximum code-cell length: 23 lines.
Hardware defaults remain disabled, CONNECT precedes open, ?SV is first, and RUN
precedes lesson commands. Writes require explicit site limits; full physical status
checks require Stage 1-verified active_fault_clear_reply. All four temperature
servos must be LOCKED before the controlled tutorial enables the laser.

## Requirements status

PASS covers software/simulation only. Full human criteria remain in PROJECT.md.

| ID / source | Criterion | Method | Status | Evidence |
| --- | --- | --- | --- | --- |
| REQ-001 / explicit PROJECT.md | Pinned framework and preserved inputs | TEST-001 hashes | PASS | E036 |
| REQ-002 / derived | Protocol, framing and errors | TEST-002 golden wire/malformed replies | PASS | E035/E036 |
| REQ-003 / derived | Typed API, serialized I/O and cleanup | TEST-003 concurrency/deadline/interruption/recovery | PASS | E036 |
| REQ-004 / derived | Simulator models/faults/warmup/transitions | TEST-004 virtual clock/lost acknowledgments | PASS | E035/E036 |
| REQ-005 / derived | Bounded telemetry, freshness and errors | TEST-005 lifecycle/cache/source changes | PASS | E036 |
| REQ-006 / derived | Cache-only Dash and streaming CLI | TEST-006 callbacks/watchdog | PASS | E036; unchanged browser assets E024 |
| REQ-007 / derived | Packaging and software quality | TEST-007 lint/type/build/core/extras installs | PASS | E036 |
| REQ-008 / derived | Operating docs and physical-validation procedure | TEST-008 source/output review | PASS | E035/E036 |
| REQ-009 / explicit PROJECT.md | Entire phase hardware-free | TEST-009/012 serial/discovery guards including kernels | PASS | E036 |
| REQ-010 / future derived | Physical behavior/calibration | TEST-010 approved operator procedure | UNTESTED | Outside current scope |
| REQ-011 / explicit tutorial request | Four small examples and clear notebooks/docs | TEST-011 all lessons and notebooks executed | PASS | E036 |
| REQ-012 / explicit tutorial request | Simulator defaults, safety and reuse | TEST-012 models/inputs/states/errors/no replay | PASS | E036 |
| REQ-013 / explicit operator clarification | Implemented human-operated hardware paths | TEST-013 simulated configuration/confirmation/serial routing | PASS | E036; no physical validation |
| REQ-014 / explicit notebook clarification | Visible functions and uncrowded sections | TEST-014 definitions, empty-directory kernels, cell lengths | PASS | E036 |
| REQ-015 / explicit simplification request | Direct code, preserved features/API/tests and separation | TEST-015 source/API/dependency review + regression | PASS | D009/E033; E036 current regression |
| REQ-016 / explicit manual-verification request | Full implemented protocol audit and corrections/report | TEST-016 independent manual vectors, source matrix + regression | PASS | D010/E035/E036 |

Evidence: [E035](records/RECORDS.md#e035), [E036](records/RECORDS.md#e036),
[D010](records/RECORDS.md#d010), [E024](records/RECORDS.md#e024).

## Current candidate and reproducibility

Version 0.1.0; source-manifest SHA-256:
`7cee08deb695a9136e4b07749dd7003c2ff5dff6b9f63fd3641503096d34693f`.

E036: **320 tests PASS**, **96% library statement coverage**, including all
75 tutorial/operator cases and eight fresh notebook runs (four defaults and four
simulated hardware branches). All 11 validation stages passed; all 52 source
hashes stayed unchanged during validation. Manual/framework hashes match.
No test was removed; the previous module/dependency simplification is retained.

Reproduce: install `.[dev,serial,gui]`, then `python scripts/validate.py`.
[Manifest](records/validation.json) includes dependencies and build hashes;
[dependency snapshot](records/requirements-validated.txt) captures the environment.
Windows 11/Python 3.12.14, Node 24.19.0. One non-failing Windows pyzmq selector-thread
warning; no skipped/failed tests. Installed extras: Dash 4.4.1, Plotly 7.0.0,
pySerial 3.5. Normal Windows permissions were needed for test temporary directories.
Executed notebooks: `records/tutorial-notebooks/` (regenerated, uploaded by CI).

## Review and next action

No remaining software gap in this request. See [verification report](outputs/REPORT.md).
Unresolved firmware details and physical assumptions are explicitly listed in the
[protocol uncertainty register](docs/PROTOCOL.md#uncertainty-register).
The prior user request authorizes review, pruning, commit and push; Git HEAD and
origin/main record publication state. The audit began from ef9c472. Publication
does not approve hardware access. All test sessions/kernels completed; no pending
device operation or tutorial polling worker remains.

## Human action required

None for this software task. Future physical integration requires review of this
candidate and explicit Stage 1 read-only approval naming the actual model,
operator-confirmed port/baud and site conditions in
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md). First interaction: passive open,
then one ?SV query and comparison of framing/read semantics/firmware reply.
Return raw replies and front-panel comparisons, including an independently verified
?F clear response, with the procedure's units and PASS/FAIL/INCONCLUSIVE evidence.
Only after Stage 1 may separately approved writes/enable/shutter operations run
within stated limits and beam/cooling/interlock/abort conditions. Example power
values are synthetic exercises, not safe physical limits. No approval is inferred
from task resumption or hardware availability.
