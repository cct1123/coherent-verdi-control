# Engineering records

Durable evidence and decisions; append new records with stable IDs rather than
rewriting historical results. STATE.md identifies current acceptance evidence.
Generated logs stay local; only the latest validation manifest is versioned.

## E001

Date: 2026-09-09T18:55:00-05:00
Kind / scope: Repository and framework inspection; TEST-001 / REQ-001.
Claim: Target initialized from the requested framework without overwriting useful inputs.
Method: Inspect initial Git status and files; retrieve the upstream commit and
seven core files by HTTPS; compare source and target hashes.
Result: Initial target had only the manual and prompt log, no commits or code.
Core instructions copied; PROJECT.md populated; PROJECT.md, AGENTS.md and STATE.md
read before implementation. PASS. Original hashes and pinned framework in
[FRAMEWORK.md](FRAMEWORK.md). Target remote retained. Upstream had read-only access.
Limitations: No physical device inspection performed or authorized.

## E002

Date: 2026-09-09T19:00:00-05:00
Kind / scope: Manual inspection; TEST-002 / REQ-002.
Method: Extract relevant PDF text; visually inspect Table 5-1, command continuation,
fault table (PDF pages 50, 54, 56); inspect sections 2 and 4 for ratings/shutter behavior.
Result: Confirmed CR/LF handshaking, empty command acknowledgment, 19200/8N1,
42 query forms, reversed PROMPT setting and LASER ON fault-history clearing.
Recorded ambiguity in active no-fault reply, exact echo timing, shutter-closed
power reporting and simulator dynamics. [Protocol contract](../docs/PROTOCOL.md).
Limitations: Source inspection only; firmware conformance is UNTESTED.

## D001

Date: 2026-09-09T19:01:00-05:00
Decision: Own one transport in a serialized controller; optional Dash consumes one
bounded telemetry cache. No construction/recovery/close device commands; explicit
write opt-in and no automatic replay. Keep core dependency-free and physical factory
separate, disabled by default. CLI remains simulator-only in this phase.
Basis: PROJECT.md hardware-free constraint, E002; untagged replies cannot correlate
late data to subsequent instructions. REQ-002 through REQ-009.
Consequence: Failed serial sessions need explicit replacement and later observed
resynchronization. GUI is a read-only monitor; API provides operational writes.
Reconsider if: Authoritative firmware evidence or approved scope changes.

## E003

Date: 2026-09-09T19:11:00-05:00
Kind / scope: Software and simulator test; TEST-002 through TEST-006 / REQ-002–006,009.
Method: `.venv/Scripts/python -m pytest -q --cov=coherent_verdi --cov-report=term-missing`;
strict mypy on src/coherent_verdi. Windows, Python 3.12.14, no hardware.
Result: 93 tests PASS; 93% statement coverage; strict typing PASS for 12 modules.
Coverage is aggregate, not a physical-safety claim. A sandbox-only pytest cache
warning occurred; no tests were skipped or failed. Serial constructors/discovery
are patched to reject hardware calls; factory tests replace them with explicit fakes.
Bearing: Functional implementation established; hardening and final installation review remain.

## E004

Date: 2026-09-09T19:15:00-05:00
Kind / scope: Diagnostic regression; TEST-003 / REQ-003.
Method: Fake monotonic clock makes final LF arrive 0.02 s into a 0.01 s transaction;
`test_complete_reply_arriving_after_deadline_is_rejected`.
Result before fix: FAIL (did not raise ResponseTimeout). The read loop checked the
deadline before reads but accepted a complete late terminator without checking again.
Fix: Recheck deadline immediately after each read before accepting reply completion.
Result after fix: 95 tests PASS (including lost-acknowledgment simulation), strict
mypy PASS. A lost-ack scenario proves the command may execute despite an exception
and is not replayed. These results supersede E003 for changed components.

## D002

