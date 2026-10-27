# Developing the controller and GUI

Start with `uv run verdi gui`, select Simulator, click Connect and then
Start monitoring. CLI connection options only prefill the form; startup is
disconnected and monitoring is paused. Tests replace serial construction and discovery
with fakes; running them never opens physical hardware. The [GUI guide](GUI.md)
covers launch commands and operator-facing controls.

## Development setup and checks

From the checkout, install all extras and run the software checks:

```sh
uv sync --all-extras
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
node scripts/test_watchdog.cjs
uv build
uv run scripts/install_smoke.py
```

Node.js runs the dashboard watchdog, knob and browser power-validation tests.
Tests replace physical
serial access with fakes; these checks do not establish hardware timing, optical
safety or bench readiness. The [simulator reference](SIMULATOR.md) describes
synthetic operation and its limits.

`uv sync` installs the project in editable mode plus the `dev` dependency group
(pytest, ruff, mypy). `uv.lock` pins dependencies; CI uses `uv sync --locked`.
Change dependencies with `uv add` / `uv remove` (`--dev` for tools,
`--optional gui` for the dashboard). Refresh pins with `uv lock --upgrade` and
commit `uv.lock` with `pyproject.toml`.

Source distributions include the manual, tutorial notebooks and tests; wheels
contain the controller package.

The installation smoke check runs all nine notebooks against an installed wheel
with fake serial ports and explicit fixture inputs. It checks their write scopes,
uses a headless plotting backend, and verifies lesson 07's combined CSV inside its
temporary test directory. Notebook hardware outputs and repository data are not
regenerated. To check a build in another folder, use
`python scripts/install_smoke.py --dist-dir <folder>`.

