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
