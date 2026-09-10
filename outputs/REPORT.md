# Engineering report

Status: hardware-independent scope **COMPLETE / PASS**, 2026-09-09 America/Chicago.
The template checkpoint is AWAITING_HUMAN_REVIEW for any separately authorized
physical integration. No hardware is needed to reproduce the software evidence.

## Candidate and architecture

Version **0.1.0** implements the requested Verdi V-2/V-5/V-6 Python controller,
typed models, diagnostics, simulator, bounded telemetry, JSON CLI and optional
Plotly Dash monitor. The supplied Coherent operator manual Rev IB is authoritative.
The internal shutter is a safety shutter, never an experiment modulation device.

Candidate source-manifest SHA-256:
`a731d6a9db7bc9db8e642c67bbba3d0f18d8209b2458caea3a17c85c1cca94e4`.
[validation.json](../records/validation.json) records file/build hashes and results
at **2026-09-10T00:55:27.405946+00:00**. Evidence, state and report updates are excluded from the source
manifest to avoid self-reference; Git identifies the complete repository revision.

One controller owns serialized request/reply pairs and compound samples. The
protocol catalog contains all 42 documented short-form queries. Operational writes
cover power, STANDBY/ON, safety shutter, echo and prompt, with explicit opt-in.
Unknown faults remain visible; connection, close and replacement send no commands.
There is no automatic replay. The pySerial adapter is optional and has only been
exercised with byte-stream fakes.

The simulator independently maps commands and models documented state meanings,
virtual-clock warmup fixtures, key/fault transitions, malformed replies, timeouts
and applied commands with lost acknowledgments. Synthetic dynamics are documented.
One telemetry service retains bounded immutable history; Dash consumes typed cache
snapshots and never accesses a controller lock or serial protocol. Source identity
travels with status samples, and freshness uses monotonic time. The CLI remains
simulator-only, with immediate JSONL output and failure-aware exit status.

[Installation/API/CLI](../README.md) · [Ownership and integration](../docs/INTEGRATION.md) ·
[Protocol/uncertainties](../docs/PROTOCOL.md) · [Simulator contract](../docs/SIMULATOR.md)

## Continued engineering and verification

The continuation audit resolved meaningful software gaps after the original
candidate: oversized integer parsing, blocked GUI metadata reads, empty-error and
wall-clock freshness mistakes, stale source labels, interrupted-open cleanup,
retrying failed resource release, replacement failure state, buffered CLI output,
missing source-archive support files and incomplete integrated JS validation.
Before/after evidence is recorded in [E013](../records/RECORDS.md#e013); design
consequences in [D004](../records/RECORDS.md#d004). No undocumented firmware behavior
was added. Manual query, command and fault mappings were reconfirmed.

Final [E015](../records/RECORDS.md#e015) hardware-free validation: **PASS**.

- **135 pytest tests passed**, **94% statement coverage**, no skips or warnings.
- Ruff lint/format and strict mypy for 12 modules passed; dependencies are consistent.
- Wheel/sdist builds, archive completeness, both examples and CLI passed.
- Fresh no-extras wheel installation verified imports, assets, typing marker,
  console entry point and integration examples.
- Integrated Node watchdog startup/live/expiry/recovery and preserved-input hashes passed.
- Source remained unchanged during validation.

Current actual browser rendering and stopped-server warning passed
([E014](../records/RECORDS.md#e014)); refreshed
[live](../docs/images/simulator-dashboard.png) and
[offline](../docs/images/simulator-server-offline.png) screenshots are included.
Blocked acquisition responsiveness, source changes, empty exceptions and monotonic
freshness are covered by automated callback/integration regressions. Server and
browser test resources were closed afterward.

Local configuration: Windows 11/Python 3.12.14, Node 24.19.0;
[exact Python dependencies](../records/requirements-validated.txt). Run
`python scripts/validate.py` after installing `.[dev,serial,gui]` and Node 22+.
Use `VERDI_NODE` for an explicit Node executable when it is not on PATH.
Current source commit **c895060** passed every job in the Windows/Linux Python
3.11-3.13 [CI matrix](https://github.com/cct1123/coherent-verdi-control/actions/runs/34423561052)
([E016](../records/RECORDS.md#e016)). Evidence-only commits preserve the exact
validated source hashes. [STATE.md](../STATE.md) maps acceptance.

## Remaining physical scope

All independent software/simulator requirements have current PASS evidence.
Physical Verdi behavior and calibration remain **UNTESTED**: active `?F` clear
format, echo/prompt timing, firmware latency, electrical compatibility, shutter-closed
reporting and actual operating limits. Model ratings are software ceilings, and
simulator dynamics are fixtures. Raw diagnostics retain unspecified-unit/composite
responses. Service/calibration commands and GUI writes are outside this version.

No serial discovery, physical reads/writes, actuation or calibration occurred.
Future integration requires a separately scoped candidate approval under
[HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md), starting with passive open and
one `?SV` query before broader reads. That document gives query groups, evidence,
write gates, abort/recovery and operator shutdown. Closing software does not change
laser/shutter/heater state; follow the manual's operator cool-down procedure.

Framework revision `724a7f772069d3357ea66dbc4742d25bd874a33e` and original inputs are
preserved ([provenance](../records/FRAMEWORK.md)); the upstream repository is untouched.