The 2026-10-27 software review passed 1,151 tests, Ruff lint/format, mypy, browser
asset checks, dependency/lock checks and clean-environment package checks for the
CLI, all nine notebooks and GUI lifecycle. These checks use fake serial ports.
The operator's notebook run report and saved hardware evidence are documented
separately in the [hardware validation record](HARDWARE.md#validation-record-2026-10-27).

## Follow one request

1. `gui.py:create_app` builds the controls and registers three device-action callbacks
   (refresh, submit, refresh_controls, in that order), two connection callbacks
   when a `GuiSession` is supplied, plus two browser-only
   clientside callbacks for the knob and POWER LEVEL lamps.
   The submit callback translates an explicit click into `RequestQueue.submit`.
   Editing an input alone sends nothing. Named callback arguments keep browser
   click counters separate from input values.
2. `monitor.py:RequestQueue` validates and queues the request. The request ID
   combines browser, button and click counter. Repeated delivery of that ID returns
   the existing request rather than sending a second instruction. Action records
   are the only queue state: queued/running records are pending, in order. Browser
   submissions carry `Monitor.generation`; admission rejects an older connection's view.
3. The launcher's single worker calls `Monitor.poll_once`. The session drains
   queued requests, checking permissions, age, readiness and telemetry again at
   execution. Ordinary writes wait behind a pending write. Standby/close take
   priority and cancel older queued ordinary writes.
4. `RequestQueue._write` uses the public controller API. Its `ACTIONS` table
   describes commands and documented readbacks; it does not implement another
   protocol parser. Power uses `set_power_w` to validate a numeric browser value.
5. `controller.py:command` owns the byte transaction and its record: one write,
   `read_until(b"\r\n")`, then `read_until(b">")` when prompts are enabled;
   `read` returns byte payloads; `write`/`command` return full wire replies.
   Full wire replies remain in transaction evidence. Explicit `get_value`
   calls `read()` before decoding and interpretation. `set_value()` calls `write()`
   before validating the acknowledgment. Named `get_...` and `set_...` helpers
   use those typed entry points. `_interpret_reply()` only interprets an existing
   reply, with the same transaction lock held.
   An uncertain exchange retires the connection permanently. There is no retry or replay.
6. The session records acknowledgment and readback separately. An acknowledgment
   confirms protocol acceptance; a matching getter confirms reported state.
   Neither establishes physical completion. Browser callbacks render cached copies.

## Ownership and locks

`monitor.py` owns telemetry and the request queue; `gui.py` owns the view,
connection lifecycle and worker/server lifetime.
`Monitor` constructs its queue immediately. Building a Dash view never changes
polling, opens a connection, or starts a worker. `gui.py:GuiSession` owns
connection lifetime in the CLI GUI. It keeps a stable monitor and calls
`Monitor.reset` once per connection change to replace caches and controller state.
Queue admission closes atomically with each connection request, before the worker
can open the next connection. Browser click counters survive cache resets.
The monitor owns the connection generation; the GUI clears operator readiness
when it changes. Acknowledged hardware baud/prompt writes update the runtime's
cached settings for reconnects, without performing extra device queries.
`run_gui` starts one worker and a stoppable local HTTP server;
Close application and Ctrl+C drain I/O and release the port. Standalone
`create_app(monitor)` integrations remain caller-owned and omit the connection bar.

The controller's reentrant lock protects complete transactions. The monitor's
runner lock rejects a second acquisition caller; its short lock protects published
samples. The queue's short cache lock protects action and result updates.
Browser callbacks never hold the transaction lock or perform device I/O. A running
action is copied before execution, then its finished result is published under
the cache lock so readers cannot observe a partly modified result.
Copy controller transaction evidence before taking the cache lock, so a blocked
controller cannot delay browser snapshots. On errors, prefer the exception's
attached transaction: two different attempts can have byte-identical records.

Call `monitor.wait(stop_event)` between acquisitions to maintain start-to-start
cadence. New requests wake the wait. On shutdown, set the stop event, close the
monitor, join the worker, then disconnect. Close cancels queued work and wakes
the worker; an exchange already in progress must finish. No shutdown step sends
laser-state commands automatically.

CLI `watch` uses the same start-to-start wait as the GUI. Worker exceptions are
reported after local connection cleanup rather than appearing as a clean exit.

## Samples and browser updates

`poll_once` publishes only complete overview samples. A write between reads
invalidates the partial overview: the return has `interrupted: true`, and the
next cycle reacquires it. Paused/closing cycles return `paused: true`. Neither
return replaces the last complete sample; its age continues increasing normally.

`latest()` copies one sample for freshness checks and readings. `snapshot()`
copies the full bounded history for export. `power_history(counter)` copies only
new plot points; each browser stores its own counter. Failures append gaps, not
old readings. Plot updates retain at most the configured history size. UTC is for
display; elapsed time and freshness use a monotonic clock, which ignores clock
adjustments. The browser's faster action timer runs only while requests are pending.

## Adding a query or command

- Check the local manual and `docs/PROTOCOL.md` first. Do not guess units, enum
  meanings, response formats, safe ranges or a getter that is not documented.
- Add a query to `controller.py:QUERY_INFO`, including its manual name, unit and
  reply constraint (code queries list their labels). `STATUS_FIELDS` defines the deliberately small overview;
  adding a query to the catalogue alone does not increase periodic serial traffic.
- Add an independent simulator reply in `simulator.py` and protocol tests with
  explicit wire bytes. The simulator must not derive its expected replies from
  the driver's parser; independent expectations help catch shared mistakes.
- Add a write to `controller.py:COMMAND_INFO`, then implement a named `set_...`
  helper through `set_value()` and `write()`. Validate before sending bytes. Add it to the GUI's
  `ACTIONS` table with a readback only if the manual documents one. Actions with
  an operand use a command ending in `=`; fixed commands include their operand.
  The GUI sends fixed commands through `set_value()`; power, temperature, lock
  and baud operands use their named setters. Disabled menu navigation has no
  executable GUI action entry.
- Exercise the GUI queue, result and permission paths in `test_gui_controls.py`.
  Use `FaultyVerdi` for lost acknowledgments, mismatches and adapter failures.
- A new GUI button needs a `BUTTONS` entry (the server-side channel allowlist).
  Add it to `FRESH_BUTTONS` if it is an ordinary write, and put write controls
  inside one of the `WRITE_GROUPS` fieldsets so the server and the watchdog can
  disable them. Browser-only behaviour (`assets/panel.js`) may edit unsent inputs
  but must never submit a request.

## Communication invariants

One transaction lock covers writing, the CR/LF reply and, by default, the
following terminal prompt. An empty RX queue after CR/LF does not complete a
prompt-enabled transaction. pySerial `read_until` consumes the reply and then
the prompt, using a fixed timeout per stage and a combined 4096-byte limit.
There are no automatic purges, input-queue polls or retries. Preserve consumed
bytes in `response`, including partial replies on failure. The transaction record
contains only instruction, request, response, payload, outcome and error.

Keep the read-only default, server-side checks, finite power ceiling, bounded
queue, deduplication and failure latch. A Python exception's type does not prove
that a command was rejected: the transaction's outcome is the evidence.

Use the [development check commands](#development-setup-and-checks) above.
Software and simulator checks establish protocol behavior, not hardware timing,
optical safety or bench readiness.


## Notebook reference tests

`tests/data/verdi_v2_status.json` freezes the 41 byte payloads saved in the
successful V2 health-check run on 2026-10-26. Replay frames append CR/LF and the
terminal prompt observed in lesson 01; they are reconstructed frames, not
individual raw captures for every query. Tests execute lessons 01-03 against
these replies without consulting the simulator's values. Keep `?DIOS` excluded
from this survey: the actual laser rejected it. Compound `?ACAD` data is kept as bytes.

The shared serial peer uses pySerial's own `read_until` implementation. Synthetic
cases cover incomplete replies, delayed prompts, write permissions and power
limits. Lessons 04-06 still use simulation for their write and readiness cases;
the read-only reference run does not validate emission or physical readiness.
