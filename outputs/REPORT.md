# Engineering report — simplified Verdi controller

The simplification is complete and reviewed. **Software/simulator validation PASS;
physical hardware and calibration remain UNTESTED.** The public controller API,
safety checks, hardware/simulator separation and all 216 test cases are retained.

## Changes and compatibility

- Consolidated five terminal tutorial files into one
  [run_tutorial.py](../examples/tutorials/run_tutorial.py), using direct function
  dispatch. Removed runtime script loading and duplicate imports/entry guards.
- Kept all four notebooks self-contained, with named simulator functions, direct
  execution cells and visible hardware helpers. Maximum code-cell length: 22 lines.
- Combined CLI write-result handling; simplified simulator current aliases and
  removed discarded query computation during reply injection.
- Removed explicit `wheel` build/dev requirements and the redundant interactive
  tutorials `nbclient` declaration. Notebook testing retains its own dependencies;
  core runtime remains dependency-free.
- Simplified notebook definition comparisons and updated installation checks and
  documentation. Added successful set-power/standby assertions to the existing test.

Python source across library/examples/scripts/tests: **29 -> 25 files** and
**4,221 -> 4,159 lines**, including blanks/comments. The core's 12 small modules
remain because they have distinct responsibilities and stable import paths.
The API signature inventory is unchanged. The four old example filenames are
replaced by the existing terminal commands below; notebook filenames and runner
arguments remain unchanged. No compatibility wrappers were added.

| Lesson | Notebook | Command after `python examples/tutorials/run_tutorial.py` |
| --- | --- | --- |
| Read status and diagnostics | [Lesson 1](../examples/tutorials/01_read_status.ipynb) | `read-status` |
| Set power in standby | [Lesson 2](../examples/tutorials/02_set_power.ipynb) | `set-power` |
| One controlled session | [Lesson 3](../examples/tutorials/03_controlled_session.ipynb) | `controlled-session` |
| Fault evidence and lost replies | [Lesson 4](../examples/tutorials/04_handle_faults.ipynb) | `faults` |

## Architecture and operation

The controller owns one serial or simulated transport and serializes transactions.
Protocol parsing validates complete replies; serial failures invalidate the session.
The simulator is an independent peer with explicit fixture policies. Telemetry
owns one polling worker and bounded immutable history. Dash consumes only cached
snapshots. See the [API](../docs/API.md) and [integration guide](../docs/INTEGRATION.md).

For learning, install `.[tutorials]`, run `python -m jupyterlab examples/tutorials`,
and execute notebook cells in order. Terminal lessons need only the core package.
Each default execution owns a fresh simulator and completes its connection lifetime
within one call. No notebook imports or executes the terminal file.

The [operator guide](../examples/tutorials/README.md#human-operated-hardware)
provides the later serial workflow. Model, native port, matching baud and timeout
are explicit; writes require an approved target/ceiling. Configuration validation
precedes open, CONNECT precedes ?SV, and RUN precedes the lesson sequence.
Identification-only mode stops after ?SV. Cancellation/errors never retry, replay
commands or fall back to simulation. Hardware switches default to disabled.

## Validation evidence

[E034](../records/RECORDS.md#e034), 2026-09-11T00:05:33.655180+00:00:
**216 tests PASS**, 95% library coverage, including 71 tutorial/operator cases and
eight fresh notebook runs from empty directories. Hardware branches use simulated
serial factories; physical opening/discovery is blocked in tests and kernels.
All notebook functions match their terminal equivalents. All 11 validator stages
passed: tests, lint, formatting, strict typing, dependency consistency, builds,
CLI, synchronous/async examples, clean core/extras installs and Node watchdog.
All 52 source hashes stayed unchanged; manual/framework hashes match.

Version 0.1.0; source-manifest SHA-256:
`29b070ac92fa9b7bca04287c1ef96afec593e2e873b704684d55f80d4d8906e0`.
[Manifest](../records/validation.json), [review](../records/RECORDS.md#e033),
[dependencies](../records/requirements-validated.txt). An additional isolated wheel
build passed with only setuptools 84.0.0 as the build dependency. Windows 11/Python
3.12.14 and Node 24.19.0 were tested. One non-failing pyzmq selector-thread warning;
no skipped or failed tests. Browser evidence E024 applies to unchanged GUI assets.
Reproduce with `python scripts/validate.py` after installing `.[dev,serial,gui]`.

## Hardware review and recovery

Physical integration remains **AWAITING_HUMAN_REVIEW**. Follow
[HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md): approve this candidate and
actual connection, begin with passive open and one `?SV` query, then verify framing,
read semantics and actual no-fault replies (TEST-010A–C). Only after Stage 1, approve
the exact writes, limits, beam/cooling/warmup/interlock conditions and physical abort
procedure (TEST-010D–G). Software publication does not grant hardware authority.

Status and fault lessons are read-only. Setpoint control retains the approved target
in standby. The controlled lesson checks readiness/history, sets power, enables,
opens the safety shutter once, samples, closes it and verifies standby. It retains
the target. Fault injection and lost-reply exercises remain simulator-only.

Actual idle power, ramp/settling, quantization, echo timing, latency, wiring,
interlocks and calibration are unverified. Simulator fault latching and numerical
values are fixtures. The safety shutter is not an experimental modulator.
On error or Ctrl+C, stop subsequent commands and follow the physical abort procedure.
A missing acknowledgment may follow an applied command; communication close is not
shutdown. Do not send blind cleanup writes or assume reopening clears late replies.
If shutdown is approved and communication is trustworthy, verify shutter closure
and standby; full heater/cooling shutdown follows the manual. Software rollback
cannot undo a physical action. All test kernels/simulator sessions completed;
no physical port was enumerated or opened, and upstream was not modified.
