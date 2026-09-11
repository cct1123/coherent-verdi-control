# Verdi 0.3.0 — reviewed software candidate

The aggressive simplification is software-complete and hardware-ready for review.
**Physical behavior, wiring, timing and calibration remain UNTESTED.** No physical
ports were opened or discovered. Source SHA-256: `56bbd1fce0bfa82fd92e747684961a913c9264d10a7b965de96f5aa5bbffe5c4`; base 7878823.

## Result

| Measure | 0.2.0 | 0.3.0 |
| --- | ---: | ---: |
| Package modules | 8 | 5 |
| Python lines including comments/blanks | 1335 | 1057 |
| Executable statements | 703 | 521 |
| Classes | 17 | 5 |
| Root exports | 12 | 4 |
| Exception classes | 4 | 2 |
| Required runtime dependencies | 0 | 0 |

The final layout is controller.py, simulator.py, gui.py, __init__.py and __main__.py.
The complete physical path is in controller.py: validate, encode, exchange once,
decode. One lock serializes transactions and full status groups. SimulatedVerdi
inherits the public API and failure handling and supplies independent wire replies.
All 42 manual queries and six command forms remain supported.

Removed transport classes/interfaces, configuration/state/query enums, result
dataclasses, fault metadata objects, serialization adapters, monitor sequence
counters and three thin modules. Returned dictionaries/lists can be serialized
directly and cannot mutate hardware or subsequent samples. Fault meanings moved
to the protocol reference. The CLI is now read-only and prints results directly;
the Python control examples retain explicit writes and verified normal shutdown.
Redundant integration documentation and monitor test files were merged. No runtime
compatibility aliases remain; [migration instructions](../docs/API.md#migration-to-030)
cover earlier releases. Across both pruning passes, 12 modules became 5 and 1610
Python lines became 1057.

## Reliability and integration

Import/construction cause no I/O. Connect passively opens an explicit native port;
disconnect sends no commands. The experiment owns lifetime, polling and logging.
Timeout, partial write, malformed reply or interruption latches failure. A failed
controller cannot reconnect/replay; cleanup remains retryable. Complete DeviceError
rejections retain their instruction/reply and leave the session usable. The GUI's
source label does not control fault parsing; physical ?F clear text must be verified.

The optional Monitor in gui.py polls the public status API from one application
caller and protects copied bounded snapshots with a short lock. Dash only reads
the cache. Neither starts a worker; the standalone simulator GUI launcher explicitly
starts and drains its worker before disconnect. No core import loads pySerial,
Dash or Plotly. Ordinary json.dumps and the application's logger replace custom
logging/serialization. See [architecture](../ARCHITECTURE.md) and [README](../README.md).

## Validation and review

[E041](../records/RECORDS.md#e041): **322 tests PASS, 97% coverage, all 11 stages PASS**.
Includes eight guarded notebook executions, fake serial I/O/failure/concurrency,
all operator paths using simulation, lint/format, strict typing, pip check,
wheel/sdist builds, CLI/examples, isolated core/GUI installs and browser watchdog.
Final review checked active documentation links, visible notebook functions against
the terminal runner, package inventory and removal of obsolete imports. No remaining
actionable software review finding was identified. Source hashes remained unchanged
during the full run; a later markdown-only notebook note correction is recorded in
the manifest, with all code cells and other source files verified unchanged.

Environment: Windows, Python 3.12.14, Node v24.14.1. No failed/skipped tests; one
non-failing pyzmq selector-thread warning. GUI validation covers HTTP routes,
callbacks, assets and watchdog behavior; retained screenshots are historical evidence.
[validation.json](../records/validation.json) contains versions, commands and current
source/build hashes; logs/notebook outputs are regenerable. Final packaging is
refreshed after this checkpoint; its result is recorded in that manifest.

## Physical limits and next phase

The supplied manual remains authoritative. Actual framing/latency, ?F clear text,
V5/UNO servo variant, closed-shutter power, fault recovery and calibration remain
unverified. Model ratings are conservative software ceilings, not site safety limits
or proven firmware ranges. Simulator temperatures, currents, warmup and dynamics are
fixtures. See [protocol uncertainties](../docs/PROTOCOL.md#uncertainty-register).

Future hardware work requires explicit Stage 1 approval of this candidate plus the
actual model, operator-confirmed port/baud and site conditions. First passively
connect with writes disabled, then issue one read("?SV"). Capture raw framing/version
and compare the front panel. Follow TEST-010A..C in
[HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md); independently establish ?F clear
semantics and return raw responses, units and PASS/FAIL/INCONCLUSIVE comparisons.
Any TEST-010D..H writes require separate approval, limits and abort conditions.

Disconnect is not laser shutdown. Normal authorized shutdown explicitly closes
the shutter and enters standby with readbacks; complete heater/cooling shutdown
follows the manual. On uncertain I/O, cease commands and use the physical abort
procedure. Software rollback means reinstalling a reviewed checkout while
disconnected; never infer or replay laser state. No human action is needed for
the requested software cleanup and authorized Git publication.
