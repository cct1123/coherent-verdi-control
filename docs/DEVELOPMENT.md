# Developing the controller and GUI

Start with `verdi gui --allow-writes --power-limit-w 0.5`, without a serial
`--port`. This uses the simulator. Tests replace serial construction and discovery
with fakes; running them never opens physical hardware.

## Follow one request

1. `gui.py:create_app` builds the controls and registers three server callbacks
   (refresh, submit, refresh_controls, in that order) plus two browser-only
   clientside callbacks for the knob and POWER LEVEL lamps.
   The submit callback translates an explicit click into `ControlSession.submit`.
   Editing an input alone sends nothing. Named callback arguments keep browser
   click counters separate from input values.
2. `gui.py:ControlSession` validates and queues the request. The request ID
   combines browser, button and click counter. Repeated delivery of that ID returns
   the existing request rather than sending a second instruction. Action records
   are the only queue state: queued/running records are pending, in order.
3. The launcher's single worker calls `Monitor.poll_once`. The session drains
   queued requests, checking permissions, age, readiness and telemetry again at
   execution. Ordinary writes wait behind a pending write. Standby/close take
   priority and cancel older queued ordinary writes.
4. `ControlSession._write` uses the public controller API. Its `ACTIONS` table
   describes commands and documented readbacks; it does not implement another
   protocol parser. Power uses `set_power_w` to validate a numeric browser value.
5. `controller.py:command` owns the byte transaction and its record: one write,
   `read_until(b"\r\n")`, then `read_until(b">")` when prompts are enabled;
   `get` returns byte payloads; `set`/`command` return full wire replies.
   Full wire replies remain in transaction evidence. Explicit `get_value`
   and named setting helpers opt into decoding and interpretation afterwards. An uncertain exchange
   retires the connection permanently. There is no retry or replay.
6. The session records acknowledgment and readback separately. An acknowledgment
   confirms protocol acceptance; a matching getter confirms reported state.
   Neither establishes physical completion. Browser callbacks render cached copies.

## Ownership and locks

`Monitor` constructs its session immediately. Building a Dash view never changes
how polling works, opens a connection, or starts a worker. The CLI owns connection
lifetime, worker startup and shutdown. A custom launcher must do the same.

The controller's reentrant lock protects complete transactions. The monitor's
runner lock rejects a second acquisition caller; its short lock protects published
samples. The session's short cache lock protects queue and result updates.
Browser callbacks never hold the transaction lock or perform device I/O. A running
action is copied before execution, then its finished result is published under
the cache lock so readers cannot observe a partly modified result.

Call `monitor.wait(stop_event)` between acquisitions to maintain start-to-start
cadence. New requests wake the wait. On shutdown, set the stop event, close the
monitor, join the worker, then disconnect. Close cancels queued work and wakes
the worker; an exchange already in progress must finish. No shutdown step sends
laser-state commands automatically.

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
- Implement a new write in a typed controller method and route its documented
  spelling through `command`. Validate before sending bytes. Add it to the GUI's
  `ACTIONS` table with a readback only if the manual documents one. Actions with
  an operand use a command ending in `=`; fixed commands include their operand.
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

Use the check commands in [README](../README.md#reference-and-development).
Software and simulator checks establish protocol behavior, not hardware timing,
optical safety or bench readiness.
