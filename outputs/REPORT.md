# Compact Verdi driver — candidate review

Software-complete and hardware-ready for review. **Physical behavior, wiring,
timing and calibration remain UNTESTED.** This software work authorizes no hardware
access. Candidate SHA-256: `be0ad6235eb92e38800fe23e6c24f784719d4b5359d43f6b2ac2015a736fa027`; version 0.2.0, based on cfb3f4a.

## Simplification

| Measure | Before | After |
| --- | ---: | ---: |
| Package Python modules | 12 | 8 |
| Package Python lines, including comments/blanks | 1610 | 1335 |
| Classes, including enums, exceptions and typing protocols | 25 | 17 |
| Root public exports | 24 | 12 |
| Exception classes | 7 | 4 |
| Core runtime dependencies | 0 | 0 |

Final modules: controller, protocol, simulator, monitor, gui, errors, __init__,
__main__. Configuration/model fragmentation, separate transport/serialization/CLI
files, query-spec registry, transport replacement, telemetry lifecycle/logging
machinery and compatibility exports were removed. Core operations use direct
keywords and explicit connect/disconnect/read/set/start/stop/status methods.
See [architecture](../ARCHITECTURE.md) and [API migration](../docs/API.md).
This intentionally changes the previous interface; callers must migrate before use.

## Device-control path and behavior

One controller locks one backend. Each operation validates input, encodes one
CR/LF request, exchanges once and decodes one reply. Status holds the lock for 14
sequential reads. Six operations and all 42 manual short queries remain, with
documented units/state codes and preservation of unknown positive fault codes.
The simulator supports this emitted subset using independent in-memory replies;
extra firmware aliases are no longer emulated. Its dynamics are fixtures.

Import/construction cause no I/O. Connect passively opens the explicit port;
disconnect sends no device commands. Timeout, partial write, interruption or
malformed replies permanently invalidate that controller session. DeviceError
denotes a complete rejection whose session remains readable. No automatic replay,
flush, reconnect, mode change or state restoration is implemented. Failed cleanup
can be retried; it does not revive the session or replace an existing error.

Monitoring is optional and synchronous, with a bounded cache and monotonic age.
Applications own scheduling/log sinks. Dash consumes only that cache; Monitor
calls the public status API. The standalone GUI launcher explicitly creates and
joins its polling thread. Core imports do not load monitoring, pySerial, Dash or
Plotly, and simulator/controller/Monitor use starts no implicit thread.

## Validation

[E039](../records/RECORDS.md#e039): **315 tests PASS, 97% coverage, all 11 integrated
stages PASS**, including eight notebook executions, all operator paths with fake
serial connections, strict typing, lint/format, dependencies, wheel/sdist, CLI and
examples, isolated core/GUI installs and watchdog tests. The wheel contains exactly
the eight source modules; core-only installation runs without optional dependencies.
Tests prohibit physical opening/discovery, including in notebook kernels.

The final review fixed non-boolean fault-history selectors that silently selected
the history query, and added five regressions proving rejection before I/O. It also
restored missing test guards, operating documents and the manual to the source
archive, with explicit package checks. Version 0.2.0 identifies the intentional API
break; build validation selects that version's artifacts and the local editable
CLI installation was refreshed. The current user authorized commit and push.

Environment: Windows, Python 3.12.14, Node v24.14.1. One non-failing pyzmq warning;
no failed/skipped tests. Full versions, source/build hashes and commands are in
[validation.json](../records/validation.json). Reproduce with `.[dev,serial,gui]`
installed and `python scripts/validate.py`. GUI verification covers routes,
callbacks, assets and watchdog behavior; old screenshots are historical.

## Remaining hardware assumptions and first interactions

The supplied manual remains authoritative. Hardware framing, actual response
latency, `?F` no-fault text, V5/UNO servo variant, shutter-closed power reporting,
startup/fault recovery behavior and calibration remain unverified. Model ratings
are conservative software ceilings, not proven firmware bounds or site safety
limits. No service, heater, chiller or calibration writes are exposed. See the
[uncertainty register](../docs/PROTOCOL.md#uncertainty-register).

The next physical phase requires explicit Stage 1 approval of this candidate plus
actual model, operator-confirmed port/baud and site conditions. The exact first
interactions are passive `connect()` and one `read("?SV")`, with writes disabled;
capture raw framing/version and compare the front panel. Then follow TEST-010A..C
in [HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md), independently establish the
`?F` clear reply, and return raw responses with units and PASS/FAIL/INCONCLUSIVE
comparisons. Separately approve any TEST-010D..H writes, limits and abort conditions.
There are no pending device operations or required human actions for this cleanup.

Disconnect is not laser shutdown. Normal authorized shutdown explicitly closes
the shutter and enters standby with readbacks; full heater/cooling shutdown follows
the manual. On uncertain I/O, cease commands and use the physical abort procedure.
For software rollback, reinstall a reviewed previous checkout while disconnected;
do not infer or replay laser state. Any new physical integration still requires
candidate review and the documented clean-session procedure.
