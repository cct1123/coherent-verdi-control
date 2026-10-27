# Command-line reference

Run commands from the checkout with `uv run verdi`. All hardware examples below
use COM5, V2 and 19200 baud; substitute your actual settings.
`uv run python -m coherent_verdi` is equivalent.

## Installation options

From a checkout:

```sh
uv sync
```

Add the optional browser panel with `uv sync --extra gui`. A later plain
`uv sync` removes the optional GUI dependencies. pySerial is installed automatically.
For a pip-managed environment, `pip install .` also works from the checkout.
To add the package to another uv project:

```sh
uv add "coherent-verdi-control @ git+https://github.com/cct1123/coherent-verdi-control.git"
```

## Connection options

Put connection options **before** the subcommand:

```sh
uv run verdi --port COM5 --model V2 --baudrate 19200 query ?SV
```

| Option | Meaning |
| --- | --- |
| `--port COM5` | Serial port; Linux examples include `/dev/ttyUSB0` |
| `--model V2` | Actual model: V2, V5 or V6; required with a serial port |
| `--baudrate 19200` | Match the front panel; default 19200 |
| `--timeout-s 2` | Serial write and receive timeout; each reply/notice/prompt read has its own wait; default 1 second |
| `--no-prompt` | Use only when the instrument prompt is already disabled |

Without a serial `--port`, commands use the simulator. `commission` requires
an explicit hardware port and model. The driver does not discover the model,
detect baud or configure echo/prompt modes on connection.
The reader consumes the reply CR/LF and the enabled trailing prompt using
`read_until()`. It adds no extra delay between queries.

## Individual queries and diagnostics

```sh
uv run verdi --port COM5 --model V2 --baudrate 19200 query ?SV
uv run verdi --port COM5 --model V2 --baudrate 19200 query ?P
uv run verdi --port COM5 --model V2 --baudrate 19200 diagnostics
```

`query` prints an interpreted value as JSON. `diagnostics` reads software version,
operating hours and fault history. Long query names are accepted too; quote names
containing spaces. The [protocol reference](PROTOCOL.md) lists supported queries.

## Raw capture for commissioning

```sh
uv run verdi --port COM5 --model V2 --baudrate 19200 commission > identify.jsonl
uv run verdi --port COM5 --model V2 --baudrate 19200 commission --query ?F > active-fault.jsonl
```

The default is one `?SV` query. Repeat `--query` to select an ordered sequence.
Each attempt emits one JSON line containing instruction, request/reply bytes as
hex, payload, outcome and any error. A captured reply is evidence to inspect;
it does not establish physical readiness. It stops at the first rejection or
communication failure.
See [hardware commissioning](HARDWARE.md#first-read).

## Full status and monitoring

Fault queries interpret `SYSTEM OK` as an empty fault list and preserve positive
fault codes. Unexpected replies stop the session; inspect them using the
[hardware procedure](HARDWARE.md#fault-clear-reply-and-full-status).

```sh
uv run verdi --port COM5 --model V2 --baudrate 19200 status
uv run verdi --port COM5 --model V2 --baudrate 19200 watch --count 10 --interval 1
```

`status` prints one overview as JSON. `watch` prints JSON lines for repeated
samples. Its defaults are 10 samples and a 1-second target start-to-start interval,
including acquisition time. Each overview uses 14 sequential queries; it is not
a simultaneous measurement. Both commands are read-only.

## Explicit writes

Prefer the [set-power notebook](../examples/05_set_power.ipynb) for a checked
standby procedure and the [controlled session](../examples/06_key_on_and_run.ipynb)
for enabling and shutter operation. Confirm physical readiness and the site's
approved power ceiling before enabling writes.

The command form is `command "INSTRUCTION" --allow-writes`. For example,
**only if 0.25 W and a 0.5 W ceiling are approved for your setup**, this changes
the stored setpoint:

```sh
uv run verdi --port COM5 --model V2 --baudrate 19200 command "P=0.25" --allow-writes --power-limit-w 0.5
```

This command alone does not check standby or shutter state. Writes require
`--allow-writes`; model ratings are software ceilings, not safe site limits.
Each attempted write emits transaction evidence as JSONL. A failed acknowledgment
may mean the instruction executed; commands are never automatically replayed.
The CLI uses `set_value()` and records `acknowledged` only after validating a
successful reply. Documented device errors are `rejected`; malformed replies are
`failed`. Transport failures leave write outcomes `unknown` because the command
may already have executed.

## Browser panel

```sh
uv sync --extra gui
uv run verdi --port COM5 --model V2 --baudrate 19200 gui
```

CLI settings prefill the form. The GUI starts disconnected and paused; click
Connect, then follow the [GUI commissioning steps](GUI.md) before Start monitoring.
For another HTTP port, append `gui --port 8051`: the global `--port` selects the
serial device, while the option after `gui` selects the HTTP port.

GUI writes require `gui --allow-writes --power-limit-w N` with an approved ceiling.
Disconnect and Close application release communication without changing laser state.

## Help and failures

```sh
uv run verdi --help
uv run verdi commission --help
uv run verdi gui --help
```

Failures return exit code 2; Ctrl+C returns 130. Errors are printed as JSON on
stderr, and attempted captures/writes retain their transaction records on stdout.
Stop on framing errors or timeouts and follow the
[communication-failure procedure](HARDWARE.md#monitoring-and-communication-failure).