Date: 2026-09-09T19:16:00-05:00
Decision: Do not infer undocumented behavior from simulator success. Preserve raw
representations where layout/units are unclear; use model ratings as conservative
software ceilings and explicitly record their distinction from firmware limits.
Basis: E002 and [uncertainty register](../docs/PROTOCOL.md#uncertainty-register).
Consequence: No invented extra-diode or service/calibration commands; actual no-fault
reply and shutter reporting must be verified at the human review boundary.

## E005

Date: 2026-09-09T19:18:30-05:00
Kind / scope: Browser UI validation with simulator; TEST-006/008 / REQ-006/008.
Method: Run `python -m coherent_verdi --demo gui --port 8050` on loopback; inspect
rendered Dash UI and console; capture full page.
Result: LIVE synthetic 1.000 W, setpoint 1.0000 W, ON, OPEN, thermal/diagnostic
panels and bounded plot rendered correctly. No browser warning/error log entries.
Screenshot: [simulator-dashboard.png](../docs/images/simulator-dashboard.png).
The local server was stopped after inspection. No physical port opened. The first
sandboxed server launch could not bind a socket; the approved loopback-only run
succeeded. This was an execution-environment constraint, not a hardware dependency.

## E006

Date: 2026-09-10T00:22:14+00:00
Kind / scope: Integrated hardware-free validation; TEST-001..009 / REQ-001..009.
Method: `python scripts/validate.py`; Windows, Python 3.12.14; candidate
`1be9d2c0a29a757eeb31b9d5ab294e1f34aac3232fde571d16838332c6603814`.
Result: 108 tests PASS, 94% coverage; Ruff lint/format PASS; strict mypy PASS;
dependency check PASS; wheel and sdist builds PASS; CLI/examples PASS; clean wheel
install into a fresh no-extras environment PASS; preserved-input hashes PASS.
Artifacts at the time: `validation-initial.json` and `validation-initial.log`
(local generated files, excluded from Git). The result above is retained as history.
Bearing: Software behavior established. Final review found a remaining browser
server-loss presentation gap; REQ-006/008 validation for the revised GUI must be
rerun. No physical validation claimed.

## E007

Date: 2026-09-09T19:28:20-05:00
Kind / scope: Browser outage regression and final GUI review; TEST-006/008.
Observation: A clientside Dash callback depending on the pending server callback
never updated its warning after server shutdown. The first outage check FAILed.
Diagnosis: The watchdog must not depend on the Dash callback scheduling graph.
Fix: Independent JavaScript timer reads an otherwise hidden heartbeat in the DOM,
uses browser-monotonic receipt time, and owns only warning text and stale CSS class.
No network or hardware polling is performed by this timer.
Validation: With the revised simulator dashboard LIVE, stop its loopback server,
wait more than 10 s, then inspect the browser. PASS: `SERVER UPDATE LOST` warning,
all values explicitly labeled stale, LIVE indicator hidden and current tiles dimmed.
[Live screenshot](../docs/images/simulator-dashboard.png) and
[server-offline screenshot](../docs/images/simulator-server-offline.png).
Automated method: `node scripts/test_watchdog.cjs` with bundled Node; virtual-clock
startup, fresh receipt, expiry and recovery checks PASS. Updated Dash route/callback
checks: 16 PASS; strict Python typing PASS. Tests verify both GUI assets are served;
clean wheel smoke test now also requires the watchdog asset.
Limitations: Browser warnings require browser execution; a suspended OS/tab updates
on resume. In-flight tabs from a different application version require reload.
The simulator server and temporary test tab are closed. Physical Verdi UNTESTED.

## E008

Date: 2026-09-10T00:29:15+00:00
Kind / scope: Final integrated software/simulator acceptance; TEST-001..009.
Candidate: `5c4ec6654c4cfdc39fbeb32e5a2af1fbbc4ece08152b25cd368ee5d084c0dd95`.
Method: `python scripts/validate.py` on Windows/Python 3.12.14; no hardware.
Result: 108 pytest tests PASS (1.66 s), 94% statement coverage; Ruff lint/format PASS;
strict mypy PASS (12 modules); pip dependency check PASS; sdist/wheel build PASS;
CLI and both examples PASS; isolated no-extras wheel import/assets/entrypoint and
both examples PASS. Original input/framework hashes PASS. Source unchanged during
validation. No skipped tests or pytest warnings in the final run.
Artifacts at the time: `validation.json`, `validation.log`, `junit.xml`.
The latest run replaces these generated files; this historical result is superseded
by later acceptance records after source changes.
Bearing: Supersedes E006 for changed GUI/package files; REQ-001..007 and REQ-009 PASS
within software scope. E007 separately validates real browser outage presentation.
Physical firmware behavior and calibration remain UNTESTED.

## E009

Date: 2026-09-09 (America/Chicago), final review after E008.
Kind / scope: Software-side candidate review; TEST-008/009 / REQ-008/009.
Method: Inspect public API, ownership, timeout/recovery behavior, model/units,
fault preservation, simulator assumptions, GUI boundaries, packaging and operating
instructions. Check source hashes, local documentation targets and preserved inputs.
Result: Documented operational API, architecture, simulator limitations, two verified
browser screenshots, installation/examples/troubleshooting and staged physical
validation procedure are present. Commands and hardware access remain explicit;
no physical port was probed, enumerated or opened. No remaining software gap within
the documented candidate scope. Configured remote CI has not been executed.
Outcome: HARDWARE_READY software review completed; checkpoint moved to
AWAITING_HUMAN_REVIEW under AGENTS.md. No hardware approval inferred from prompt log.
Artifacts: [report](../outputs/REPORT.md), [state](../STATE.md),
[hardware procedure](../HARDWARE_VALIDATION.md). Physical validation UNTESTED.


## E010

Date: 2026-09-09 (America/Chicago), publication review after E009.
Kind / scope: Software review and diagnostic regressions; TEST-002/003/007.
Authorization: User requested "review, prune. commit, push." Software changes and
publication to the target repository are authorized; hardware remains prohibited.
Findings: Response stripping accepted TAB/VT/FF as harmless whitespace, including
an invalid command acknowledgment. KeyboardInterrupt during a transaction left
its transport reusable despite a possible pending untagged response. Validation
subprocess failures could leave a previous PASS manifest as the apparent result.
Method: Add malformed control-byte cases and interrupt a fake stream read.
Before fix: 5 regression failures; 60 related tests passed. After rejecting control
bytes before trimming spaces and poisoning interrupted sessions: 65 focused tests
passed. Add timeout, launch failure and interrupt tests for the validation runner;
write RUNNING before execution and FAIL on abnormal termination. Final integrated
results are recorded separately below. No physical connections used.
Bearing: E008/E009 do not establish acceptance of these changed components.

## D003

Date: 2026-09-09 (America/Chicago).
Decision: Prune bootstrap format examples and duplicated handoff prose. Keep the
manual, current validation manifest, dependency snapshot, screenshots and durable
conclusions. Ignore historical prompt input and generated logs/XML; preserve those
local files unchanged. CI uploads JUnit results as per-job artifacts. Normalize
published text to LF through .gitattributes so Git blobs match candidate hashes.
Basis: Explicit user review/prune/publication request; reproducibility and clear
review history without versioning temporary machine output. REQ-001/007/008.
Consequence: Clean clones need no local prompt log. Its hash is checked if present;
manual and original framework hashes remain mandatory checks. AGENTS.md and
ARCHITECTURE.md remain byte-for-byte upstream copies. Upstream remains untouched.


## E011

Date: 2026-09-10T00:41:07.930567+00:00
Kind / scope: Reviewed candidate integrated software/simulator validation; TEST-001..009.
Candidate: `50d96d36801e5d2acf905a4ce53664ef6e74761c315d80186236f7ca12437b82`.
Method: `python scripts/validate.py`; Windows 11/Python 3.12.14, isolated temp
installation, no hardware. `node scripts/test_watchdog.cjs`; Node 24.19.0.
Result: 116 pytest tests PASS (1.73 s), 94% statement coverage; no skips/warnings.
Ruff lint/format PASS, strict mypy PASS (12 modules), dependencies PASS, wheel/sdist
PASS, CLI and both examples PASS, clean no-extras wheel installation PASS.
Node startup/live/expiry/recovery PASS. Preserved inputs/framework hashes PASS;
source manifest unchanged during validation. Validation-runner failure tests PASS.
Artifacts: [current manifest](validation.json), [versions](requirements-validated.txt).
Raw `validation.log` and `junit.xml` are generated locally and excluded from Git.
Bearing: Supersedes E008/E009 acceptance for changed components after E010 review.
E007 browser evidence remains applicable because GUI assets are unchanged.
Software criteria PASS; physical behavior/calibration remain UNTESTED.


## E012

Date: 2026-09-10T00:49:00+00:00.
Kind / scope: Published baseline CI reconciliation; TEST-007 / REQ-007.
Candidate: Git 48c0cbd46f510d5ba3843f773c6aca3be8096479 (E011 source manifest).
Method: Read GitHub Actions run and all six job conclusions through the API.
Result: All Windows/Linux Python 3.11, 3.12 and 3.13 jobs completed successfully,
including lint, formatting, typing, pytest, build, examples, isolated installation
and Node regression. PASS for the published baseline, not subsequent edits.
Artifact: [CI run 34422531888](https://github.com/cct1123/coherent-verdi-control/actions/runs/34422531888).
Bearing: Replaces the prior "CI not run" uncertainty. Latest user authorization
explicitly reopens independent software work; hardware access remains prohibited.

## E013

Date: 2026-09-10T00:52:00+00:00.
Kind / scope: Independent interface audit and diagnostic regressions; TEST-002..009.
Findings before fixes: Oversized integer replies escaped as ValueError and left
controllers usable. GUI reads waited on the controller lock; empty exceptions
produced LIVE despite missing status; a wall-clock rewind produced negative age;
a static source badge survived replacement. Failed/interrupted close could not
retry cleanup, failed replacement left the old controller usable, and interrupted
open leaked cleanup. CLI watch buffered output and returned success after failed
samples. The sdist included validation tests but omitted their scripts and examples.
The main validation command did not execute the JavaScript watchdog test.

Method/results: Runtime probes reproduced the numeric and GUI failures. Five new
resource lifecycle cases failed before the fix, then 50 related lifecycle/API/
transport/hardening cases passed. Four numeric conversion regressions plus existing
protocol/API tests: 75 PASS. Nine new client edge cases plus existing GUI/CLI/API
tests: 44 PASS. Cleanup/validation-runner suite: 9 PASS. The latter injects a JS
failure to prove the integrated validator cannot claim PASS. Ruff and typing PASS
in focused checks. Archive inspection confirmed all five scripts/examples missing;
MANIFEST.in and archive completeness checks added, requiring final rebuild.

Changes: Convert integer conversion errors to ProtocolError; typed cache snapshots
with monotonic age and per-sample source; explicit unavailable/error presentation;
flushed watch output and failed exit; retryable cleanup with I/O disabled; preserve
primary open exception; package supporting source files; include Node in validation.
Manual review reconfirmed all 42 queries, operational command forms and fault codes.
No source-supported simulator contradiction justified changing documented fixture
policies or inventing physical timing. Final integrated acceptance follows below.

## D004

Date: 2026-09-10T00:52:00+00:00.
Decision: GUI consumes only immutable telemetry snapshots, never controller metadata
that can contend with acquisition. Status captures source kind under the same lock
as its sample; monotonic age is measured from the polling attempt's start. Failed
samples have no current source, and changing simulated/physical source clears plotted
history while preserving sequence numbers. UTC remains the recording/display clock.
Basis: E013 lock contention, false freshness and source mislabeling. REQ-003/005/006.
Consequence: Source and freshness describe the displayed sample, not a replacement
connection or wall-clock assumption. No GUI code acquires or polls a serial owner.
Cleanup failures disable I/O but allow explicit cleanup retry; no commands are replayed.


## E014

Date: 2026-09-10T00:55:00+00:00.
Kind / scope: Current browser rendering and server-loss regression; TEST-006/008.
Method: Start `python -m coherent_verdi --demo gui --port 8050` on loopback,
inspect the actual in-app browser, capture full-page screenshots, stop the server,
then inspect the warning after its 10-second stale interval.
Result: PASS. SIMULATOR, LIVE, 1.000 W measured, 1.0000 W setpoint, ON, OPEN,
thermal/status fields and plot rendered. Live browser console warnings/errors: none.
After server stop: SERVER UPDATE LOST, all displayed values labeled stale, LIVE
indicator hidden, tiles and thermal/status fields dimmed. Updated the
[live screenshot](../docs/images/simulator-dashboard.png) and
[offline screenshot](../docs/images/simulator-server-offline.png).
The fake server and temporary browser tab are closed. No physical access occurred.
Bearing: Supersedes E007 for current GUI source. E013 additionally tests empty
errors, monotonic freshness, source changes and cache responsiveness during blocked I/O.


## E015

Date: 2026-09-10T00:55:27.405946+00:00
Kind / scope: Final continued-engineering acceptance; TEST-001..009 / REQ-001..009.
Candidate: `a731d6a9db7bc9db8e642c67bbba3d0f18d8209b2458caea3a17c85c1cca94e4`.
Method: `python scripts/validate.py` with VERDI_NODE set to bundled Node 24.19.0;
Windows 11/Python 3.12.14, isolated temp install, entirely hardware-free.
Result: 135 pytest tests PASS (2.09 s), 94% statement coverage; no skips/warnings.
Ruff lint/format PASS, strict mypy PASS for 12 modules, dependency consistency PASS,
wheel/sdist build PASS, source archive completeness PASS, CLI and both examples
PASS, isolated no-extras wheel install/import/typing marker/assets/entrypoint/examples
PASS, integrated Node watchdog PASS. Manual/framework/input hashes PASS and source
unchanged throughout validation. Raw logs/XML are local generated artifacts.
Artifacts: [manifest](validation.json), [versions](requirements-validated.txt);
current browser evidence E014. E013 regressions and package omission are resolved.
Bearing: Supersedes E011 for changed software. All hardware-independent requirements
have current PASS evidence; physical protocol/calibration remain UNTESTED. Remote
matrix results from E012 apply only to the published baseline until a new run finishes.


## E016

Date: 2026-09-10T01:00:49Z (GitHub run completion).
Kind / scope: Final source cross-platform CI acceptance; TEST-007 / REQ-001..009.
Candidate: Git c8950609eab0ca6e34bf1bd63a547b141fd315e1; all 47 committed candidate
file hashes match E015. Evidence-only checkpoint/report edits leave source unchanged.
Method: Push reviewed candidate, read run and every job conclusion through GitHub API.
Result: PASS, all six jobs: Ubuntu and Windows, each with Python 3.11, 3.12 and 3.13.
Every job completed lint, formatting, strict typing, 135 tests, build, both examples,
source archive/isolated wheel installation smoke and Node watchdog checks. No hardware.
Artifact: [CI run 34423561052](https://github.com/cct1123/coherent-verdi-control/actions/runs/34423561052).
Bearing: Supersedes E012 for current software; closes remote matrix uncertainty.
All software/simulator requirements now have current local and CI PASS evidence.
Physical protocol and calibration remain UNTESTED and outside authorized scope.


## E017

Date: 2026-09-09 (America/Chicago), publication review after E016.
Kind / scope: Review and pruning; TEST-003/005/006/007/008.
Authorization: User requested "review, prune. commit, push."
Method: Inspect the latest controller/transport cleanup, telemetry/cache/source
boundaries, CLI, validation runner, installed-archive checks and their regressions.
Result: No new actionable runtime defect. Removed duplicated Dash callback request
builders and validator setup in favor of shared pytest fixtures. Guarded joining
an unstarted test thread so setup failures preserve their original diagnostic.
Condensed repeated checkpoint/report prose; retained original inputs, all assertions,
acceptance criteria, physical limitations and durable historical records.
Runtime package, assets, examples, build configuration and hardware guards remain
unchanged. Integrated acceptance of the test cleanup is recorded next.


## E018

Date: 2026-09-10T01:05:40.459186+00:00
Kind / scope: Post-pruning integrated acceptance; TEST-001..009 / REQ-001..009.
Candidate: `7b3c7d8cf51378f091fa5adf459c5d3e35df2a223286de01bc04636028199c81`.
Method: `python scripts/validate.py`, Windows/Python 3.12.14, Node 24.19.0, no hardware.
Result: 135 tests PASS (2.03 s), 94% coverage, no skips/warnings. Lint/format,
strict mypy (12 modules), dependencies, wheel/sdist/archive, CLI/examples, isolated
no-extras wheel installation and Node watchdog PASS. Input/framework hashes PASS;
source unchanged during validation. [Manifest](validation.json) records current hashes.
Bearing: Supersedes E015 for the pruned test suite; runtime code/assets remain
unchanged from E016's passing CI candidate. E014 browser evidence remains applicable.
No new runtime finding. Physical validation/calibration remain UNTESTED.

## E019

Date: 2026-09-10, final hardware-free production/usability review.
Kind / scope: Inspect → gap → design → implement → test → diagnose; REQ-002..008.
Baseline: E018. User explicitly requested renewed software hardening before review.
Method: Review all runtime layers, lifecycle ownership, public models, manual query
catalog/units/faults, client callbacks, installed distributions, documentation and
regressions. Bounded protocol and API/lifecycle audits were delegated under AGENTS.md.
Findings and diagnoses:

- Manual p. 4-2 states the diode cannot turn on while the LBO warms and key ON
  reports fault 5. The fixture previously accepted premature enable and could
  emit automatically at readiness. New cold-start tests initially failed; the
  simulator now reports fault 5 and refuses ON during warmup. Its conservative
  post-warmup FAULT latch requires explicit enable and is documented as fixture
  policy, not an inferred firmware promise. Focused simulator/controller: 24 PASS.
- Mutable telemetry controller/interval could mislabel model identity or bypass
  the validated polling delay. Both are now read-only properties; reconfiguration
  creates a new service. A throwing application logging handler could prevent
  error publication and kill acquisition. Publication now precedes logging,
  releases cache/sample locks, and isolates sink Exceptions. Joining a worker
  while holding the lifecycle lock could block a handler inspecting `running`;
  shutdown now joins outside that lock and clears only the captured worker.
- Async example cancellation could leave a worker running while the event-loop
  thread tried to close its controller. One worker now owns operations and cleanup;
  its cancellation regression verifies cleanup stays with the in-flight worker.
  Lifecycle/client/telemetry focused checks: 35 PASS; typing/lint/format PASS.
- Clean installation previously exercised only the core wheel. Added a separate
  fresh GUI/serial installation check and standalone installed-Dash HTTP smoke:
  assets, no data, live data, known/unknown faults, timeout, recovery, bounded
  history and zero callback acquisition. Core installation now also verifies the
  missing-GUI CLI error. Both modes are in the acceptance runner and CI workflow.
- Added a public API reference, expanded install/warmup/troubleshooting guidance,
  and refined the later physical procedure: completed LBO warmup before enable,
  one connection owner across read/write stages, exact shutter commands and an
  operation evidence form with measured tolerance basis. Executed all six Python
  snippets across README and docs successfully, entirely with simulators.

No additional actionable defect found in serial deadlines, failure poisoning,
explicit replacement/cleanup, documented command forms, numeric units/model ceilings,
fault decoding or cache-only Dash state. Integrated acceptance follows in E021.
This finding supersedes E018's no-new-defect statement for the newly examined cases.

## D005

Date: 2026-09-10.
Decision: Keep device facts, simulator policy and application lifecycle distinct.
Cold key ON/fault 5 is manual-grounded; post-warmup re-enable is a conservative
fixture policy. Telemetry configuration is immutable and failed acquisition is
published before external logging. Async examples keep operation and resource
ownership in one worker even when the awaiting task is canceled.
Basis: E019 reproduced warmup, metadata, logging and cancellation gaps.
Consequence: No automatic laser enable, command replay, hidden callback polling,
or physical recovery assumption was introduced. Hardware remains UNTESTED.

## E020

Date: 2026-09-10T01:18:45+00:00.
Kind / scope: Current real-browser simulator smoke; TEST-006/008.
Method: Run `python -m coherent_verdi --demo gui --port 8050` on loopback, inspect
the browser's actual rendered/accessibility state and console, save full-page
screenshots. Stop the simulator server and wait beyond the 10-second watchdog.
Result: PASS. SIMULATOR/LIVE, 1.000 W, 1.0000 W setpoint, ON/OPEN, LOCKED servo,
thermal/status fields and chart rendered without clipping. Live console warnings
and errors: none. After stopping the server, SERVER UPDATE LOST appeared, LIVE
was hidden, and all retained values were visibly dimmed and labeled stale.
Artifacts: [live](../docs/images/simulator-dashboard.png) and
[server offline](../docs/images/simulator-server-offline.png) simulator screenshots.
An initial offline capture preceded the watchdog deadline; it was replaced with
the verified post-deadline capture. Both test servers and browser tabs are closed.
Bearing: Supersedes E014 for the current candidate. No physical access occurred.

## E021

Date: 2026-09-10T01:19:54.046692+00:00.
Kind / scope: Final production/usability acceptance; TEST-001..009 / REQ-001..009.
Candidate: `e47efd04594643e98c1778a7400c0a201ffc987cf2d1d24e13f93f585c85a811`.
Method: `python scripts/validate.py`, Windows/Python 3.12.14, Node 24.19.0,
hardware prohibited. Source/docs/screenshots finalized before the run.
Result: 145 tests PASS (2.63 s), 95% statement coverage, no skips/warnings.
Ruff lint/format, strict mypy (12 modules), dependency consistency, wheel/sdist
build and archive completeness PASS. CLI and both examples PASS. Separate clean
environments pass core installation without dependencies and GUI/serial extras
installation, including installed module/typing/assets, console entrypoint, both
examples, missing-GUI error, Dash HTTP assets and callbacks across no data, live,
fault, timeout and recovery states. Callback checks prove no acquisition occurs
during rendering. Extras versions: Dash 4.4.1, Plotly 6.9.0, pySerial 3.5.
Integrated Node watchdog startup/receipt/expiry/recovery PASS. Input/framework
hashes match and source remained unchanged throughout the complete run.
Artifacts: [manifest and build hashes](validation.json), [versions](requirements-validated.txt),
local generated validation.log/JUnit; fresh browser/screenshots E020.
Bearing: Supersedes E018 for the changed candidate. E019 defects and installation
coverage gaps are resolved. Earlier E016 remote matrix evidence is historical;
this changed candidate has current local Windows/Python 3.12.14 acceptance.
Software validation: PASS. Simulator validation: PASS.
Physical Verdi validation: UNTESTED. No independent software work remains.

## E022

Date: 2026-09-09 (America/Chicago), publication review after E021.
Kind / scope: Review, prune, commit and push; TEST-002..009.
Authorization: User requested "review, prune. commit, push."
Method: Inspect all pending runtime, simulator, lifecycle, installation, regression
and documentation changes; compare the candidate to E021 before publication.
Result: No new actionable runtime defect. Pruned repeated architecture, navigation
and review-result prose from outputs/REPORT.md; retained requirements, detailed
evidence, user documentation, screenshots, every assertion and hardware guard.
Publication checks: 145 tests PASS (1.11 s), Ruff lint/format PASS, strict mypy
PASS for 12 source modules. The 51 candidate file hashes still match E021 exactly;
its full build/install/GUI acceptance remains applicable. Only checkpoint/report
and durable evidence changed during this pruning pass. Physical validation remains
UNTESTED; publishing the software grants no permission to access hardware.

## E023

Date: 2026-09-10, aggressive simplification after Git 34b5c37.
Kind / scope: User-authorized reduction of scaffolding while preserving behavior;
TEST-002..009 / REQ-002..009. No physical access authorized or performed.
Method: Map runtime imports, public uses, validation flow and all test functions;
audit abstractions against current correctness, ownership, safety and reuse needs.
Changes:

- Controller query decoding and value parsing now share one failure path. Removed
  `_number`/`_integer` conversion wrappers; status builds named fields directly,
  retaining query order and computing duration after all 14 reads. The new virtual
  timing regression proves the full 1.75 s fixture duration is included.
- Removed duplicate cached model metadata from telemetry and its redundant worker
  loop branch. Configuration remains immutable, sample/error history bounded, and
  snapshot access still uses no serial transaction lock. Allowed baud values now
  have one definition shared by configuration validation and protocol parsing.
- Dash callbacks produce plain figure dictionaries, replacing graph-object builder
  calls and removing the redundant direct Plotly constraint/type-check override.
  Dash supplies Plotly itself. Merged identical error/offline CSS declarations.
- Consolidated tests by protocol, transport, controller/simulator, telemetry and
  clients: seven fragmented files replaced by two subsystem files, net five fewer.
  Combined duplicate test factories/fakes and one duplicate close-failure case;
  preserved regression assertions. Fixed Windows-default decoding of an em dash
  introduced during the merge. Subsystem checks then passed. Total test count
  returns to 145 with the new acquisition-duration regression.
- Merged GUI install smoke into install_smoke.py. One clean environment verifies
  the dependency-free core, then installs GUI/serial extras for isolated callback
  checks. Removed the external `--extras` mode and duplicate environment setup.
  Narrowed the subprocess helper to its actual cwd argument, with bounded execution
  and visible failure output. CI now invokes the same validator used locally.
- Removed an obsolete acceptance condition pinning ignored `prompt log.txt` to a
  historic checksum. The first full run passed all executable checks, source
  consistency and authoritative manual/framework hashes, but failed solely because
  this unrelated local reference had changed since the earlier run. It is neither
  a source input nor a clean-clone requirement; its contents remain untouched.
  Current local reference SHA-256: 9de6c1fc9b7506ed5fdffc104651ddd5948d33d8e17cc0ceee2e028f372aee01.
- Updated the architecture diagram to show controller-owned I/O and pure protocol
  functions, removed its duplicate and repeated API summaries from integration
  docs, and executed all six remaining documentation Python snippets successfully.

Incremental controller/protocol/telemetry/client checks: 116 PASS before the timing
case, then controller checks 36 PASS. Lint/format/typing PASS. An isolated validator
test attempt encountered sandbox denial on the host temporary directory; the final
pipeline uses workspace temporary fixtures. Final complete acceptance follows E025.

## D006

Date: 2026-09-10.
Decision: Keep one controller owning either serial or simulated transport, pure
protocol functions, immutable public models/errors, and one bounded telemetry worker
borrowed by GUI clients. Keep public imports/signatures and documented CLI behavior.
These isolate the actual vendor/I/O boundary, prevent competing serial owners and
preserve fault/recovery contracts. Retain deterministic clocks, finite/range guards,
failure poisoning, cleanup retries, safety-shutter semantics, typed query catalog,
JSON serialization reused by CLI/examples, packaging and durable evidence.
Remove wrappers, duplicate state/configuration, duplicate validation orchestration
and audit-round test fragmentation. Do not add replacement frameworks or break
actively used interfaces merely to reduce module count. No upstream template edit.

## E024

Date: 2026-09-10, simulator browser check after GUI simplification.
Kind / scope: TEST-006/008 browser rendering and server-loss behavior.
Method: Launch simulator-only loopback Dash, inspect actual rendered/accessibility
state and live console, capture full-page image; stop server, wait beyond watchdog
deadline and inspect/capture stale state.
Result: PASS. Both plain-dictionary traces, W/UTC axes, 1 W live simulator data,
thermal fields, configured model, servo/state/shutter and source label render.
No live browser console warnings/errors. After server stop, SERVER UPDATE LOST
appears, LIVE is hidden, and displayed values are dimmed and labeled stale.
Updated [live](../docs/images/simulator-dashboard.png) and
[offline](../docs/images/simulator-server-offline.png) screenshots. Server/tab closed.
This supersedes E020 for the changed figure implementation. No hardware accessed.

## E025

Date: 2026-09-10T04:03:18.050817+00:00.
Kind / scope: Complete simplification acceptance; TEST-001..009 / REQ-001..009.
Candidate: `4606c649bd71fcd27cb750365f11310beb4d4360f0b0b7b2e8305ecd543c738e`.
Method: `python scripts/validate.py` with workspace temporary fixtures and Node
24.19.0; Windows/Python 3.12.14. Entirely hardware-free.
Result: 145 tests PASS (1.48 s), 95% statement coverage, no skips/warnings.
Ruff lint/format PASS, strict mypy PASS (12 modules), pip consistency PASS,
wheel/sdist builds and archive completeness PASS, CLI and both examples PASS.
Isolated core installation/entrypoint/assets/examples/missing-extra behavior PASS;
GUI/serial extras then installed in the same clean environment and installed HTTP
callbacks/known and unknown faults/error/recovery/history bounds PASS. Resolved
versions: Dash 4.4.1, Plotly 7.0.0, pySerial 3.5. Development GUI/browser uses
Plotly 6.9.0. Node watchdog startup/expiry/recovery PASS. All 45 source-file hashes
unchanged during validation; supplied manual and pinned framework hashes match.
Current screenshots/browser evidence E024; documentation snippets E023.
Artifacts: [manifest/build hashes](validation.json), local validation.log/JUnit.
Reduction relative to 34b5c37: code files under src/tests/scripts 30 → 24 (−20%);
Python/JS/CSS lines 3,339 → 3,218 (−121, −3.6%). Excludes docs/workflow/records.
Final pruning review retained only current public, hardware, lifecycle, testing,
packaging and reproducibility boundaries described in D006 and the report.
Bearing: Supersedes E021/E022 for current source. Software validation PASS;
simulator validation PASS; physical Verdi validation UNTESTED. No remaining
independent software work under this cleanup request; hardware review gate retained.

## E026

Date: 2026-09-10T04:08:14+00:00, publication review after E025.
Kind / scope: Review/prune/commit/push of the simplified candidate; TEST-002..009.
Authorization: User requested "review, prune. commit, push."
Method: Review runtime reductions, consolidated regression suites, merged clean
installation flow, CI delegation, documentation and excluded local artifacts.
Result: No new actionable runtime defect or further justified source deletion.
Retain the six-file/121-line reduction and all meaningful regression coverage.
Publication checks: 145 tests PASS (0.83 s), Ruff lint/format PASS, strict mypy PASS
for 12 source modules. All 45 candidate hashes exactly match E025; its complete
build/install/GUI evidence remains current. Public exports unchanged; diff checks
PASS. Fetched origin and confirmed no branch divergence before publication.
Only checkpoint/evidence prose changed during this review. No hardware access;
physical Verdi validation remains UNTESTED and publication grants no hardware approval.

## D007

Date: 2026-09-10; user-requested beginner command-control tutorials.
Decision: Teach four progressively broader workflows: read-only status/diagnostics,
bounded setpoint/readback in standby, one enable–safety-shutter–standby session,
and fault evidence/uncertain write handling. Pair each small script with a notebook
containing the same visible source; AST comparison prevents executable-code drift.
Application functions accept a controller; only entry points construct simulators
and change fixture conditions. Reuse the existing driver without changing its API.
No executable hardware switch, remote keyswitch, cycling shutter loop, auto-enable,
retry or blind cleanup is introduced. Exercise ceilings are explicitly synthetic.
Normal completion verifies closure/standby; errors and interrupts stop subsequent
commands and require an operator's physical abort procedure on eventual hardware.
Source: active user task and PROJECT.md tutorial extension. Scope remains hardware-free.

## E027

Date: 2026-09-10; incremental tutorial verification, TEST-011/012 / REQ-011/012.
Method: `python -m pytest tests/test_tutorials.py -q -p no:cacheprovider` with a
workspace temporary directory; Python 3.12.14, nbclient 0.11.0, nbformat 5.11.1,
ipykernel 7.3.0. Executed all four notebooks in separate fresh Python kernels,
injecting serial-open/discovery guards before tutorial imports. Source notebooks
contain clear expected results; actual executed outputs are retained separately.
Result: 36 tests PASS. Nominal functions passed for V2/V5/V6; script entry points
ran twice with identical output and released every simulator. Verified exact
control command order, local write/input rejection, readiness/fault guards,
readback/parsing failures, interrupt handling, lost acknowledgments at every
control write, active/history evidence, unknown faults and no command replay.
Reviewed actual notebook output against the written expected results: all match.
Ruff lint/format, strict library typing and dependency consistency PASS.
Environment note: Windows sandbox denied access to pytest-created temporary
directories; the same guarded tests passed with normal local permissions. Notebook
tooling installation needed normal package-registry access. One non-failing pyzmq
warning reports its supported selector-thread fallback for Windows' Proactor loop.
No device was enumerated or connected. Physical validation remains UNTESTED.
Integrated acceptance and final candidate fingerprint follow in E028.

## E028

Date: 2026-09-10T23:12:02.508556+00:00.
Kind / scope: Integrated tutorial candidate acceptance; TEST-001..009/011/012.
Candidate: `577575f55400df6c51985cd7b88f2bb96dd6ac6c388cd58c6dc1dfd57a5494e5`.
Method: `python scripts/validate.py` in the documented development environment,
workspace temporary fixtures, normal local permissions and package-registry access.
Result: 181 tests PASS (15.50 s), 95% library statement coverage. Includes 36 new
tutorial cases and actual execution of all four notebooks in hardware-guarded
fresh kernels. One non-failing pyzmq Windows selector-thread warning, no skips.
Ruff lint/format PASS (46 files including notebooks), strict mypy PASS (12 runtime
modules), dependency consistency PASS, wheel/sdist builds and inclusion of all
tutorial scripts/notebooks/guide PASS. Isolated core-wheel installation ran all
four tutorial scripts plus original examples and CLI without serial/Jupyter/Dash
dependencies. Installed GUI/serial extras then passed HTTP callback/assets/cache/
fault/error/recovery checks (Dash 4.4.1, Plotly 7.0.0, pySerial 3.5). Node 24.19.0
watchdog regression PASS. All 11 validator stages passed; all 55 candidate source
hashes stayed unchanged. Manual and pinned framework input hashes match.
Artifacts: [manifest/environment/build hashes](validation.json),
[development dependencies](requirements-validated.txt), local validation.log/JUnit
and four executed notebook copies in `records/tutorial-notebooks/` (CI artifacts).
Review: Expected notebook outputs match observations; normal completion and unknown
outcomes are distinguished. Application functions use only the existing public
controller API; simulator-only setup/injection is isolated in entry points. Core
runtime is unchanged, so prior browser evidence E024 remains applicable.
Bearing: REQ-011/012 PASS; REQ-001..009 current software/simulator PASS. Supersedes
E025/E026 for the expanded candidate. Physical REQ-010 remains UNTESTED. Tutorial
request complete; hardware gate retained without requesting physical access.
All sessions/kernels finished. No serial device was enumerated or opened; no
commit/push or upstream change was requested or performed.

## D008

Date: 2026-09-10; user clarification: examples must implement real-hardware use
for human operators, not merely describe future adaptation.
Decision: Add one shared `run_tutorial.py` operator runner and a disabled-by-default
hardware section in every notebook. Reuse the four application functions. Validate
explicit native port/model/baud and required write target/ceiling before opening;
ask CONNECT, query ?SV first, and ask RUN before the lesson. Identification-only
mode sends one query. Hardware fault diagnosis stays read-only and never invokes
fixture setup, fault removal or timeout injection. Hardware power setting leaves
the approved target stored; synthetic rejection and return-to-zero exercises remain
in simulator mode. Physical access by the agent remains unauthorized; preparation
of executable operator paths does not pass the project's hardware review gate.

## E029

Date: 2026-09-10; TEST-013 and affected TEST-011/012, hardware-path software checks.
Method: Run the tutorial suite with the serial factory replaced by the actual
Verdi simulator and scripted human answers. Execute each notebook in default mode
and again with the hardware section enabled against that substituted factory.
Result: 71 tests PASS, including all four hardware lesson routes, explicit serial
settings, invalid/missing configuration before opening, cancellation before connect
and after ?SV, identification-only exchange, fixture-operation prohibition,
connection/timeout failures without fallback/reconnect, and CLI routing. Eight
fresh notebook executions passed; recorded outputs match the real-mode sequence
descriptions. Kernel artifacts restore disabled hardware settings and explicitly
record simulator substitution in metadata. No real device was accessed.
Diagnosis: The first expanded suite run had 67 PASS and four notebook harness
failures because IPykernel resets builtins.input between cells. Patch the runner's
module lookup for scripted test input instead; ordinary terminal/Jupyter input in
the implementation is unchanged. The rerun passed all 71 checks. One non-failing
Windows pyzmq selector-thread warning remains. Lint/format and library typing PASS.
Final integrated candidate validation follows E030. No physical PASS is inferred.

## E030

Date: 2026-09-10T23:34:10.147333+00:00.
Kind / scope: Integrated human-operated tutorial software candidate; TEST-001..009/011..013.
Candidate: `cb278b99ebeeb7eb8d186f939127045a33b7f2ce41fd16e1c35c72b7cb020f11`.
Method: `python scripts/validate.py`, normal Windows temporary-file permissions,
workspace fixtures and explicit Node runtime. All device interaction uses simulation
or fake streams; the new operator paths use simulator serial-factory substitution.
Result: 216 tests PASS (19.79 s), 95% library statement coverage; 71 tutorial/operator
tests include eight fresh notebook executions. One non-failing Windows pyzmq
selector-thread warning, no failed/skipped tests. Ruff lint/format PASS (47 files),
strict runtime typing PASS, dependency consistency PASS. Wheel/sdist builds and
archive completeness PASS; the core-only isolated install ran the four original
tutorial scripts and the new runner's simulator default. Installed GUI/serial extras,
CLI/original examples and Node watchdog PASS. All 11 validation stages passed.
All 56 source hashes stayed unchanged; supplied manual and framework hashes match.
Artifacts: [manifest/environment/build hashes](validation.json), local validation.log,
JUnit, and default/operator-path executed notebooks under `records/tutorial-notebooks/`.
Operator-path notebook artifacts identify simulation and restore disabled settings.
Review: Hardware configuration/connection and calls to the existing application
functions are implemented; no reader-written adapter code is necessary. Actual
physical identity, framing, operating limits, behavior and calibration remain
UNTESTED. Candidate/site approval is still required before a human uses the path.
Bearing: REQ-013 software PASS and affected tutorial/package/docs requirements
revalidated; supersedes E028 for the current candidate. No library runtime changes,
physical discovery/open/actuation, upstream modification or commit/push occurred.
All simulator sessions and test kernels completed; no pending operation remains.

## E031

Date: 2026-09-10; user-authorized review, pruning, commit and push, followed by
the clarification that notebooks must show all demonstration functions explicitly,
use clear sections and avoid crowding. Scope remains entirely hardware-free.
Review findings/changes:

- Fix CLI handling of --timeout-s without --hardware: reject it consistently with
  other serial settings instead of silently ignoring it. Add missing/incomplete
  CLI-mode regressions and retain numeric/range/rounded-ceiling rejection.
- Remove redundant finite-number checking after a bounded comparison against the
  validated finite ceiling; NaN/infinity remain rejected before connection. Merge
  duplicate operator-path test executions while retaining connection, command,
  fixture-prohibition and cleanup assertions. Trim duplicate lesson prose in the guide.
- Keep the terminal runner, but remove every tutorial-script import/dispatch from
  notebooks. Define hardware_power_config and hardware_connection visibly in each
  notebook; hardware cells call the notebook's own application functions directly.
  Split the controlled session into readiness, enable, sample, normal-stop and
  orchestration functions. Split the two fault exercises into distinct visible
  functions. Maintain clear numbered sections and one function per code cell.
- Strengthen notebook validation: execute from otherwise empty working directories,
  allow only controller-library/standard-library imports, compare application/helper
  definitions with paired scripts and limit cells to 30 lines. Actual maximum is
  22 lines in all four notebooks. No code cell loads an adjacent tutorial file.
- Normalize the dependency snapshot and generated validation JSON to repository LF
  line endings, so staging cannot silently alter the validated source fingerprint.

Evidence: The initial pruning candidate passed integrated validation (216 tests),
then was superseded by the user's notebook clarification. The self-contained
revision passes all 71 tutorial/operator tests, including eight kernel runs with
hardware branches using simulator substitutes. Lint/format/typing remain passing.
No runtime library API change, physical discovery/connection/actuation or upstream
template edit. Final combined validation follows E032. Fetched origin and confirmed
origin/main matches local main at aced244 before publication; no divergence.

## E032

Date: 2026-09-10T23:51:22.454712+00:00.
Kind / scope: Final self-contained notebook/publication candidate; TEST-001..009/011..014.
Candidate: `1e83941dbd88416affb180a51c1d1547679cc9bbdccf9dc20cd504b65977766e`.
Method: `python scripts/validate.py` with hardware-free guards, simulator serial
substitution, workspace temporary fixtures and normal local Windows permissions.
Result: 216 tests PASS (17.86 s), including 71 tutorial/operator cases and eight
fresh notebook executions from otherwise empty working directories. No notebook
loads a tutorial script; all application/connection/configuration functions are
visible, match their paired definitions, and occupy at most 22 lines per cell.
Ruff lint/format PASS (47 files), strict library typing PASS, 95% library coverage,
dependencies/builds/source-archive completeness PASS. Isolated core installation
ran all four tutorial scripts and the terminal runner's simulator default; installed
GUI/serial extras, CLI/original examples and Node watchdog PASS. All 11 stages passed;
all 56 source hashes remained unchanged. Manual/framework preserved-input hashes match.
One non-failing Windows pyzmq selector-thread warning; no skips or failures.
Artifacts: [manifest/build/environment hashes](validation.json), local validation.log,
JUnit and eight executed notebooks. Hardware-path artifacts retain disabled source
settings and identify simulator substitution. Notebook layout and expected outputs
were reviewed; no remaining actionable software finding under the current request.
Bearing: REQ-014 software PASS; affected REQ-001..009/011..013 revalidated. Supersedes
E030 and the intermediate pruning candidate. Physical REQ-010 remains UNTESTED.
The user authorized commit/push; publication does not approve real hardware access.
All test sessions/kernels completed. No physical enumeration/open/actuation occurred.

## D009

Date: 2026-09-10; source: user's aggressive codebase simplification request.
Decision: consolidate the four terminal examples into run_tutorial.py with direct
function dispatch. Remove the four duplicate script files and runtime runpy/path
loading. Keep standalone notebook definitions because the user explicitly requires
visible, self-contained tutorials. Keep the public library modules/API and the
independent protocol/transport/simulator/telemetry boundaries: they implement
required parsing, serialization, failure isolation and hardware-free testing.
Do not add compatibility wrappers for the removed example filenames; document
their existing run_tutorial.py command equivalents instead. Library import paths,
signatures, notebook filenames and terminal runner arguments remain stable.

## E033

Date: 2026-09-10; TEST-015 simplification review and affected regression preparation.
Changes: terminal tutorial files reduced from five to one; dynamic execution and
duplicate imports/entry guards removed. Notebook simulator entry points receive
descriptive names and are called directly. One AST comparison checks every visible
notebook function against its terminal equivalent; fresh-kernel execution retains
independence checks and all simulator/operator cases. CLI writes share the status
readback path; successful set-power and standby assertions extend the existing
test. Simulator current aliases share one value, and injected query replies no
longer compute and discard a side-effect-free query result. No safety check removed.

Dependencies: remove explicit wheel requirements from build/dev and the redundant
nbclient declaration from the interactive tutorials extra; keep nbclient/ipykernel
in dev for notebook tests. Core still has no runtime dependencies. All remaining
modules/declarations have concrete uses; no placeholder or unused runtime module
was found. Documentation gives the replacement terminal commands.

Observed: 176 affected tests PASS, including eight fresh notebook runs and the
human-operated branches with simulator substitution; Ruff and strict typing PASS.
Isolated wheel build PASS with only setuptools 84.0.0 installed as the backend
dependency (`python -m build --wheel --outdir tmp/simplification-isolated-build`).
All 216 existing collected test cases remain; no test file was removed.
Python source count across library/examples/scripts/tests: 29 -> 25 files,
4,221 -> 4,159 lines (blank/comment lines included). Final integrated validation
follows in E034. Physical hardware remains UNTESTED and untouched.

## E034

Date: 2026-09-11T00:05:33.655180+00:00; TEST-001..009/011..015 final simplification candidate.
Candidate: `29b070ac92fa9b7bca04287c1ef96afec593e2e873b704684d55f80d4d8906e0`.
Method: `python scripts/validate.py`, normal local Windows permissions, workspace
temporary fixtures; physical serial/discovery prohibited, operator branches simulated.
Result: 216 tests PASS (14.35 s), 95% library statement coverage; 71 tutorial/operator
cases and eight fresh notebook runs. Ruff lint/format PASS (43 files), strict typing
PASS (12 modules), dependency checks, wheel/sdist completeness, CLI/examples, clean
core/extras installs and Node watchdog PASS. All 11 stages passed; 52 candidate hashes
unchanged during validation and preserved input hashes match. One non-failing Windows
pyzmq selector-thread warning; no skips or failed tests.
Review: public class/function/method signature inventory unchanged, all notebook
functions match terminal equivalents, max code-cell length 22 lines, source diff
clean. No runtime dynamic loading remains. All four terminal lessons and the default
passed against the installed core wheel; Dash 4.4.1/Plotly 7.0.0/pySerial 3.5 extras
callbacks passed. The previous browser evidence E024 applies to unchanged GUI assets.
Artifacts: validation.json; local validation.log/JUnit and eight executed notebooks.
Bearing: affected requirements revalidated; REQ-015 PASS. E032 remains historical
evidence for the previous candidate. REQ-010 physical validation remains UNTESTED.
Origin/main fetched and matched HEAD at 0033ecc before commit. The user's earlier
commit/push authorization remains applicable; Git history records publication.
All test sessions/kernels completed. No device access or upstream template change.

## D010

Source: user's request to verify every implemented protocol/safety behavior against
the official manual. Authority remains software/simulator only. Preserve the five
implemented write families (six API operations), all 42 queries and the service
command exclusion. Do not infer ?F clear semantics from the documented ?FH clear
reply: physical controllers now require a caller-supplied, independently verified
active_fault_clear_reply. The simulator convention remains source-specific.
Keep ambiguous fault-code 1 labels visible and V5/UNO servo distinctions unresolved;
reject only model/code combinations explicitly excluded for known V2/V6 models.

## E035

Scope: TEST-016 manual audit, begun at ef9c472; supplied Coherent operator manual
0171-750-00 Rev IB, 08/2005, SHA-256 unchanged. Read/extracted complete section 5,
safety pp.1-1..1-3, ratings p.2-5, operation pp.4-1..4-5/4-9/4-13, fault tables
pp.6-1..6-3 and Charts 5/13; checked shutter/thermal operating principles.
Visually inspected Tables 5-1..5-4, serial pin figure, Table 4-3, fault handling and
Table 6-1 to verify columns, spellings, footnotes and conflicting fault labels.

Findings and fixes:
- Add fault 30 from Table 6-1/Chart 13. Code 1 now flags the Table 5-4 head-interlock
  versus Table 6-1/Chart 5 emission-lamp conflict; retain code 47 from Table 5-4.
- Require verified clear-fault text on physical connections; do not silently accept
  the simulator's SYSTEM OK convention. Fault codes/lists cannot be clear settings.
- Enforce diode/LBO servo code restrictions (V2 excludes 6; V6 excludes 5); keep
  V5/UNO ambiguity visible. Controlled tutorials check all four temperature servos.
- Simulator accepts long query aliases, PRINT, colon delimiters, semicolon
  termination and short prompt >, while preserving one instruction per transaction.
  Remove trailing acknowledgment spaces; reject Python-only numeric syntax and
  non-boolean mode settings. Closed-shutter ON has a positive synthetic idle diode
  current; faults/standby have zero. Current magnitudes and ?P idle remain fixtures.
- Correct shutter citation to Table 4-3, p.4-9; clarify physical-key versus fixture
  semantics and complete-shutdown/warmup prerequisites. Keep undocumented ranges,
  response latency, no-fault text, fault recovery and optical calibration unverified.

Validation: independent vectors cover all 42 rows/units/types/enum codes/aliases,
all 12 error-prefix/echo/prompt combinations, command alternatives, all 22 known
fault codes, explicit-clear profiles, servo restrictions and tutorial readiness.
Initial notebook checks exposed omitted forwarding of the new configuration in
four hardware cells; fixed and rerun with non-simulated source metadata on in-memory
peers so the check cannot use the simulator fallback. A reserved pytest parameter
name was corrected during test collection. Full pytest then PASS: 320 cases
(16.62 s), including all eight notebook executions, 75 tutorial/operator cases.
No test was removed. Ruff and strict typing PASS. Final integrated run follows E036.
Every physical serial constructor/discovery path remained prohibited; no hardware
was accessed. No dependency or public operational command was added.

## E036

Date: 2026-09-11T00:28:16.330843+00:00; TEST-001..009/011..016 final manual-audit candidate.
Candidate: `7cee08deb695a9136e4b07749dd7003c2ff5dff6b9f63fd3641503096d34693f`.
Method: python scripts/validate.py, Windows 11/Python 3.12.14, Node 24.19.0,
workspace temporary fixtures with normal local Windows permissions. All physical
serial constructors/discovery prohibited, including notebook kernels. Hardware
branches exercise in-memory peers with non-simulated source metadata and explicitly
verified fixture clear text, so they cannot use the simulator-only clear fallback.

Result: 320 tests PASS (20.82 s), 96% library statement coverage; 75 tutorial/operator
cases and eight fresh notebook runs. All 11 stages PASS: Ruff lint/format, strict
typing (12 modules), dependency checks, wheel/sdist builds, CLI, synchronous/async
examples, clean core/extras installs and Node watchdog. All 52 candidate hashes
unchanged during validation; preserved manual/framework hashes match. One non-failing
Windows pyzmq selector-thread warning; no skipped/failed tests. No test was removed.

Review: manual source matrix and independent vectors cover all implemented commands
and queries, state codes, fault catalogs, framing, errors, limits and safety rules.
Only one optional configuration field was added; operational APIs and transport
separation retained. No dependency/module or service write added. Notebook helpers
remain visible and match terminal functions; maximum code cell is 23 lines.
Short report and checkpoint updated after validation; these are outside the source
fingerprint. Previous browser evidence E024 applies to unchanged GUI assets.
Artifacts: records/validation.json, local validation.log/JUnit and eight executed
notebooks. All test sessions/kernels completed; no hardware accessed.

Bearing: REQ-016 and affected software requirements PASS for this candidate.
E034 is historical evidence for the prior revision. REQ-010 remains UNTESTED;
future physical work is AWAITING_HUMAN_REVIEW, not a validated release.
Publication review: git diff --check PASS; all 52 working source hashes still match
the validated manifest. Origin/main fetched and matched HEAD at ef9c472 before
commit. Only reviewed audit changes are staged under the user's prior commit/push
authorization; Git history records the final publication revision.

## E037

Date: 2026-09-11 00:38:52 UTC. User requested review, prune, commit and push.
Reviewed 82b6db1 and its manual-audit diff: fault-clear configuration and session
failure behavior, model-specific servo restrictions, simulator syntax/transitions,
tutorial/operator paths, packaging/dependencies, tests and documentation.
No additional actionable code defect, unused module or unused dependency found.
Independent simulator/manual vectors and visible notebook functions are purposeful;
retained them, all required features, tests and hardware/simulator separation.
Pruned repeated checkpoint prose and linked the existing detailed reports.

TEST-002..009/011..016: pytest -q -p no:cacheprovider
--basetemp=tmp/publication-review --cov=coherent_verdi --cov-report=term-missing
--junitxml=tmp/publication-review-junit.xml. Result: 320 PASS in 20.96 s,
96% library statement coverage; all 75 tutorial/operator cases and eight notebook
executions. One non-failing Windows pyzmq warning, no failed/skipped tests.
Ruff lint PASS; formatting PASS (43 files); strict mypy PASS (12 modules);
pip check PASS. Tests/kernels prohibited physical serial opening/discovery.

All 52 source hashes still match E036's candidate
7cee08deb695a9136e4b07749dd7003c2ff5dff6b9f63fd3641503096d34693f.
Only STATE.md, outputs/REPORT.md and this record changed; E036's integrated build,
clean-install and watchdog results remain applicable and were not rerun.
Origin/main fetched and matched HEAD at 82b6db1. Publication is authorized by the
current request. No hardware accessed; physical validation remains UNTESTED and
future integration requires the unchanged review gate. All test kernels completed.

## D011

Date: 2026-09-11T03:12:47.397880+00:00. Source: active user compact-driver redesign request, added to PROJECT.md.
The repository at cfb3f4a had 12 package modules, 1610 Python lines, 25 classes and
24 root exports. Reduce this to eight modules and direct device operations; no
external compatibility obligation was identified. Config objects become constructor
keywords; models move alongside their protocol/results; serial I/O moves into
protocol.py; optional monitoring/JSON share monitor.py; CLI lives in __main__.py.
Remove transport replacement, duplicate serial locks/session state, telemetry
worker/lifecycle/log-handler machinery, QuerySpec metadata registry, three exception
subclasses and legacy exports/modules. No compatibility aliases are retained.

The backend's three methods and source flag remain as a structural typing contract
for connection injection. Actual hardware state enums, status/diagnostic results,
fault records and four actionable exception classes remain. The controller alone
serializes serial transactions and latches uncertain outcomes. A simulator timeout
now also latches controller failure; direct fixture inspection does not authorize
continued application I/O. No replay, flush, negotiation or recovery command exists.
The simulator implements the exact emitted short-form subset, not extra firmware
aliases/terminators. All 42 public queries and six public operations are retained;
manual aliases remain reference data. This deliberately narrows simulator scope
under the latest cleanup request, superseding that part of E035.

GUI callbacks continue to consume the public monitoring cache; Monitor calls the
same status() used by scripts. Core and Monitor create no threads. The standalone
GUI launcher explicitly starts and drains its worker before disconnect. Logging
uses returned samples/JSON and the application's own sinks. Current REQ-003/005/015
criteria are explicit lifecycle and useful device behavior, superseding derived
tests that enforced the deleted ownership/lifecycle internals.

ARCHITECTURE.md now describes the driver as explicitly requested; original template
hash/provenance remains in records/FRAMEWORK.md and Git. AGENTS.md and the manual
remain byte-identical. Their preservation checks remain active. No hardware access,
discovery, physical validation, publication or new external authority is implied.

## E038

Date: 2026-09-11T03:12:47.397880+00:00. TEST-001..009/011..017: compact-driver candidate review and regression.
Candidate: `8d955e2566827304f4a77689bde146313554eae06670a3e2e0cef3fd4d863aec`. Base: cfb3f4a.
Final method: `.venv/Scripts/python.exe scripts/validate.py`, Windows/Python 3.12.14,
Node v24.14.1. All physical serial constructors/discovery prohibited by tests and
notebook-kernel guards. Fake pySerial handles exercise passive open/close, framing,
timeouts, byte limits, partial writes, interruption, cleanup retry and concurrency.

Result: 310 tests PASS in 16.94 s, 97% statement coverage (701 statements, 19 missed).
All eight notebook runs PASS, including disabled-default and operator paths with
in-memory serial substitutes and explicit fixture clear text. All 11 stages PASS:
pytest/coverage, lint, formatting, strict mypy (8 modules), dependencies, wheel/sdist,
CLI, synchronous/async examples, isolated core/extras installation and browser
watchdog. Installed wheel inventory matches exactly the current eight modules;
the dependency-free install runs the CLI, examples and four terminal lessons.
GUI callbacks show NO DATA/LIVE/FAULT/ERROR with bounded history and no acquisition.
The launcher test proves acquisition finishes before disconnect on Ctrl+C.
No tests were skipped. One non-failing Windows pyzmq selector-thread warning remains.

TEST-017 review: package modules 12 -> 8 (-33%); Python lines including comments and
blanks 1610 -> 1333 (-17%); classes 25 -> 17 (-32%); root exports 24 -> 12 (-50%);
exception classes 7 -> 4. Core dependencies remain zero; serial, GUI and notebook
extras remain independent. README, API/migration, integration, simulator, architecture,
physical procedure, all examples and notebook source were updated. Tests for deleted
registries/factories/lifecycle internals were replaced by device-facing behavior.

Intermediate diagnostics: initial tests exposed stale expectations for implicit fake
recovery/error formatting and fake physical paths missing verified clear text; fixed
without relaxing parser behavior. Restricted Windows temporary-directory ACLs prevented
notebook fixtures; reran guarded tests with normal local permissions. An integrated
run failed only format checks; corrected formatting and reran all 11 stages. Stale
generated build output was removed within the verified repository build path before
building; the wheel inventory check now detects obsolete modules.

Artifacts: records/validation.json (versions, hashes and commands), generated
records/validation.log, records/junit.xml and records/tutorial-notebooks/. Source
hashes were unchanged during final validation; preserved manual/AGENTS hashes match.
The report/checkpoint below are maintained outside the source fingerprint. Previous
GUI screenshots are historical evidence, not validation of the revised layout;
current GUI verification covers HTTP/callback/assets and virtual-clock watchdog.
All validation processes and notebook kernels completed. REQ-010 remains UNTESTED;
this is software-complete pending candidate review and physical integration.

## E039

Date: 2026-09-11T03:19:24.564854+00:00. Source: user request "holistic review update
commit push". Reviewed the complete compact-driver change, protocol/serial failure
paths, simulator, optional monitor/GUI/CLI, tutorial/operator routes, tests,
packaging and documentation. Commit and push to configured origin/main are now
explicitly authorized. Origin/main was fetched and matched the base cfb3f4a.

The review reproduced `read_faults(history="False")` emitting `?FH` because of
truthiness. Require a boolean selector; five regression cases now reject invalid
values before any I/O and prove the session remains usable for `?F`. The source
archive omitted tests/conftest.py (physical-access guards and shared fixtures) and
the operating documents/manual. MANIFEST.in now includes them and install_smoke.py
checks their presence. Version 0.2.0 marks the breaking API; package checks select
the configured version rather than obsolete local build artifacts. Refreshed the
editable installation with pip --no-deps --no-build-isolation and verified the
installed simulator-only CLI. No additional actionable review findings remain.

TEST-001..009/011..017: `.venv/Scripts/python.exe scripts/validate.py` on Windows,
Python 3.12.14, Node v24.14.1. Candidate source SHA-256:
`be0ad6235eb92e38800fe23e6c24f784719d4b5359d43f6b2ac2015a736fa027`.
All 11 stages PASS: 315 tests in 16.98 s, 97% statement coverage (703 statements,
19 missed), lint, formatting (39 files), strict mypy (8 modules), pip check,
wheel/sdist builds, CLI, sync/async examples, isolated core/extras installs and
watchdog. Eight notebook executions passed with physical serial/discovery guards.
One non-failing Windows pyzmq warning; no failed/skipped tests. Package metrics are
8 modules, 1335 Python lines, 17 classes, 12 root exports and 4 exception classes;
zero required runtime dependencies. E038's design description remains applicable.

Source hashes remained unchanged throughout validation; preserved manual/AGENTS
hashes match. STATE.md, this record and outputs/REPORT.md are maintained outside
the source fingerprint and updated to this result before publication. Final package
hashes and any packaging-only refresh commands/results are in records/validation.json;
full generated output is in records/validation.log. No physical device was opened
or discovered. REQ-010 and calibration remain UNTESTED; future hardware integration
still requires candidate approval. All validation processes and kernels completed.

## E040

Date: 2026-09-11. Publication checkpoint following E039. Commit 20cab5f contains
the reviewed 0.2.0 simplification and validation manifest. Final packaging refresh
passed; archive checkpoint/guard bytes match the reviewed files and all source
hashes still match E039. The source manifest records updated build hashes and
both successful packaging-only commands. Git's staged diff check passed.

`git push origin main` was rejected before execution by automatic approval review:
publishing private repository contents to the configured destination requires
trusted user content explicitly naming/authorizing that destination. No workaround
was attempted. Read-only checks confirmed a clean tree after 20cab5f, one local
commit ahead of the previously fetched origin/main, and the push destination
`git@github.com:cct1123/coherent-verdi-control.git`. Await the user's explicit
approval of this remote and main branch, then push and verify synchronization.

This record and STATE.md change only publication metadata outside the source
fingerprint. E039 software/build validation remains applicable; the built archive
contains the pre-publication review checkpoint. No hardware access occurred.

## D012

Date: 2026-09-11. Source: renewed user requests for further aggressive pruning,
reduced data structures/modules, clean migration, holistic review, commit and push.
The user repeated publication after the explicit destination question for
github.com/cct1123/coherent-verdi-control, main. No physical access is authorized.

Version 0.3.0 merges protocol/serial/errors into controller.py and the optional
monitor cache into gui.py. SimulatedVerdi inherits the public operations and
failure handling, overriding only private open/close/exchange with independent
fixture responses. Remove Connection/SerialConnection, Model/Query/state enums,
Status/Diagnostics/Fault/Sample records and the JSON adapter. Results are ordinary
dictionaries, ISO UTC strings, numbers and integer fault lists. Two errors remain:
DeviceError for complete device rejection and VerdiError for unusable/uncertain
communication. Core parsing no longer trusts the display-source flag to recognize
an unverified clear-fault reply; simulator initialization supplies its own fixture
clear text. Serial configuration is private and set through constructor validation.

Remove CLI write switches/demo setup/result envelopes and the monitor sequence
counter; retain direct read/status/diagnostics/watch/GUI commands. Control workflows
remain in the Python API and visible tutorials. Monitoring stays optional, with
one application polling caller, a bounded copied cache and no lifecycle workers.
Delete redundant docs/INTEGRATION.md and tests/test_monitor.py after merging useful
content into README/API and client tests. Preserve historical screenshot/manual
evidence, all four self-contained notebooks, hardware gates and actual protocol
vectors. No deprecated imports or runtime compatibility aliases remain.

Review retained all 42 queries, six command forms, model-specific code checks,
range/rounded-ceiling checks, bounded serial deadlines, deterministic cleanup and
failure latching without replay. New tests cover invalid public queries before I/O,
JSON/result mutation isolation, source-label independence and complete device
rejection in the write example. The latter must propagate DeviceError, rather than
mislabel a complete rejection as a lost reply. Monitor snapshots are independent
copies. Tests of removed metadata/CLI operations were pruned without dropping the
manual wire vectors, simulator behavior, serial faults, concurrency or operator paths.

Metrics versus 0.2.0: 8 -> 5 modules; 1335 -> 1057 Python lines including comments
and blanks; 703 -> 521 executable statements; 17 -> 5 classes; 12 -> 4 root exports;
4 -> 2 errors. No custom result/configuration types or required runtime dependencies.
Compared with the original 12-module design, 7 modules and 553 Python lines are gone.

## E041

Date: 2026-09-11T03:55:58.287795+00:00. TEST-001..009/011..017: final 0.3.0 software review
and regression following D012, base 7878823. Source candidate:
`b96549fbe358b16cd644e4336e001378efc8f393e3ce591b14fc0cc0bfb54f75`. Command: `.venv/Scripts/python.exe scripts/validate.py`.
Windows/Python 3.12.14, Node v24.14.1. Result: 322 PASS in 19.25 s, 97% statement
coverage (521 statements, 17 missed), no skipped tests, one non-failing Windows
pyzmq warning. All 11 integrated stages PASS, including eight fresh notebook-kernel
executions, lint, formatting (34 files), strict typing (5 modules), pip check,
wheel/sdist builds, CLI, sync/async examples, isolated core/extras installs and
watchdog. Tests/kernels prohibited physical serial opening and discovery.

The final holistic audit confirmed all active documentation links resolve, all
visible notebook functions match the terminal runner, outputs are cleared in source
notebooks, and the source archive has no removed runtime modules. The installed
wheel contains exactly five modules; core-only imports start no workers or optional
dependencies. New regression checks preserve plain-result/cache isolation, public
input rejection before I/O, verified fault parsing independent of source labels,
and DeviceError propagation from the write tutorial. No further useful runtime
abstraction or scaffolding was identified for removal. Historical evidence files,
manual vectors and explicit notebook source remain purposeful.

Intermediate migration failures exposed stale attribute/tuple/enum expectations
and a missing operator model check; all corrected before the final run. Review then
fixed a complete device rejection being labelled UNKNOWN by the migrated example,
and removed the final stale fault-metadata documentation reference. The full suite
was rerun on the resulting fingerprint. Windows generated-artifact ACLs required
normal local permissions for guarded notebooks and archive reads. No hardware
authority was expanded. The editable installation was refreshed to 0.3.0.

Source hashes stayed unchanged during final validation; manual/AGENTS preservation
hashes match. STATE.md, this record and outputs/REPORT.md are updated outside the
source fingerprint. Final package hashes and packaging-only refresh results live
in records/validation.json, with output appended to records/validation.log. Origin
was fetched successfully; main was two local commits ahead with no remote divergence
before this change. The user's renewed publication request follows the explicit
destination question; push targets origin/main without force. No test kernel or
device operation remains pending. REQ-010 and calibration remain UNTESTED.

Final documentation amendment to E041: source `56bbd1fce0bfa82fd92e747684961a913c9264d10a7b965de96f5aa5bbffe5c4` removes one stale
`known=False` phrase from a markdown cell in 04_handle_faults.ipynb. Compared with
the full-suite candidate above, every code cell and every other fingerprinted
file is byte-identical. No runtime/test behavior changed; the full-suite evidence
remains applicable. records/validation.json explicitly preserves both fingerprints
and this check. Rebuild/installation checks cover the amended package artifacts.

## E042

Date: 2026-09-11. Final packaging refresh for E041 passed: wheel/sdist rebuilt,
isolated core/extras installations passed, archive checkpoint/guard bytes matched,
and the source fingerprint remained unchanged. Manifest records the final hashes
and commands. Git staged-diff checking passed; commit 99072c6 contains the reviewed
0.3.0 implementation, clean migration and evidence.

The requested `git push origin main` was rejected before execution by automatic
approval review. Its reason: the trusted user text authorizes pushing generically
but does not explicitly specify the GitHub destination or payload. No workaround
or alternate push was attempted. The configured destination remains
git@github.com:cct1123/coherent-verdi-control.git; origin/main was fetched without
divergence. Request explicit authorization to publish all local main commits since
origin/main, including this reviewed code and its checkpoint/evidence, to that
repository's main branch. Then push and verify remote equality and a clean tree.

This publication checkpoint changes only STATE.md, outputs/REPORT.md and this
record outside the source fingerprint. E041's software/package evidence remains
applicable; built archives contain the reviewed pre-publication checkpoint.
No physical device operation occurred or remains pending.

## E043

Date: 2026-09-14. The user replied "push" directly to the request identifying all
four local main commits and github.com/cct1123/coherent-verdi-control, branch main.
Automatic approval review accepted the authorized `git push origin main`; it
completed successfully, advancing main from cfb3f4a to c5da4d5. A subsequent
`git ls-remote origin refs/heads/main` returned
`c5da4d5ca8f59f0f0a79544a8efd087038bf5eed`, matching local HEAD. The working tree
was clean. E042's publication blocker is resolved.

This follow-up changes only publication status in STATE.md, outputs/REPORT.md
and this evidence record. Runtime, tests, package sources and E041's validation
are unchanged. Hardware approval remains outstanding; no device was accessed.

## E044

Date: 2026-09-15. REQ-018 / TEST-018: new-user README update based on b4bc562.
README now leads with the user workflow, environment setup, simulator output,
GUI launch/stop instructions and a guide to the displayed fields. Two independent
Python examples demonstrate reads and a setpoint change while remaining in
simulated standby. A Mermaid block diagram shows scripts and optional monitoring
using the same public API. Detailed migration/implementation material is linked.

Ran `.venv/Scripts/python.exe -m coherent_verdi status`: expected V5 simulated
standby, closed shutter, zero power and no faults. Executed both README Python
fences with physical `_open` prohibited; stdout matched the documented values.
Checked all 24 local links and heading anchors: PASS. Launched
`.venv/Scripts/python.exe -m coherent_verdi gui`, inspected the rendered browser
view and captured docs/images/gui-simulator-quickstart.jpg (74775 bytes). It shows
LIVE/SIMULATOR, 0 W, STANDBY/CLOSED, thermal and instrument fields, matching the
default workflow. The screenshot is unaltered; the browser returned JPEG bytes.
Preserved older screenshots because historical evidence references them.

Added JPEG inclusion to MANIFEST.in. Built with
`.venv/Scripts/python.exe -m build --sdist --no-isolation --outdir tmp/readme-dist`;
archive README (normalized line endings), screenshot and manifest match source.
Windows sandbox temporary-file/archive ACLs blocked the initial checks; the
build and archive read passed with normal local permissions. No dependency or
runtime change was needed. `git diff --check` passed. Closed the preview tab and
stopped its CLI session with Ctrl+C; a loopback socket check confirms port 8050
is no longer served by that preview. No hardware was discovered or accessed.

Current source fingerprint:
`4a67cd283aea6d506e040c6ff5249d04c35f85da829ad38a3fa3f7c2bb04d3fd`.
Compared with records/validation.json, only README.md, PROJECT.md, MANIFEST.in
and the new screenshot differ. Every runtime/test/example source matches E041;
the full suite was not rerun and its existing manifest was not overwritten.
The new source archive is a documentation packaging check, not a new physical
or full-suite validation. STATE/report/evidence changes remain outside the source
fingerprint. No publication was requested for this follow-up.

README SHA-256: `397fc7462f9e75d9ebc0823b7b7afe2723c6ca8227dccf317b00c1eb99c070dc`.
Screenshot SHA-256: `866bac21435cf88804402348035cb53580fa9bbf7da7d86e8f2bee9d89d19564`.

Publication follow-up: the user requested "commit push" for this reviewed README
update and screenshot. Refetched origin and confirmed main has no divergence;
the candidate fingerprint still exactly matches E044. `git diff --check` passes.
Publish the seven reviewed documentation/image/package-manifest files to the
established github.com/cct1123/coherent-verdi-control main branch without force.
This authorization does not include physical hardware access.
