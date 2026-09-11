# Engineering state

## Status

**AWAITING_HUMAN_REVIEW** for future hardware integration. The compact driver and
holistic software review are complete; the user authorized commit and push. No
hardware access is authorized; physical behavior
and calibration remain UNTESTED. No validation process or device operation is pending.

## System and candidate

Eight package modules, 1335 Python lines, twelve root exports, zero core runtime
dependencies. Constructor keywords and explicit connection methods replace config
objects/transport factories. One controller serializes I/O and latches uncertain
outcomes. Monitor/JSON and Dash are optional; callers own polling and shutdown.
See [architecture](ARCHITECTURE.md), [API migration](docs/API.md) and
[candidate report](outputs/REPORT.md). Four visible-function notebooks and the
operator runner use the same API; hardware defaults remain disabled.

Version 0.2.0; candidate SHA-256 `be0ad6235eb92e38800fe23e6c24f784719d4b5359d43f6b2ac2015a736fa027`.
[E039](records/RECORDS.md#e039): 315 tests PASS, 97% coverage, eight notebook executions,
all 11 validation stages PASS; Windows/Python 3.12.14, Node v24.14.1. Lint, format,
strict typing, dependencies, builds, examples, clean core/GUI installs and watchdog
passed. Wheel inventory matches the eight source modules; the source archive
includes test safety guards, manual and operating documents. Source hashes did not
change during validation. One non-failing pyzmq warning; no skipped tests.

## Requirements

PASS is software/simulation scope only. Full human criteria remain in PROJECT.md.
Evidence is E039 unless otherwise noted; [D011](records/RECORDS.md#d011) records the
latest authorized API/simulator-scope changes. E036..038 describe earlier candidates.

| ID / source | Criterion | Validation | Status |
| --- | --- | --- | --- |
| REQ-001 / PROJECT explicit | Framework provenance and preserved inputs | TEST-001 hashes; D011 architecture adaptation | PASS |
| REQ-002 / derived | Protocol, framing, errors | TEST-002 independent manual vectors | PASS |
| REQ-003 / derived, current cleanup | Explicit API/lifecycle and serialized I/O | TEST-003 read/write/concurrency/interruption/cleanup | PASS |
| REQ-004 / derived | Simulator models/faults/warmup/transitions | TEST-004 fixture clock and uncertain writes | PASS |
| REQ-005 / derived, current cleanup | Optional bounded monitoring/freshness | TEST-005 caller-driven acquisition and cached failures | PASS |
| REQ-006 / derived | Cache-only Dash and streaming CLI | TEST-006 callbacks/launcher shutdown/watchdog | PASS |
| REQ-007 / derived | Packaging and quality | TEST-007 typing/lint/build/core/extras installs | PASS |
| REQ-008 / derived | Operations and physical procedure | TEST-008 source/docs review | PASS |
| REQ-009 / PROJECT explicit | Hardware-free work | TEST-009/012 serial/discovery guards, including kernels | PASS |
| REQ-010 / future derived | Physical behavior/calibration | TEST-010 approved operator procedure | UNTESTED |
| REQ-011 / tutorial request | Four clear examples/notebooks | TEST-011 all lessons/notebooks executed | PASS |
| REQ-012 / tutorial request | Defaults, safety and reuse | TEST-012 models/inputs/states/errors/no replay | PASS |
| REQ-013 / operator clarification | Implemented human hardware paths | TEST-013 simulated configuration/confirmation/serial routing | PASS |
| REQ-014 / notebook clarification | Visible functions and clear sections | TEST-014 cell layout/no hidden scripts/empty-directory runs | PASS |
| REQ-015 / earlier simplification | Direct implementation/features/separation | TEST-015 source/API review and regression | PASS |
| REQ-016 / manual-verification request | Implemented protocol grounded in manual | TEST-016 42 queries/six commands/error/fault vectors | PASS |
| REQ-017 / current compact-driver request | Fewer modules, code/types and small reusable API | TEST-017 metrics/import/lifecycle/package review | PASS |

Reproduce: install `.[dev,serial,gui]`, run `python scripts/validate.py`.
[Manifest](records/validation.json) records environment, source/build hashes and commands.

## Human action required / next action

None for this software review/publication. Commit and push to the configured
origin/main are explicitly authorized by the current user request. Git history and
the tracking branch record publication. Future integration requires explicit Stage 1
read-only approval of this candidate under [HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md),
with actual model, operator-confirmed port/baud and site conditions. Begin with
passive connect and one ?SV; return raw framing/version/front-panel comparisons
and independently verified ?F clear text with units and acceptance results.
Then resume approved read validation. Writes require separate scope, power limits,
beam/cooling/interlock conditions and an abort procedure. Availability, examples
and historical publication do not grant hardware authority or physical safe limits.
