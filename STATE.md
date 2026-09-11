# Engineering state

## Status

**AWAITING_HUMAN_REVIEW** for future physical integration. The requested manual
audit, corrections, simulator/tests, tutorials and short report are software-complete.
No hardware access is authorized; physical behavior and calibration remain UNTESTED.

## System

[PROJECT.md](PROJECT.md) defines the controller, simulator, telemetry, CLI, Dash
monitor and tutorials. One controller owns serialized transactions; the simulator
is an independent peer and Dash reads only cached telemetry. The
[verification report](outputs/REPORT.md) covers the six operations, 42 queries,
manual corrections and remaining hardware assumptions.

The [tutorial guide](examples/tutorials/README.md) links four self-contained,
sectioned notebooks and one terminal runner. Hardware defaults remain disabled;
CONNECT precedes open, ?SV is first, and RUN precedes lesson commands. Physical
status checks require Stage 1-verified active_fault_clear_reply; writes require
explicit site limits and the controlled lesson checks all four temperature servos.

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

Evidence: [manual audit E035](records/RECORDS.md#e035),
[integrated validation E036](records/RECORDS.md#e036),
[publication review E037](records/RECORDS.md#e037).

## Current candidate and reproducibility

Version 0.1.0; source-manifest SHA-256:
`7cee08deb695a9136e4b07749dd7003c2ff5dff6b9f63fd3641503096d34693f`.

E037 reran **320 tests: PASS**, **96% coverage**, including 75 tutorial/operator
cases and eight notebook executions. Lint, format, strict typing and dependency
checks passed. All 52 source hashes still match E036, whose 11-stage integrated
validation remains applicable. No implementation, test or dependency changed.

Reproduce: install `.[dev,serial,gui]`, then `python scripts/validate.py`.
[Manifest](records/validation.json) records environment and build hashes;
[dependencies](records/requirements-validated.txt) pin the tested environment.
Windows 11/Python 3.12.14; one non-failing pyzmq warning, no failed/skipped tests.
Executed notebooks in `records/tutorial-notebooks/` are regenerated and uploaded by CI.

## Review and next action

E037 found no remaining actionable code issue or unused dependency. Pruned repeated
checkpoint prose; retained required features, tests and notebook definitions.
The user authorized commit/push; origin/main matched 82b6db1 before this review
commit. Git history records publication. No test session or device operation is pending.

## Human action required

None for this software task. Future integration requires candidate review and
explicit Stage 1 read-only approval under [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md),
with actual model, operator-confirmed port/baud and site conditions. Start with
passive open and one ?SV; return raw replies/front-panel comparisons and independently
verified ?F clear text. Record units and PASS/FAIL/INCONCLUSIVE evidence.
Only after Stage 1 may separately approved writes run within approved limits and
beam/cooling/interlock/abort conditions. Publication and example values grant no
hardware authority or safe physical limits. Firmware uncertainties remain in the
[protocol register](docs/PROTOCOL.md#uncertainty-register).
