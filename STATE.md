# Engineering state

## Status

**AWAITING_HUMAN_REVIEW** — hardware-free scope complete, 2026-09-09 America/Chicago.
Software/simulator criteria: **PASS** (E018). Physical behavior/calibration:
**UNTESTED**. No physical access authorized or independent software task pending.

## Objective and current architecture

[PROJECT.md](PROJECT.md): manual-grounded Verdi V2/V5/V6 controller, diagnostics,
simulator, telemetry, CLI and optional Dash client for research software stacks.
One typed controller owns serialized transactions. Telemetry publishes bounded,
immutable snapshots with source provenance and monotonic age; GUI reads only that
cache. The internal shutter is a safety shutter, never an experimental modulator.
[README](README.md), [integration](docs/INTEGRATION.md), [report](outputs/REPORT.md).

## Requirements status

Criteria are agent-derived except explicit REQ-001/009. PASS applies to software
and simulation, not physical firmware conformance or calibration.

| ID / source | Criterion | Method | Status | Evidence |
| --- | --- | --- | --- | --- |
| REQ-001 / explicit | Pinned framework and preserved inputs | TEST-001 hashes | PASS | [E018](records/RECORDS.md#e018) |
| REQ-002 / derived | Documented protocol/framing/errors | TEST-002 golden wire and malformed numeric cases | PASS | [E013](records/RECORDS.md#e013), [E018](records/RECORDS.md#e018) |
| REQ-003 / derived | Typed API/models, serialized I/O, cleanup | TEST-003 concurrency/deadline/interruption/recovery | PASS | [E013](records/RECORDS.md#e013), [E018](records/RECORDS.md#e018) |
| REQ-004 / derived | Simulator and faults/warmup/transitions | TEST-004 all models, virtual clock, lost acknowledgments | PASS | [E018](records/RECORDS.md#e018) |
| REQ-005 / derived | Bounded telemetry, errors, freshness, source | TEST-005 lifecycle, 1000 samples, clock/source changes | PASS | [E018](records/RECORDS.md#e018) |
| REQ-006 / derived | Cache-only Dash and streaming CLI | TEST-006 blocked acquisition, callbacks, real browser, JS | PASS | [E014](records/RECORDS.md#e014), [E018](records/RECORDS.md#e018) |
| REQ-007 / derived | Packaging, examples and software quality | TEST-007 lint/type/build/archive/install/runner and CI | PASS | [E018](records/RECORDS.md#e018), [E016](records/RECORDS.md#e016) |
| REQ-008 / derived | Operating docs and validation procedure | TEST-008 source review, links, current screenshots | PASS | [E013](records/RECORDS.md#e013), [E014](records/RECORDS.md#e014) |
| REQ-009 / explicit | Entire phase hardware-free | TEST-009 patched constructors/discovery and fake streams | PASS | [E018](records/RECORDS.md#e018) |
| REQ-010 / future derived | Physical behavior/calibration | TEST-010 later operator-approved procedure | UNTESTED | [Procedure](HARDWARE_VALIDATION.md); outside phase |

## Current configuration and evidence

Version 0.1.0; candidate source-manifest SHA-256:
`7b3c7d8cf51378f091fa5adf459c5d3e35df2a223286de01bc04636028199c81`.
E018: **135 tests**, **94% statement coverage**, lint/format, strict typing,
dependencies, builds, source archive completeness, CLI/examples, isolated wheel
installation and integrated Node watchdog regression PASS. Windows/Python 3.12.14;
Node 24.19.0. [validation.json](records/validation.json) records current hashes,
results and environment; [requirements-validated.txt](records/requirements-validated.txt)
records exact Python dependencies. Current browser rendering/server-loss PASS (E014).

Runtime code remains identical to c895060, which passed all six Windows/Linux
Python 3.11-3.13 CI jobs ([E016](records/RECORDS.md#e016)). E018 revalidates the
pruned test suite and packaging. Manual/framework hashes remain unchanged.

## Limits and next action

No remaining actionable software finding from the audit. Real no-fault formatting,
echo timing, electrical compatibility, firmware latency, shutter-closed reporting,
operating limits and calibration remain unverified. The
[uncertainty register](docs/PROTOCOL.md#uncertainty-register) states these separately
from simulator policies. No automatic replay, service/calibration API or GUI writes.

Review/pruning complete ([E017](records/RECORDS.md#e017)); publish the validated
cleanup to origin/main under the user's commit/push authorization. Read PROJECT.md, AGENTS.md and STATE.md on resume.
New requirements or failures reopen development and invalidate affected evidence.
The simulator server/browser are closed. No port was enumerated or opened.

## Blockers and human action

None for this phase; no hardware permission is requested to finish software work.
For a separately requested later phase, explicit candidate approval must identify
Stage 1 read-only scope, model, operator-confirmed connection/baud and site conditions
under [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md). Prepared first interaction:
passive open followed by one `?SV` query. Record scope and evidence before proceeding;
no device writes or actuation are implied. This is not a physically validated release.
