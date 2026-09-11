# Integration into an experiment stack

Create one controller per connection and share it with clients. Its lock serializes
requests and complete status/diagnostic groups. Status contains 14 sequential
readings: timestamp marks the start and duration covers all queries. Front-panel
actions can still change hardware between queries.

```python
from coherent_verdi import SimulatedTransport, VerdiController

laser = VerdiController(SimulatedTransport(), model="V5")
laser.connect()
try:
    print(laser.read_power_w())
    # Share this connected object with the experiment's other components.
finally:
    laser.disconnect()
```

The hardware form takes an operator-identified port instead of the simulator.
After candidate approval, start with passive connect and one `read("?SV")`.
Broader status acquisition needs verified clear-fault text. See [API](API.md) and
[physical procedure](../HARDWARE_VALIDATION.md).

Import, construction, connect and disconnect issue no laser commands. Within an
approved scope and trustworthy connection, explicitly command shutter closure and
standby and verify readbacks. After uncertain I/O, stop issuing commands and use
the operator's physical abort procedure. Context cleanup only closes communication;
it cannot undo a command that executed before its reply was lost.

An interruption, timeout or malformed reply invalidates the controller session.
Disconnect remains retryable if cleanup fails. Establish a clean connection before
constructing another controller; reopening does not prove delayed untagged replies
are gone. Complete DeviceError replies can be diagnosed using the same session.
No state is automatically restored, reset or replayed.

## Monitoring and logging

Monitor borrows a controller without connecting, closing or creating workers.
Call `poll_once()` from the experiment scheduler. Write its returned Sample with
`to_json()` to JSON Lines, a notebook or an existing logger. No global handlers
or hidden callbacks are installed.

`snapshot()` copies the bounded cache under a short lock without waiting for I/O.
It contains model, simulated, history, interval_s and age_s. Samples contain
sequence, UTC attempt time, status or an error string. Age uses monotonic time
from acquisition start. Errors produce gaps; source metadata remains known when
a reading fails. Use a new monitor for each new controller/session.

`interval_s` is a scheduling hint used for GUI staleness and by the launcher.
The launcher waits this interval after each sample; no exact rate or catch-up
burst is promised. Other schedulers own timing. Finish acquisition before disconnect.

## Async applications and Dash

[async_integration.py](../examples/async_integration.py) puts the complete
connection/read/cleanup block inside `asyncio.to_thread`. Cancelling the await
does not cancel serial I/O or stop emission. Drain work before releasing an
application-owned controller.

`coherent_verdi.gui.create_app(monitor)` builds the read-only Dash app. It reads
only cached public monitor data; Monitor uses the public `status()` API. The
caller schedules polling. The simulator CLI explicitly starts/joins one worker;
browser tabs never create extra acquisition.

Serve on loopback or behind the stack's authenticated proxy. Disable debug and
reloader; do not create a controller per web worker. GUI errors show unknown
values, old samples become stale, and a browser watchdog warns after 10 seconds
without updates. Suspended browsers can update only on resume. The GUI provides
observation, not a hardware interlock or shutdown mechanism.
