# Engineering report — self-contained Verdi tutorials

Four beginner tutorials are implemented for simulator learning and later
human-operated hardware sessions. **Every demonstration, configuration and
connection function is visible in each notebook.** No notebook imports or runs a
tutorial script. Named sections separate individual functions, execution,
expected results, exercises and optional hardware use. The largest code cell is
22 lines. Start with the [tutorial guide](../examples/tutorials/README.md).

| Tutorial | Notebook | Small Python equivalent |
| --- | --- | --- |
| Read status and diagnostics | [Lesson 1](../examples/tutorials/01_read_status.ipynb) | [read_status.py](../examples/tutorials/read_status.py) |
| Set and verify power in standby | [Lesson 2](../examples/tutorials/02_set_power.ipynb) | [set_power.py](../examples/tutorials/set_power.py) |
| One start–shutter–standby session | [Lesson 3](../examples/tutorials/03_controlled_session.ipynb) | [controlled_session.py](../examples/tutorials/controlled_session.py) |
| Fault evidence and lost replies | [Lesson 4](../examples/tutorials/04_handle_faults.ipynb) | [handle_faults.py](../examples/tutorials/handle_faults.py) |

## Architecture and use

The controller/protocol/transport/simulator/telemetry/CLI/Dash runtime is unchanged.
Notebook functions call the controller library directly. The controlled session
is broken into readiness, enable, sample, normal-stop and orchestration functions;
the two fault exercises have separate visible functions. Hardware configuration,
connection and cleanup are also defined in individual notebook cells.
The [terminal runner](../examples/tutorials/run_tutorial.py) is an optional CLI
alternative and is not a notebook dependency.

In an activated Python 3.11+ environment, install `.[tutorials]` and run
`python -m jupyterlab examples/tutorials`. Run the notebook cells in order.
Default runs create fresh simulators and skip hardware; sessions finish within
one execution cell. Install `.[tutorials,serial]` only when preparing the
separately approved human hardware path. Standalone simulator scripts and the
runner's default need only the dependency-free core.

The [operator guide](../examples/tutorials/README.md#human-operated-hardware)
provides notebook settings and CLI templates. Supply a verified native port,
model, matching baud and timeout. Writes require explicit approved target/ceiling.
CONNECT precedes open and one `?SV` query; RUN precedes lesson operations.
Identification-only mode stops after `?SV`. Configuration errors precede opening;
cancellation, errors and interruptions never trigger retries or simulator fallback.
The 0.25 W target and 0.5 W ceiling shown in simulator exercises are not physical
safe limits. All notebook hardware switches are disabled in the delivered source.

## Reviewed changes

[E031](../records/RECORDS.md#e031) records review and pruning. Fixed a CLI option
that silently ignored `--timeout-s` without `--hardware`; incomplete mode settings
now fail consistently. Removed redundant numeric checks and duplicated operator
test execution, shortened repeated guide prose and normalized publication artifacts
to repository LF line endings. Retained state/readback checks, confirmation,
fault evidence, no-replay behavior and all distinct regression assertions.

The user's final clarification replaced notebook dispatch through helper scripts
with explicit local definitions and direct calls. Application and hardware-helper
definitions are checked against the Python equivalents, while kernel execution
from empty working directories proves notebooks have no adjacent-script dependency.

## Final validation

| Scope | Result |
| --- | --- |
| Software and simulator | **PASS** |
| Four default + four simulated-hardware notebook runs | **PASS** |
| Actual physical behavior/calibration | **UNTESTED** |

Version 0.1.0; final source-manifest SHA-256:
`1e83941dbd88416affb180a51c1d1547679cc9bbdccf9dc20cd504b65977766e`.

[E032](../records/RECORDS.md#e032), [manifest](../records/validation.json),
2026-09-10T23:51:22.454712+00:00: **216 tests PASS**, including 71 tutorial/operator
cases; **95% library statement coverage**. Every notebook executes in a fresh kernel
with real serial opening/discovery blocked, from an otherwise empty working
directory. Tests check source equivalence, permitted imports, code-cell length,
all model workflows, bad inputs/states/readbacks, fault history, interruption,
lost acknowledgments, operator configuration/cancellation and no retries.

Lint/format, strict library typing, dependency consistency, wheel/sdist completeness,
all scripts and the simulator runner in an isolated core installation, installed
GUI/serial extras, CLI/examples and Node watchdog PASS. All 11 validator stages
passed; all 56 source hashes remained unchanged and manual/framework hashes match.
Browser evidence E024 applies to unchanged runtime/assets. Reproduce with
`python scripts/validate.py` after installing `.[dev,serial,gui]`.

Windows 11/Python 3.12.14; JupyterLab 4.6.3, nbclient 0.11.0, nbformat 5.11.1,
ipykernel 7.3.0; Node 24.19.0. One non-failing Windows pyzmq selector-thread fallback
warning; no skipped or failed tests. Normal local permissions were required for
Windows temporary directories. [Dependency snapshot](../records/requirements-validated.txt).
Executed notebook copies are regenerated under `records/tutorial-notebooks/`
and uploaded by CI; source outputs stay clear and hardware settings stay disabled.

## Hardware review, expected outcomes and recovery

Physical integration remains at **AWAITING_HUMAN_REVIEW**. Follow
[HARDWARE_VALIDATION.md](../HARDWARE_VALIDATION.md): approve a specific candidate
and actual link, begin with passive open and one `?SV\r\n`, then verify framing,
read semantics and actual no-fault replies (TEST-010A–C). Only after Stage 1,
approve exact write scope, limits, beam/cooling/warmup/interlock conditions and the
physical abort procedure (TEST-010D–G). Publication does not grant hardware access.

Normal hardware behavior requested by each lesson: status/fault diagnosis is
read-only; setpoint control leaves the approved target stored in standby; the
controlled session verifies readiness, sets power, enables, opens the safety
shutter once, samples once, closes it and verifies standby. It retains the target
and does not establish optical settling. Fault injection/removal and the lost-write
exercise occur only in simulator demonstrations.

Actual idle power, ramp behavior, quantization, echo timing, firmware latency,
wiring, interlocks and calibration remain unverified. The simulator's values and
fault latching are fixture policies. The head shutter is a safety shutter, not an
experimental modulator; status reads are not physical interlocks.

On error or Ctrl+C, stop subsequent commands and use the approved physical abort
procedure. A missing acknowledgment can follow an applied command. Communication
close is not shutdown, and reopening is not proof that late replies cleared.
If communication is verified trustworthy and shutdown is authorized, close the
shutter and enter standby with readback; full heater/cooling shutdown follows the
manual. Software rollback cannot undo a physical action.

All test kernels and simulator sessions completed. No physical port was enumerated
or opened and no upstream template was modified. The user authorized review,
pruning, commit and push of this software candidate; Git history records publication.
