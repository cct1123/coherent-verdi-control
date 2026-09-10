# Engineering state

## Status

**AWAITING_HUMAN_REVIEW** — software review and pruning are complete. All four
notebooks are self-contained, with every demonstration and hardware helper defined
in named sections and code cells of at most 22 lines. The user requested commit
and push; publication is authorized. Physical integration still requires review.

| Validation scope | Status |
| --- | --- |
| Software validation | **PASS** |
| Simulator validation | **PASS** |
| Physical Verdi validation | **UNTESTED** |

No hardware access is authorized or performed.

## Objective and architecture

[PROJECT.md](PROJECT.md): manual-grounded Verdi V2/V5/V6 controller, diagnostics,
simulator, telemetry, CLI and optional Dash client, plus the user's four beginner
command-control tutorials. One typed controller owns serialized transactions.
Telemetry publishes bounded immutable snapshots; Dash reads only its cache.
The internal shutter is a safety shutter, never an experimental modulator.

[Tutorial guide](examples/tutorials/README.md): read status, set power in standby,
one controlled enable/shutter/standby session, and fault/uncertain-write diagnosis.
Each small script has a notebook containing the same visible source, expected
outputs and an exercise. Reusable functions accept a controller; simulator setup
and injection stay in the simulator entry point. Notebook hardware cells use their own visible validation/connection functions and
call the notebook's application functions directly. The separate
[terminal runner](examples/tutorials/run_tutorial.py) provides the CLI alternative.
Both require CONNECT before serial open, send ?SV first and require RUN before
lesson commands.
Notebook hardware cells are disabled by default. Core runtime source/API is unchanged.

## Requirements status

PASS covers software/simulation, not physical conformance or calibration.
Full human criteria remain in PROJECT.md.

| ID / source | Criterion | Method | Status | Evidence |
| --- | --- | --- | --- | --- |
| REQ-001 / explicit PROJECT.md | Pinned framework and preserved inputs | TEST-001 hashes | PASS | [E032](records/RECORDS.md#e032) |
| REQ-002 / derived | Documented protocol/framing/errors | TEST-002 golden wire and malformed numeric cases | PASS | [E032](records/RECORDS.md#e032) |
| REQ-003 / derived | Typed API, serialized I/O, cleanup | TEST-003 concurrency/deadline/interruption/recovery | PASS | [E032](records/RECORDS.md#e032) |
| REQ-004 / derived | Simulator models/faults/warmup/transitions | TEST-004 virtual clock and lost acknowledgments | PASS | [E032](records/RECORDS.md#e032) |
| REQ-005 / derived | Bounded telemetry, freshness, errors, source | TEST-005 lifecycle/cache/configuration | PASS | [E032](records/RECORDS.md#e032) |
| REQ-006 / derived | Cache-only Dash and streaming CLI | TEST-006 callbacks/watchdog; unchanged browser assets | PASS | [E032](records/RECORDS.md#e032), [E024](records/RECORDS.md#e024) |
| REQ-007 / derived | Packaging, examples and software quality | TEST-007 lint/type/build/core/extras installs | PASS | [E032](records/RECORDS.md#e032) |
| REQ-008 / derived | Operating docs and physical-validation procedure | TEST-008 source/output review | PASS | [E031](records/RECORDS.md#e031), [E032](records/RECORDS.md#e032) |
| REQ-009 / explicit PROJECT.md | Entire phase hardware-free | TEST-009/012 serial-open/discovery guards including kernels | PASS | [E032](records/RECORDS.md#e032) |
| REQ-010 / future derived | Physical behavior/calibration | TEST-010 operator-approved procedure | UNTESTED | [Procedure](HARDWARE_VALIDATION.md); outside phase |
| REQ-011 / explicit PROJECT.md tutorial extension | Four small examples, paired notebooks and clear explanations | TEST-011 all scripts and notebooks executed; source/expected-output checks | PASS | [E031](records/RECORDS.md#e031), [E032](records/RECORDS.md#e032) |
| REQ-012 / explicit PROJECT.md tutorial extension | Simulator-only defaults, errors/safety and later controller reuse | TEST-012 all models, invalid inputs/states, failures, interrupts, no replay | PASS | [E031](records/RECORDS.md#e031), [E032](records/RECORDS.md#e032) |
| REQ-013 / explicit PROJECT.md user clarification | Executable human-operated hardware paths for all four lessons | TEST-013 configuration, confirmation, serial routing and notebook hardware branches with simulator substitution | PASS | [E031](records/RECORDS.md#e031), [E032](records/RECORDS.md#e032); physical validation excluded |
| REQ-014 / explicit PROJECT.md notebook clarification | Visible functions, no hidden tutorial scripts, clear uncrowded sections | TEST-014 empty-directory execution, import/definition checks and cell length | PASS | [E032](records/RECORDS.md#e032); actual maximum 22 lines per code cell |

## Current candidate and reproducibility

Version 0.1.0; working-tree source-manifest SHA-256:
`1e83941dbd88416affb180a51c1d1547679cc9bbdccf9dc20cd504b65977766e`.

[E032](records/RECORDS.md#e032): **216 tests PASS**, **95% library statement
coverage**. Includes 71 tutorial/operator tests and eight notebook executions:
four default runs and four hardware-branch runs with simulated serial factories,
all from otherwise empty working directories. No notebook loads a tutorial script.
Lint/format, strict library typing, dependencies, wheel/sdist completeness,
CLI/examples, clean core-then-extras installation and Node watchdog PASS.
All four tutorial scripts and the shared runner's simulator default also passed
with only the installed core wheel.
[Manifest](records/validation.json) captures 56 source hashes and build/environment
details; [dependencies](records/requirements-validated.txt) captures the environment.

Windows 11, Python 3.12.14; JupyterLab 4.6.3, nbclient 0.11.0, nbformat 5.11.1,
ipykernel 7.3.0; Node 24.19.0. One non-failing Windows pyzmq selector-thread fallback
warning; no skipped or failed tests. Local executed notebooks:
`records/tutorial-notebooks/` (regenerated by tests, uploaded by CI).
Run `python scripts/validate.py`; activate the documented development environment.
Normal local permissions were needed for Windows pytest temporary directories.

## Review and next action

No remaining software gap within this request. See [report](outputs/REPORT.md).
Reviewed simulator policies remain explicit: synthetic power/thermal values,
fault latching, no-active-fault formatting and instantaneous transitions establish
no hardware behavior. Example targets/ceilings are not physical safety limits.
No automatic retries, physical fault injection, service/calibration commands or
GUI writes were introduced. Hardware validation/calibration remain UNTESTED.

All test sessions/kernels finished; no pending operation or tutorial polling worker.
No serial port was enumerated or opened. Manual/framework hashes are unchanged.
The user explicitly requested review, pruning, commit and push. Upstream main was
fetched and matched local main at aced244 before publication. Final Git history and
remote tracking record publication; no hardware approval is implied.

## Human action required

None to complete implementation of the human-operated tutorials. No physical
access approval is requested as part of this software work. For later integration,
review this candidate and record explicit Stage 1 read-only approval identifying
the model, operator-confirmed connection/baud and site conditions under
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md). The first prepared interaction is
passive open followed by one `?SV` query, then comparison of framing and actual
firmware response. Writes, laser enable and shutter opening need their own approved
scope and limits after read-only validation. Resuming this task does not grant it.
