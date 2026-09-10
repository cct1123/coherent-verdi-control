# Engineering report

Status: **AWAITING_HUMAN_REVIEW** — hardware-free candidate, 2026-09-09.

## Result and reviewed candidate

Version **0.1.0** provides a typed Python controller for Coherent Verdi V-2/V-5/V-6,
a deterministic simulator, diagnostics, bounded telemetry, JSON CLI and optional
read-only Plotly Dash monitor. Its protocol reference is the supplied Coherent
operator manual, Rev IB. Physical behavior and calibration remain **UNTESTED**.

Candidate source-manifest SHA-256:
`50d96d36801e5d2acf905a4ce53664ef6e74761c315d80186236f7ca12437b82`.
[validation.json](../records/validation.json) records file/build hashes, tool versions
and results at **2026-09-10T00:41:07.930567+00:00**. The Git commit containing this report identifies
the published revision. State, report and evidence updates sit outside the source
manifest to avoid self-reference.

The requested framework was initialized from
`724a7f772069d3357ea66dbc4742d25bd874a33e`; upstream was untouched. Original manual,
prompt log and framework instruction hashes were verified. The manual is versioned;
historical prompts and generated logs remain local. See [provenance](../records/FRAMEWORK.md).

## Architecture and implementation

One controller owns the transport and serializes complete transactions and compound
samples. The protocol catalog covers all 42 documented short-form queries, strict
framing/value parsing and unknown fault preservation. Operational writes cover
power, STANDBY/ON, safety shutter, echo and prompt, with explicit write opt-in.
Connection, close and replacement are passive; no automatic replay occurs.

The optional pySerial adapter bounds deadlines and response size, and rejects reuse
after a failed/interrupted transaction. It has only been exercised through injected
byte streams. The simulator independently maps requests and supports fake key/fault
state, virtual-clock warmup, malformed replies, timeouts and lost acknowledgments.

One telemetry worker publishes bounded immutable history and visible failures.
Dash reads that cache; it owns no protocol implementation or serial connection.
An independent browser watchdog marks server loss as stale. The CLI is entirely
simulator-backed. Core dependencies are empty; serial and GUI are optional extras.

[API, installation and CLI](../README.md) · [Ownership/lifecycle](../docs/INTEGRATION.md) ·
[Protocol and uncertainties](../docs/PROTOCOL.md) · [Simulator behavior](../docs/SIMULATOR.md)

## Review, pruning and verification

The publication review corrected three issues: control whitespace accepted in
responses, interrupted transactions leaving reusable sessions, and abnormal
validation termination retaining an old PASS. Regression failures were reproduced
for the first two; checkpoint tests cover subprocess timeout, launch failure and
interruption. Bootstrap examples and duplicate report prose were pruned. Regenerable
logs/XML are ignored; CI uploads its JUnit results as artifacts. See
[E010](../records/RECORDS.md#e010) and [D003](../records/RECORDS.md#d003).

Final [E011](../records/RECORDS.md#e011) software/simulator validation: **PASS**.

- **116 pytest tests passed**, **94% statement coverage**, no skips or warnings.
- Ruff lint/format, strict mypy for 12 modules and dependency consistency passed.
- Wheel/sdist builds, CLI, both examples and a clean no-extras wheel installation passed.
- Node virtual-clock watchdog startup, live receipt, expiry and recovery passed.
- Manual/framework preservation and unchanged source during validation passed.

The earlier browser validation remains applicable: actual simulator screenshots
show the [live monitor](../docs/images/simulator-dashboard.png) and
[server-loss warning](../docs/images/simulator-server-offline.png); see
[E007](../records/RECORDS.md#e007). No server is left running.

Validated locally on Windows 11, Python 3.12.14 and Node 24.19.0.
[Exact Python dependencies](../records/requirements-validated.txt) are recorded.
Reproduce with `python scripts/validate.py` and `node scripts/test_watchdog.cjs`
after installing `.[dev,serial,gui]`. The configured CI matrix covers Windows/Linux
and Python 3.11-3.13; remote results must be read from the actual run.
[STATE.md](../STATE.md) maps each requirement to its method and evidence.

## Limits and later hardware review

No physical port discovery, reads, writes, actuation or calibration occurred.
Active `?F` clear formatting, echo/prompt timing, firmware latency, electrical
compatibility and shutter-closed reporting remain unverified. Simulator dynamics
are fixtures; 2/5/6 W software ceilings do not establish physical operating limits.
Unknown-unit/composite diagnostics stay raw. Service/calibration commands and GUI
writes are excluded. Closing the controller releases communication without changing
laser, shutter or heater state; the safety shutter is not a modulation mechanism.

For a later phase, review this candidate and explicitly authorize Stage 1 read-only
integration with model, operator-confirmed connection/baud and site conditions.
[HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md) specifies the first passive open
and single `?SV` query, expected evidence, subsequent query groups, write gates,
abort/recovery and operator shutdown. Follow the manual's cool-down procedure;
never use AC power cycling as a software test. Current publication authorization
does not authorize those physical steps. This is a software-complete candidate,
not a physically validated release.
