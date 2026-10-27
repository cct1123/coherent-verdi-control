# Coherent Verdi Control

Read power, temperatures and status from **Coherent Verdi V-2, V-5 and V-6**
lasers over RS-232. Use Python, the command line or an optional browser panel.
Communication is read-only by default.

## Install

Install Python **3.11+** and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Download or clone this repository, open a terminal in its folder, then run:

```sh
uv sync
```

Run commands with `uv run`; no environment activation is needed.

## Prepare the connection

1. Connect the power supply through an RS-232 port or USB-to-**RS-232** adapter.
   Check the cable against the [manual](verdi.manual_v5.pdf), Figure 5-1.
2. Find the serial port in Device Manager, or use the
   [port discovery notebook](examples/00_device_discovery.ipynb).
3. Check the laser model and front-panel baud rate. Close other programs or
   notebooks using the port.

The examples below use **COM5, V2 and 19200 baud**. Replace these with your
settings. The controller uses 8N1 with no flow control and expects the instrument
prompt to be enabled. See [hardware setup](docs/HARDWARE.md) for details.

## Read the laser

Start with the software version:

```sh
uv run verdi --port COM5 --model V2 --baudrate 19200 query ?SV
```

Then read output power in watts and diode temperature in degrees Celsius:

```sh
uv run verdi --port COM5 --model V2 --baudrate 19200 query ?P
uv run verdi --port COM5 --model V2 --baudrate 19200 query ?D1T
```

Each command opens the port, reads the reply and releases the port. Supplying
`--port` selects real hardware; omitting it selects the simulator.

## Use Python or notebooks

Create the controller and open the connection first:

```python
from coherent_verdi import VerdiController

laser = VerdiController("COM5", model="V2", baudrate=19200, timeout_s=2)
print("Serial port open:", laser.connect())
```

After the connection succeeds, read values:

```python
print("Software:", laser.read(b"?SV"))
print("Power:", laser.read(b"?P"))
print("Diode temperature:", laser.read(b"?D1T"))
```

`read()` returns payload bytes, such as `b'6.05'`. Supply byte queries without
`\r\n`; the controller adds the terminator and waits for the full reply and
prompt before sending the next instruction.

Use `get_...` helpers for interpreted values, such as `laser.get_power_w()`
returning a float in watts. Named `set_...` helpers validate arguments and
acknowledgments. The byte methods are `read(query)` and `write(instruction)`;
`write()` waits for and returns the full reply, including device error replies.
All writes require `allow_writes=True`; use a site-approved `power_limit_w`.
See the [API reference](docs/API.md) for the raw and typed interfaces.

Release the port when finished:

```python
laser.disconnect()
```

For step-by-step hardware use, follow the [tutorial notebooks](examples/README.md):
connect, quick status, health check, pre-key-on readiness, set power in standby,
and a controlled session.

## Optional browser panel

```sh
uv sync --extra gui
uv run verdi --port COM5 --model V2 --baudrate 19200 gui
```

Open [localhost:8050](http://127.0.0.1:8050/), check the settings and click
**Connect**. Connection and monitoring are separate actions. Follow the
[GUI guide](docs/GUI.md) to verify the active-fault reply before starting monitoring.
The panel displays power, current and temperatures and provides individual queries.

## Before controlling output

Use the [readiness](examples/04_pre_key_on_readiness.ipynb),
[set-power](examples/05_set_power.ipynb) and
[controlled-session](examples/06_controlled_session.ipynb) notebooks with the
manual and your site's laser procedure. Writes require explicit permission and
a site-approved power ceiling. **Disconnecting does not put the laser in standby
or close its shutter.**

Read-only notebooks 01–03 ran successfully on a V2 with firmware 6.05.
Emission control and optical behavior remain unverified on hardware.

## More detail

- [Hardware setup and troubleshooting](docs/HARDWARE.md)
- [Command-line reference](docs/CLI.md)
- [Python API](docs/API.md) and [manual command tables](docs/PROTOCOL.md)
- [GUI guide](docs/GUI.md)
- [Simulator](docs/SIMULATOR.md) and [development](docs/DEVELOPMENT.md)
