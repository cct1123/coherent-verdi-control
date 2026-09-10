# Engineering state

## Status

**AWAITING_HUMAN_REVIEW** — simplification complete; no remaining software finding.

| Validation scope | Status |
| --- | --- |
| Software validation | **PASS** |
| Simulator validation | **PASS** |
| Physical Verdi validation | **UNTESTED** |

Physical access remains prohibited in this phase.

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
| REQ-001 / explicit | Pinned framework and preserved inputs | TEST-001 hashes | PASS | [E025](records/RECORDS.md#e025) |
| REQ-002 / derived | Documented protocol/framing/errors | TEST-002 golden wire and malformed numeric cases | PASS | [E023](records/RECORDS.md#e023), [E025](records/RECORDS.md#e025) |
| REQ-003 / derived | Typed API/models, serialized I/O, cleanup | TEST-003 concurrency/deadline/interruption/recovery | PASS | [E023](records/RECORDS.md#e023), [E025](records/RECORDS.md#e025) |
| REQ-004 / derived | Simulator and faults/warmup/transitions | TEST-004 all models, cold-start fault 5, virtual clock, lost acknowledgments | PASS | [E025](records/RECORDS.md#e025) |
| REQ-005 / derived | Bounded telemetry, errors, freshness, source | TEST-005 lifecycle/logging/configuration/history/clock/source | PASS | [E025](records/RECORDS.md#e025) |
| REQ-006 / derived | Cache-only Dash and streaming CLI | TEST-006 blocked acquisition, callbacks, real browser, JS | PASS | [E024](records/RECORDS.md#e024), [E025](records/RECORDS.md#e025) |
| REQ-007 / derived | Packaging, examples and software quality | TEST-007 lint/type/build/archive/core and extras clean installs | PASS | [E025](records/RECORDS.md#e025) |
| REQ-008 / derived | Operating docs and validation procedure | TEST-008 source review, snippets, links, current screenshots | PASS | [E023](records/RECORDS.md#e023), [E024](records/RECORDS.md#e024) |
| REQ-009 / explicit | Entire phase hardware-free | TEST-009 patched constructors/discovery and fake streams | PASS | [E025](records/RECORDS.md#e025) |
| REQ-010 / future derived | Physical behavior/calibration | TEST-010 later operator-approved procedure | UNTESTED | [Procedure](HARDWARE_VALIDATION.md); outside phase |

## Current configuration and evidence

Version 0.1.0; candidate source-manifest SHA-256:
`4606c649bd71fcd27cb750365f11310beb4d4360f0b0b7b2e8305ecd543c738e`.
E025: **145 tests**, **95% statement coverage**, lint/format, strict typing,
dependencies, builds, archive completeness, CLI/examples, clean core-then-extras
installation, installed Dash callbacks and Node watchdog PASS. Windows/Python
3.12.14; Node 24.19.0. [validation.json](records/validation.json) records hashes,
results and the development environment; [requirements-validated.txt](records/requirements-validated.txt)
records development dependencies. Fresh installation also passed with Dash 4.4.1,
Plotly 7.0.0 and pySerial 3.5. Browser rendering/server-loss PASS (E024).

Cleanup: six fewer code files, 121 fewer lines across src/tests/scripts. Public
runtime APIs and hardware boundaries retained. One validator now drives local
and CI acceptance; historical CI results do not certify this changed candidate.
Manual/framework hashes remain unchanged. Upstream was not modified.

## Limits and next action

No remaining actionable software finding after publication review. Real no-fault
formatting, echo timing, electrical compatibility, firmware latency, shutter-closed reporting,
operating limits and calibration remain unverified. The
[uncertainty register](docs/PROTOCOL.md#uncertainty-register) states these separately
from simulator policies. No automatic replay, service/calibration API or GUI writes.

Publication review complete ([E026](records/RECORDS.md#e026)); the user authorized
commit/push of the validated simplification. The hardware-review checkpoint remains.
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
