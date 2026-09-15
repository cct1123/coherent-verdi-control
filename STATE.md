# Engineering state

## Status and candidate

**AWAITING_HUMAN_REVIEW** for future hardware integration. Software simplification,
holistic review and final validation are complete. No hardware access is authorized;
physical behavior and calibration remain UNTESTED. No device operation is pending.

Version 0.3.0; hardware-focused README rewrite based on 29bb216; current source SHA-256
`cbd7ecca8ec7b2d349efa9111d6769a7add2ea2e2954baa41d8280d6db76ae12`.
E041's validated implementation fingerprint is
`56bbd1fce0bfa82fd92e747684961a913c9264d10a7b965de96f5aa5bbffe5c4`.
Relative to E041, only README, PROJECT, the screenshot and its source-package
inclusion differ within the fingerprint; runtime, tests and examples match
E041 byte-for-byte. This follow-up changes documentation only.
[E047](records/RECORDS.md#e047) records final review, setup clarifications, repeated
README example/link checks and wheel/source-archive inspection. E046 verifies
the serial install, five hardware command
templates and the real-controller Python example with fake exchanges, plus 21
links/anchors. E045 retains the core install and 89 targeted test evidence. E044
supplies the unchanged screenshot's browser evidence; its source-archive check
applies to the earlier README.
Five package modules (three substantive), 1057 Python lines, five classes, four
root exports, two exceptions and zero required runtime dependencies. Controller
contains serial/protocol handling; SimulatedVerdi exposes the same API. Results
are dictionaries, strings, numbers and fault-code lists. GUI/cache remain optional.
See [architecture](ARCHITECTURE.md), [API/migration](docs/API.md) and [report](outputs/REPORT.md).

[E041](records/RECORDS.md#e041): 322 tests PASS, 97% coverage, eight notebook executions,
all 11 integrated stages PASS. Windows/Python 3.12.14, Node v24.14.1; no skipped tests.
One non-failing pyzmq warning. Source hashes stayed unchanged during validation;
manual/AGENTS hashes match. Final audit verified links, notebook/runner function
parity and absence of removed runtime modules from distributions. The wheel has
exactly five modules. [D012](records/RECORDS.md#d012) records scope and reductions.
A final markdown-only notebook correction is recorded in the manifest; every code
cell and other source file matches the full-suite candidate. Previous evidence
E038..040 is historical.

## Requirements

PASS is software/simulation scope only; full criteria remain in PROJECT.md.
Current evidence is E041 and D012, including review methods TEST-001/008/015/017.

| ID / source | Criterion | Validation | Status |
| --- | --- | --- | --- |
| REQ-001 / PROJECT explicit | Framework provenance and preserved inputs | TEST-001 hashes; D012 architecture adaptation | PASS |
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
| REQ-018 / PROJECT new-user README and follow-ups | Hardware-first visual guide: serial setup, reads/controls, Python, safety, troubleshooting and optional simulation | TEST-018 final review, examples/links/build E047; serial install E046; screenshot E044 | PASS |

Reproduce: install `.[dev,serial,gui]`, run `python scripts/validate.py`.
[Manifest](records/validation.json) captures environment, source/build hashes and commands.

## Human action required / next action

The requested hardware-focused README review and fixes are complete. The user's
"review fix issues commit push" authorizes committing and publishing the five
reviewed documentation files to the configured origin/main at
`github.com/cct1123/coherent-verdi-control`. Origin was refreshed and matches
29bb216 without divergence. Next: commit, push without force, verify remote
equality and record publication. No further approval is needed for these changes.
No preview server, hardware operation or test process is pending. E041's full-suite
manifest is preserved; no new full-suite or physical validation is claimed.

Future integration requires explicit Stage 1 read-only candidate approval under
[HARDWARE_VALIDATION.md](HARDWARE_VALIDATION.md), with actual model, operator-confirmed
port/baud and site conditions. Begin with passive connect and one ?SV; return raw
framing/version/front-panel comparisons and independently verified ?F clear text.
Then resume approved read validation. Writes require separate approval, site power
limits, beam/cooling/interlock conditions and an abort procedure. No physical
limits, calibration or current device state can be inferred from simulation.
