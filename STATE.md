# Engineering state

## Status

**AWAITING_HUMAN_REVIEW** — final hardware-free hardening and usability pass complete.

| Validation scope | Status |
| --- | --- |
| Software validation | **PASS** |
| Simulator validation | **PASS** |
| Physical Verdi validation | **UNTESTED** |

Physical access remains prohibited in this phase. No independent software task remains.

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
| REQ-001 / explicit | Pinned framework and preserved inputs | TEST-001 hashes | PASS | [E021](records/RECORDS.md#e021) |
| REQ-002 / derived | Documented protocol/framing/errors | TEST-002 golden wire and malformed numeric cases | PASS | [E019](records/RECORDS.md#e019), [E021](records/RECORDS.md#e021) |
| REQ-003 / derived | Typed API/models, serialized I/O, cleanup | TEST-003 concurrency/deadline/interruption/recovery | PASS | [E019](records/RECORDS.md#e019), [E021](records/RECORDS.md#e021) |
| REQ-004 / derived | Simulator and faults/warmup/transitions | TEST-004 all models, cold-start fault 5, virtual clock, lost acknowledgments | PASS | [E021](records/RECORDS.md#e021) |
| REQ-005 / derived | Bounded telemetry, errors, freshness, source | TEST-005 lifecycle/logging/configuration/history/clock/source | PASS | [E021](records/RECORDS.md#e021) |
| REQ-006 / derived | Cache-only Dash and streaming CLI | TEST-006 blocked acquisition, callbacks, real browser, JS | PASS | [E020](records/RECORDS.md#e020), [E021](records/RECORDS.md#e021) |
| REQ-007 / derived | Packaging, examples and software quality | TEST-007 lint/type/build/archive/core and extras clean installs | PASS | [E021](records/RECORDS.md#e021) |
| REQ-008 / derived | Operating docs and validation procedure | TEST-008 source review, snippets, links, current screenshots | PASS | [E019](records/RECORDS.md#e019), [E020](records/RECORDS.md#e020) |
| REQ-009 / explicit | Entire phase hardware-free | TEST-009 patched constructors/discovery and fake streams | PASS | [E021](records/RECORDS.md#e021) |
| REQ-010 / future derived | Physical behavior/calibration | TEST-010 later operator-approved procedure | UNTESTED | [Procedure](HARDWARE_VALIDATION.md); outside phase |

## Current configuration and evidence

Version 0.1.0; candidate source-manifest SHA-256:
`e47efd04594643e98c1778a7400c0a201ffc987cf2d1d24e13f93f585c85a811`.
E021: **145 tests**, **95% statement coverage**, lint/format, strict typing,
dependencies, builds, source archive completeness, CLI/examples, isolated wheel
installation both without extras and with GUI/serial extras, installed Dash HTTP
smoke and integrated Node watchdog regression PASS. Windows/Python 3.12.14;
Node 24.19.0. [validation.json](records/validation.json) records current hashes,
results and environment; [requirements-validated.txt](records/requirements-validated.txt)
records exact Python dependencies. Current browser rendering/server-loss PASS (E020).

Earlier baseline c895060 passed six Windows/Linux Python 3.11–3.13 CI jobs (E016).
Those results are historical; E021 validates this changed candidate locally on
Windows/Python 3.12.14. The CI workflow includes the new extras check for future
runs. Manual/framework hashes remain unchanged. Upstream was not modified.

## Limits and next action

No remaining actionable software finding from the audit. Real no-fault formatting,
echo timing, electrical compatibility, firmware latency, shutter-closed reporting,
operating limits and calibration remain unverified. The
[uncertainty register](docs/PROTOCOL.md#uncertainty-register) states these separately
from simulator policies. No automatic replay, service/calibration API or GUI writes.

Publication review/pruning complete ([E022](records/RECORDS.md#e022)); the user
authorized commit/push. The hardware-review checkpoint remains in force.
Read PROJECT.md, AGENTS.md and STATE.md on resume.
New requirements or failures reopen development and invalidate affected evidence.
The simulator server/browser are closed. No port was enumerated or opened.

## Blockers and human action

None for this phase; no hardware permission is requested to finish software work.
For a separately requested later phase, explicit candidate approval must identify
Stage 1 read-only scope, model, operator-confirmed connection/baud and site conditions
under [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md). Prepared first interaction:
passive open followed by one `?SV` query. Record scope and evidence before proceeding;
no device writes or actuation are implied. This is not a physically validated release.
