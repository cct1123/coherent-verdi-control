# Engineering report

Final hardware-free production hardening and human-usability pass: **COMPLETE**.
The template checkpoint is **AWAITING_HUMAN_REVIEW**.

| Validation scope | Status |
| --- | --- |
| Software validation | **PASS** |
| Simulator validation | **PASS** |
| Physical Verdi validation | **UNTESTED** |

## Candidate

Version **0.1.0**; source-manifest SHA-256:
`e47efd04594643e98c1778a7400c0a201ffc987cf2d1d24e13f93f585c85a811`.
[validation.json](../records/validation.json) records source/build hashes, environment
and results at **2026-09-10T01:19:54.046692+00:00**. State/report/evidence updates are
excluded from the manifest, which identifies the validated working-tree source,
docs and screenshots. [STATE.md](../STATE.md) maps requirements to current evidence.

## System and documentation

One typed controller owns serialized Verdi transactions; telemetry publishes a
bounded immutable cache shared by Dash clients. The library, CLI and simulator
cover V-2/V-5/V-6. Writes require explicit opt-in, and connection/replacement/close
send no commands. The internal shutter is a safety shutter, never a modulator.

[README](../README.md): installation, Python/CLI/GUI examples, architecture and
simulator screenshots. [API reference](../docs/API.md) and
[lab integration](../docs/INTEGRATION.md): units, errors, ownership and deployment.
[Protocol](../docs/PROTOCOL.md) and [simulator](../docs/SIMULATOR.md): documented
device behavior and fixture policies. The later physical procedure is linked below.

## Review and fixes

The review fixed premature simulator enable during LBO warmup, mutable telemetry
configuration, failed logging sinks disrupting acquisition, a shutdown lock conflict,
and cancellation ownership in the async example. Ten new regression cases cover
these gaps. No automatic recovery writes were introduced. [E019](../records/RECORDS.md#e019)
records diagnoses, bounded audits and design decisions.

The review also checked serial deadlines and poisoned-session recovery, model
ceilings/units, all 42 documented queries and unknown-fault handling, bounded
telemetry/freshness, cache-only Dash callbacks and clean installation. No further
actionable finding remained. [STATE.md](../STATE.md) maps each requirement to its
tests; E019–E021 retain detailed evidence, including six executed documentation snippets.

## Acceptance evidence

[E021](../records/RECORDS.md#e021): **145 tests PASS**, **95% statement coverage**;
lint/format, strict typing, dependency consistency, wheel/sdist builds, archive
completeness, CLI, both examples, clean core/GUI/serial installations, installed
Dash HTTP smoke and Node watchdog checks PASS. Preserved-input hashes match;
source was unchanged during validation. No skipped tests or test warnings.

Fresh browser evidence ([E020](../records/RECORDS.md#e020)) includes the
[live screenshot](../docs/images/simulator-dashboard.png) and
[server-loss warning](../docs/images/simulator-server-offline.png). The live browser
reported no console warnings/errors. Test servers, tabs and temporary install
resources are closed. No physical port was enumerated or opened.

Reproduce with `python scripts/validate.py` after installing `.[dev,serial,gui]`
and Node 22+ (`VERDI_NODE` may specify its executable). Extras installation needs
the configured pip registry or cache. Current evidence is Windows/Python 3.12.14,
Node 24.19.0, Dash 4.4.1, Plotly 6.9.0 and pySerial 3.5; exact development dependency
versions are in [requirements-validated.txt](../records/requirements-validated.txt).

Earlier c895060 passed six Windows/Linux Python 3.11–3.13
[CI jobs](https://github.com/cct1123/coherent-verdi-control/actions/runs/34423561052)
(E016). Those results are historical, not a remote run of this changed candidate.
The CI workflow retains the matrix and now includes the extras installation check.

## Physical limits and human review

No independent software task remains. Physical no-fault formatting, echo/prompt
timing, firmware latency, electrical compatibility, shutter-closed reporting,
operating limits and calibration remain **UNTESTED**. Model ratings constrain
software requests; simulator outputs are fixtures. Service/calibration commands
and GUI writes are excluded. Software/simulator PASS is not physical acceptance.

Any later integration requires separately scoped candidate approval under
[HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md), starting with passive open and
one `?SV` query. That procedure covers raw evidence, further reads, completed LBO
warmup before controlled enable, write gates, abort/recovery and shutdown.
Closing software does not change laser/shutter/heater state; follow the manual's
operator cool-down procedure. The present task stops at human review.

Original inputs and framework revision `724a7f772069d3357ea66dbc4742d25bd874a33e`
are preserved ([provenance](../records/FRAMEWORK.md)); upstream remains untouched.
