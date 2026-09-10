# Engineering report — simplification

| Validation scope | Status |
| --- | --- |
| Software validation | **PASS** |
| Simulator validation | **PASS** |
| Physical Verdi validation | **UNTESTED** |

Checkpoint: **AWAITING_HUMAN_REVIEW**. Candidate version 0.1.0, SHA-256
`4606c649bd71fcd27cb750365f11310beb4d4360f0b0b7b2e8305ecd543c738e`.
[Validation manifest](../records/validation.json), completed
2026-09-10T04:03:18.050817+00:00, fingerprints the working-tree source and builds.
Report/state/history updates are excluded from that fingerprint.

## Simplified architecture

Python clients and CLI call one `VerdiController`. It directly owns a serial or
simulated transport and calls pure protocol functions for framing/parsing.
One `TelemetryService` owns polling and bounded history. Dash reads its cache and
returns plain Plotly figure dictionaries. Local and CI validation use one script.
See the [architecture diagram and usage](../README.md#architecture),
[API reference](../docs/API.md) and [integration guide](../docs/INTEGRATION.md).

## Removed and consolidated

| Previous files | Destination |
| --- | --- |
| `scripts/gui_smoke.py` | `scripts/install_smoke.py`; one clean core-then-extras environment |
| `test_client_edge_cases.py`, `test_telemetry_gui_cli.py` | `tests/test_clients.py`, `tests/test_telemetry.py` |
| `test_hardening.py`, `test_lifecycle_failures.py` | Existing controller/transport suites and telemetry suite |
| `test_protocol_edge_cases.py`, `test_simulator_acceptance.py` | `tests/test_controller.py` |
| `test_telemetry_lifecycle_edges.py` | Controller cancellation and telemetry lifecycle suites |

Eliminated two numeric conversion wrappers, duplicate protocol-error handling,
duplicate cached model state, repeated baud-rate configuration, graph-object
builder calls, duplicate CSS, test factories/fakes and one redundant close-failure
case. CI no longer repeats the validator's command list. Installation no longer
creates two environments or exposes an `--extras` mode; its helper accepts only
its used cwd argument. Removed an obsolete checksum gate on the ignored local
prompt log; the log is untouched, and manual/framework integrity checks remain.
Repeated architecture/API prose was pruned from the integration guide.

Removed the direct `plotly>=6,<7` requirement and its typing override. Plotly remains
Dash's required dependency; it has not been removed from the GUI runtime. The core
still has zero third-party dependencies. No framework or replacement infrastructure
was introduced. Details and diagnoses: [E023](../records/RECORDS.md#e023).

## Size and validation

Comparison with Git 34b5c37, counting Python/JS/CSS under src, tests and scripts:

| Area | Files before → after | Lines before → after |
| --- | --- | --- |
| Runtime and assets | 14 → 14 | 1,601 → 1,577 |
| Tests/support | 12 → 7 | 1,340 → 1,260 |
| Validation scripts | 4 → 3 | 398 → 381 |
| Total | **30 → 24 (−20%)** | **3,339 → 3,218 (−121; −3.6%)** |

These counts exclude documentation, workflow YAML, generated builds and durable
records. Meaningful regressions were retained; one duplicate test was replaced by
an acquisition-duration regression verifying all 14 status reads are timed.

[E025](../records/RECORDS.md#e025): **145 tests PASS**, **95% statement coverage**,
Ruff lint/format, strict mypy, dependency consistency, wheel/sdist builds, archive
completeness, CLI, both examples, isolated core/extras installation, installed Dash
callbacks and Node watchdog PASS. All six documentation Python snippets passed.
The 45 candidate file hashes stayed unchanged during validation. Final diff and
public API review found no remaining actionable software issue.

Environment: Windows/Python 3.12.14, Node 24.19.0. Development Plotly is 6.9.0;
fresh GUI installation passed with Dash 4.4.1 / Plotly 7.0.0 / pySerial 3.5.
[Current browser evidence](../records/RECORDS.md#e024) verifies rendering and the
server-loss warning; [live](../docs/images/simulator-dashboard.png) and
[offline](../docs/images/simulator-server-offline.png) screenshots were refreshed.
Test servers/tabs are closed. Run `python scripts/validate.py` to reproduce.

## Complexity retained deliberately

- Serial and simulator implementations share a typed transport boundary so tests
  never need a physical port; the byte-stream contract isolates pySerial.
- Controller/transport locks, deadlines, failure poisoning and explicit replacement
  protect untagged RS-232 reply ownership and uncertain write outcomes.
- Immutable typed models, distinct actionable exceptions, a sourced 42-query catalog
  and bounded telemetry preserve public APIs, unit checks, diagnostics and freshness.
- The single telemetry worker prevents GUI clients from owning or polling protocol I/O.
- Hardware guards, deterministic clocks, regression tests, package entrypoints/assets,
  reusable JSON serialization, user docs and durable provenance have current uses.

The internal shutter remains a safety shutter, never an experimental modulator.
Software close sends no state-changing command. No hardware was accessed; firmware
behavior, electrical compatibility, latency, shutter-closed reporting and calibration
remain UNTESTED. Later work follows [HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md),
starting with separately approved read-only queries. Upstream template untouched.
