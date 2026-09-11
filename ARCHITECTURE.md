# Driver architecture

Three substantive modules and two package entry points:

| Module | Responsibility |
| --- | --- |
| `controller.py` | Public hardware API, serial I/O, manual parsing, validation and two errors |
| `simulator.py` | Same public API with independent in-memory wire replies and fixture controls |
| `gui.py` | Optional caller-scheduled cache and Dash view |
| `__init__.py` | Four exports; imports no optional clients |
| `__main__.py` | Read-only simulator CLI and explicit GUI worker lifecycle |

Follow `set_power_w()`: validate watts and the rounded ceiling, format `P=nn.nnnn`,
lock the controller, encode one CR/LF request, exchange once and decode one reply.
`read()` follows the same path and parses the documented representation. `status()`
holds the lock across fourteen reads. The complete physical path is in controller.py.

SimulatedVerdi inherits those public operations, input checks and failure handling.
It overrides only the private open/close/exchange operations; its reply generator
does not reuse the production parser. There is no transport object, factory,
registry, ownership manager, protocol interface or public raw-command escape hatch.

Both implementations keep explicit connected/failed state and one I/O lock.
Construction is passive; connect/disconnect issue no laser instructions. A complete
DeviceError consumes a rejection without invalidating the session. Timeout,
malformed reply, interruption or unexpected transaction error latches failure.
Cleanup can be retried, but cannot clear that latch, replay state or undo commands.

Results are plain dictionaries, numbers, strings and fault-code lists. There are
no model/query/state enums, dataclasses, serialization adapters or compatibility
imports. Fault descriptions and uncertain hardware behavior live in the protocol
documentation. Four root exports suffice: VerdiController, SimulatedVerdi,
VerdiError and DeviceError.

The experiment owns connection lifetime, polling and logging. Optional Monitor
calls the public status API; one caller acquires while a short cache lock protects
copied snapshots. Dash only reads that cache. The simulator CLI explicitly starts
and drains its GUI worker before disconnecting; core/Monitor construction starts none.
pySerial loads at physical connect and Dash loads at app creation.

[API and migration](docs/API.md) describe integration. [AGENTS.md](AGENTS.md) and
[provenance](records/FRAMEWORK.md) preserve engineering continuity. Hardware work
requires the [candidate review gate](HARDWARE_VALIDATION.md).
