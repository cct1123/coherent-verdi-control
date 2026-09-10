# Engineering state

## Status

**AWAITING_HUMAN_REVIEW** — 2026-09-09, America/Chicago.
Hardware-free software and simulator validation: **PASS**.
Physical Verdi behavior and calibration: **UNTESTED**. No physical access authorized.

## Objective and current system

[PROJECT.md](PROJECT.md): manual-grounded Verdi V2/V5/V6 controller, diagnostics,
simulator, telemetry, CLI and optional Dash client for research software stacks.
The typed controller owns serialized I/O; the GUI reads a shared telemetry cache.
See [README](README.md), [integration](docs/INTEGRATION.md), and
[candidate report](outputs/REPORT.md).

## Requirements status

Criteria are agent-derived except explicit REQ-001/009. PASS applies to the stated
software/simulation scope; it does not establish physical firmware conformance.

| ID / source | Criterion | Method | Status | Evidence |
| --- | --- | --- | --- | --- |
| REQ-001 / explicit | Pinned framework, preserved useful inputs | TEST-001 hashes | PASS | [E011](records/RECORDS.md#e011) |
| REQ-002 / derived | Manual-linked protocol, framing and errors | TEST-002 golden wire tests | PASS | [E002](records/RECORDS.md#e002), [E011](records/RECORDS.md#e011) |
| REQ-003 / derived | Typed API, policies, serialized I/O, cleanup | TEST-003 concurrency/deadline/interruption | PASS | [E010](records/RECORDS.md#e010), [E011](records/RECORDS.md#e011) |
| REQ-004 / derived | Simulator and injected failures | TEST-004 virtual clock/faults/lost replies | PASS | [E011](records/RECORDS.md#e011) |
| REQ-005 / derived | Bounded telemetry and diagnostics | TEST-005 lifecycle/errors/1000 samples | PASS | [E011](records/RECORDS.md#e011) |
| REQ-006 / derived | CLI and Dash consume library/cache | TEST-006 routes, callbacks, browser outage | PASS | [E007](records/RECORDS.md#e007), [E011](records/RECORDS.md#e011) |
| REQ-007 / derived | Packaging, typing, lint, integration | TEST-007 build/install/examples/checkpoint | PASS | [E011](records/RECORDS.md#e011) |
| REQ-008 / derived | Operating docs and review procedure | TEST-008 review, links, screenshots | PASS | [E009](records/RECORDS.md#e009), [E010](records/RECORDS.md#e010) |
| REQ-009 / explicit | Hardware-free development | TEST-009 fake serial guards and review | PASS | [E011](records/RECORDS.md#e011) |
| REQ-010 / future derived | Actual protocol/behavior/calibration | TEST-010 later physical validation | UNTESTED | [Procedure](HARDWARE_VALIDATION.md); outside phase |

## Current configuration and evidence

Version 0.1.0; candidate manifest SHA-256:
`50d96d36801e5d2acf905a4ce53664ef6e74761c315d80186236f7ca12437b82`.
[E011](records/RECORDS.md#e011): 116 tests, 94% statement coverage, lint/format,
strict typing, dependencies, builds, CLI/examples, isolated wheel installation and
Node watchdog regression PASS. Windows/Python 3.12.14; Node 24.19.0.
[validation.json](records/validation.json) records source/build hashes and packages;
[requirements-validated.txt](records/requirements-validated.txt) records versions.

Framework `724a7f772069d3357ea66dbc4742d25bd874a33e` and original input hashes
verified. The local prompt log and generated logs are ignored; durable evidence,
manual and current manifest are versioned. No upstream modifications.

## Gaps and limits

No remaining actionable finding from this software review. Physical no-fault
framing, echo/prompt timing, electrical compatibility, firmware latency,
closed-shutter reporting, operating limits and calibration remain unverified.
See the [uncertainty register](docs/PROTOCOL.md#uncertainty-register).
No automatic retry/resynchronization or service/calibration API. GUI is read-only.
Windows/Linux Python 3.11-3.13 CI is configured; local evidence covers the host above.

## Authorization, priority and next action

The user explicitly authorized "review, prune. commit, push." Review and pruning
are complete; publish this candidate to the target `origin/main` without force.
Git history/remote status establish publication; no upstream template write is
permitted. After publication, remain at this hardware review gate. On resume read
PROJECT.md, AGENTS.md and STATE.md. New software requirements reopen development
and invalidate affected evidence. No real port has been enumerated or opened.

## Blockers and human action

None for this software phase. No hardware approval exists. For a later hardware
phase, review the candidate and explicitly approve Stage 1 read-only integration
under [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md), naming model, operator-confirmed
connection/baud and site conditions. The prepared first interaction is passive
open followed by one `?SV` query; record approval and framing evidence before
proceeding. No write/actuation authorization is implied.

The candidate is software-complete pending hardware review, not a physically
validated release. Durable files retain progress; they do not schedule execution.
