# Engineering state

## Status

**AWAITING_HUMAN_REVIEW** — software/simulator scope complete, 2026-09-09 America/Chicago.
All hardware-independent requirements have current **PASS** evidence (E015).
No independent software task remains from this audit. This is not an
"awaiting hardware" blocker. Physical behavior and calibration remain **UNTESTED**;
no physical access is authorized.

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
| REQ-001 / explicit | Pinned framework and preserved inputs | TEST-001 hashes | PASS | [E015](records/RECORDS.md#e015) |
| REQ-002 / derived | Documented protocol/framing/errors | TEST-002 golden wire and malformed numeric cases | PASS | [E013](records/RECORDS.md#e013), [E015](records/RECORDS.md#e015) |
| REQ-003 / derived | Typed API/models, serialized I/O, cleanup | TEST-003 concurrency/deadline/interruption/recovery | PASS | [E013](records/RECORDS.md#e013), [E015](records/RECORDS.md#e015) |
| REQ-004 / derived | Simulator and faults/warmup/transitions | TEST-004 all models, virtual clock, lost acknowledgments | PASS | [E015](records/RECORDS.md#e015) |
| REQ-005 / derived | Bounded telemetry, errors, freshness, source | TEST-005 lifecycle, 1000 samples, clock/source changes | PASS | [E015](records/RECORDS.md#e015) |
| REQ-006 / derived | Cache-only Dash and streaming CLI | TEST-006 blocked acquisition, callbacks, real browser, JS | PASS | [E014](records/RECORDS.md#e014), [E015](records/RECORDS.md#e015) |
| REQ-007 / derived | Packaging, examples and software quality | TEST-007 lint/type/build/archive/install/runner and CI | PASS | [E015](records/RECORDS.md#e015), [E016](records/RECORDS.md#e016) |
| REQ-008 / derived | Operating docs and validation procedure | TEST-008 source review, links, current screenshots | PASS | [E013](records/RECORDS.md#e013), [E014](records/RECORDS.md#e014) |
| REQ-009 / explicit | Entire phase hardware-free | TEST-009 patched constructors/discovery and fake streams | PASS | [E015](records/RECORDS.md#e015) |
| REQ-010 / future derived | Physical behavior/calibration | TEST-010 later operator-approved procedure | UNTESTED | [Procedure](HARDWARE_VALIDATION.md); outside phase |

## Current configuration and evidence

Version 0.1.0; candidate source-manifest SHA-256:
`a731d6a9db7bc9db8e642c67bbba3d0f18d8209b2458caea3a17c85c1cca94e4`.
E015: **135 tests**, **94% statement coverage**, lint/format, strict typing,
dependencies, builds, source archive completeness, CLI/examples, isolated wheel
installation and integrated Node watchdog regression PASS. Windows/Python 3.12.14;
Node 24.19.0. [validation.json](records/validation.json) records current hashes,
results and environment; [requirements-validated.txt](records/requirements-validated.txt)
records exact Python dependencies. Current browser rendering/server-loss PASS (E014).

Current source commit c895060 passed all six Windows/Linux Python 3.11-3.13 CI
jobs ([E016](records/RECORDS.md#e016)). Its committed source matches the E015
candidate hashes. Later evidence-only commits leave that source unchanged.
Original manual and framework hashes verified. Upstream remains untouched.

## Limits and next action

No remaining actionable software finding from the audit. Real no-fault formatting,
echo timing, electrical compatibility, firmware latency, shutter-closed reporting,
operating limits and calibration remain unverified. The
[uncertainty register](docs/PROTOCOL.md#uncertainty-register) states these separately
from simulator policies. No automatic replay, service/calibration API or GUI writes.

The user's latest instruction authorizes completing all independent software work;
the earlier commit/push authorization applies to this same target repository.
Candidate and current CI evidence are preserved in Git. Retain the hardware-free
boundary; no additional software action is pending. Read PROJECT.md, AGENTS.md and STATE.md on resume; new
software requirements or failures reopen development and invalidate affected evidence.
Temporary simulator server/browser are closed. No port was enumerated or opened.

## Blockers and human action

None for this phase; no hardware permission is requested to finish software work.
For a separately requested later phase, explicit candidate approval must identify
Stage 1 read-only scope, model, operator-confirmed connection/baud and site conditions
under [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md). Prepared first interaction:
passive open followed by one `?SV` query. Record scope and evidence before proceeding;
no device writes or actuation are implied. This is not a physically validated release.
