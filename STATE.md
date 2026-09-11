# Engineering state

## Status

**AWAITING_HUMAN_REVIEW** — the requested software simplification is complete and
reviewed. Software/simulator validation PASS; physical Verdi behavior and calibration
remain UNTESTED. No hardware access is authorized or performed.

## Objective and architecture

[PROJECT.md](PROJECT.md): manual-grounded Verdi V2/V5/V6 controller, diagnostics,
simulator, telemetry, CLI, optional Dash monitor and four beginner tutorials.
One controller owns serialized transactions. Independent serial/protocol/simulator
modules preserve framing and test isolation; telemetry publishes bounded immutable
snapshots and Dash reads only the cache. Public library APIs remain unchanged.

[Tutorial guide](examples/tutorials/README.md): read status, set power in standby,
one controlled enable/shutter/standby session, and fault/uncertain-write diagnosis.
All terminal functions now live in [run_tutorial.py](examples/tutorials/run_tutorial.py).
The four former script files and dynamic script loading are removed. Each notebook
still defines every demonstration and hardware helper visibly in named sections;
no notebook loads another tutorial file. Maximum code-cell length: 22 lines.
Hardware defaults remain disabled, CONNECT precedes open, ?SV is first, and RUN
precedes lesson commands. Write limits must be supplied explicitly.

## Requirements status

PASS covers software/simulation only. Full human criteria remain in PROJECT.md.

| ID / source | Criterion | Method | Status | Evidence |
| --- | --- | --- | --- | --- |
| REQ-001 / explicit PROJECT.md | Pinned framework and preserved inputs | TEST-001 hashes | PASS | E034 |
| REQ-002 / derived | Protocol, framing and errors | TEST-002 golden wire/malformed replies | PASS | E034 |
| REQ-003 / derived | Typed API, serialized I/O and cleanup | TEST-003 concurrency/deadline/interruption/recovery | PASS | E034 |
| REQ-004 / derived | Simulator models/faults/warmup/transitions | TEST-004 virtual clock/lost acknowledgments | PASS | E034 |
| REQ-005 / derived | Bounded telemetry, freshness and errors | TEST-005 lifecycle/cache/source changes | PASS | E034 |
| REQ-006 / derived | Cache-only Dash and streaming CLI | TEST-006 callbacks/watchdog | PASS | E034; unchanged browser assets E024 |
| REQ-007 / derived | Packaging and software quality | TEST-007 lint/type/build/core/extras installs | PASS | E034 |
| REQ-008 / derived | Operating docs and physical-validation procedure | TEST-008 source/output review | PASS | E033/E034 |
| REQ-009 / explicit PROJECT.md | Entire phase hardware-free | TEST-009/012 serial/discovery guards including kernels | PASS | E034 |
| REQ-010 / future derived | Physical behavior/calibration | TEST-010 approved operator procedure | UNTESTED | Outside current scope |
| REQ-011 / explicit tutorial request | Four small examples and clear notebooks/docs | TEST-011 all lessons and notebooks executed | PASS | E034 |
| REQ-012 / explicit tutorial request | Simulator defaults, safety and reuse | TEST-012 models/inputs/states/errors/no replay | PASS | E034 |
| REQ-013 / explicit operator clarification | Implemented human-operated hardware paths | TEST-013 simulator-substituted configuration/confirmation/serial routing | PASS | E034; no physical validation |
| REQ-014 / explicit notebook clarification | Visible functions and uncrowded sections | TEST-014 definition/import checks, empty-directory kernel runs, cell lengths | PASS | E034 |
| REQ-015 / explicit simplification request | Fewer modules/dependencies and direct control flow, features/API/tests retained | TEST-015 source/API/dependency review + full regression | PASS | D009/E033/E034 |

Evidence: [E033](records/RECORDS.md#e033), [E034](records/RECORDS.md#e034),
[D009](records/RECORDS.md#d009), [E024](records/RECORDS.md#e024).

## Current candidate and reproducibility

Version 0.1.0; source-manifest SHA-256:
`29b070ac92fa9b7bca04287c1ef96afec593e2e873b704684d55f80d4d8906e0`.

E034: **216 tests PASS**, **95% library statement coverage**, including all
71 tutorial/operator cases and eight fresh notebook runs (four defaults and four
simulated hardware branches). All 11 validation stages passed; all 52 source
hashes stayed unchanged during validation. Manual/framework hashes match.
Python files across library/examples/scripts/tests: **29 -> 25**; lines including
comments/blanks: **4,221 -> 4,159**. No test file or case was removed.

Reproduce: install `.[dev,serial,gui]`, then `python scripts/validate.py`.
[Manifest](records/validation.json) includes dependencies and build hashes;
[dependency snapshot](records/requirements-validated.txt) captures the environment.
Windows 11/Python 3.12.14, Node 24.19.0. One non-failing Windows pyzmq selector-thread
warning; no skipped/failed tests. Installed extras: Dash 4.4.1, Plotly 7.0.0,
pySerial 3.5. Normal Windows permissions were needed for test temporary directories.
Executed notebooks: `records/tutorial-notebooks/` (regenerated, uploaded by CI).

## Review and next action

No remaining software gap in this request. See [report](outputs/REPORT.md).
The prior user request authorizes review, pruning, commit and push; Git HEAD and
origin/main record publication state. Origin matched HEAD at 0033ecc before commit.
Publication does not approve hardware access. All test sessions/kernels completed;
no pending device operation or tutorial polling worker remains.

## Human action required

None for this software task. Future physical integration requires review of this
candidate and explicit Stage 1 read-only approval naming the actual model,
operator-confirmed port/baud and site conditions in
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md). First interaction: passive open,
then one `?SV` query and comparison of framing/read semantics/firmware reply.
Only after Stage 1 may separately approved writes/enable/shutter operations run
within stated limits and beam/cooling/interlock/abort conditions. Example power
values are synthetic exercises, not safe physical limits. No approval is inferred
from task resumption or hardware availability.
