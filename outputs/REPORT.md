# Engineering report

Hardware-free scope: **COMPLETE / PASS**. Physical integration remains outside
this phase; the template checkpoint is AWAITING_HUMAN_REVIEW.

## Candidate

Version **0.1.0**; source-manifest SHA-256:
`7b3c7d8cf51378f091fa5adf459c5d3e35df2a223286de01bc04636028199c81`.
[validation.json](../records/validation.json) records hashes, environment and results
at **2026-09-10T01:05:40.459186+00:00**. State/report/evidence updates are excluded from the manifest;
Git identifies the complete revision. [STATE.md](../STATE.md) maps requirements.

## System

The manual-grounded Verdi V-2/V-5/V-6 library provides typed models, diagnostics,
an optional serial adapter, simulator, telemetry, CLI and Plotly Dash monitor.
One controller serializes complete transactions and compound samples. The catalog
covers all 42 documented queries; operational writes require explicit opt-in.
Connection, close and replacement send no commands; there is no automatic replay.

The simulator covers key/fault transitions, virtual-clock warmup, malformed replies,
timeouts and lost acknowledgments, with synthetic dynamics explicitly documented.
Telemetry retains bounded immutable snapshots with source identity and monotonic
age. Dash reads only this cache. CLI streaming flushes each sample and reports
failure. The internal shutter is a safety shutter, never an experimental modulator.

[Installation/API/CLI](../README.md) · [Ownership/lifecycle](../docs/INTEGRATION.md) ·
[Protocol/uncertainties](../docs/PROTOCOL.md) · [Simulator](../docs/SIMULATOR.md)

## Review and validation

The latest review found no new runtime defect. Duplicated test setup and repeated
handoff prose were pruned; thread-test cleanup now preserves setup failures.
All assertions and hardware guards remain. See [E017](../records/RECORDS.md#e017).
Earlier fixes and their diagnoses remain in the durable records.

Current [E018](../records/RECORDS.md#e018): **135 tests PASS**, **94% coverage**;
lint/format, strict typing, dependency consistency, wheel/sdist builds, archive
completeness, CLI, both examples, clean no-extras installation and Node watchdog
checks PASS. Preserved-input hashes match; source was unchanged during validation.
Runtime code is identical to c895060, whose six Windows/Linux Python 3.11-3.13
[CI jobs passed](https://github.com/cct1123/coherent-verdi-control/actions/runs/34423561052)
([E016](../records/RECORDS.md#e016)); E018 covers the pruned tests.

Browser rendering/server-loss evidence remains current ([E014](../records/RECORDS.md#e014)):
[live screenshot](../docs/images/simulator-dashboard.png),
[offline warning](../docs/images/simulator-server-offline.png). Test resources are closed.
Reproduce with `python scripts/validate.py` after installing `.[dev,serial,gui]`
and Node 22+ (`VERDI_NODE` may specify its executable). Local evidence uses
Windows/Python 3.12.14 and Node 24.19.0; [Python versions](../records/requirements-validated.txt).

## Physical limits and later review

No hardware was accessed. Active no-fault formatting, echo/prompt timing, firmware
latency, electrical compatibility, shutter-closed reporting, operating limits and
calibration remain UNTESTED. Model ratings are software ceilings; simulator
outputs are fixtures. Service/calibration commands and GUI writes are excluded.

Any later integration requires separately scoped candidate approval under
[HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md), starting with passive open and
one `?SV` query. That procedure covers evidence, further reads, write gates,
abort/recovery and shutdown. Closing software does not change laser/shutter/heater
state; follow the manual's operator cool-down procedure.

Original inputs and framework revision `724a7f772069d3357ea66dbc4742d25bd874a33e`
are preserved ([provenance](../records/FRAMEWORK.md)); upstream remains untouched.
