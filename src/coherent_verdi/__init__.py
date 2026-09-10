"""Coherent Verdi control. Importing this package never accesses hardware."""

from .controller import VerdiController
from .errors import (
    ConnectionUnusable,
    DeviceError,
    ProtocolError,
    ResponseTimeout,
    TransportError,
    VerdiError,
    WritesDisabled,
)
from .models import (
    ControllerConfig,
    Diagnostics,
    Fault,
    LaserState,
    Model,
    SerialConfig,
    ServoState,
    Status,
    TelemetrySample,
    TelemetrySnapshot,
)
from .protocol import Query
from .simulator import SimulatedTransport
from .telemetry import TelemetryService
from .transport import SerialTransport, Transport, open_serial

__all__ = [
    "ConnectionUnusable",
    "ControllerConfig",
    "DeviceError",
    "Diagnostics",
    "Fault",
    "LaserState",
    "Model",
    "ProtocolError",
    "Query",
    "ResponseTimeout",
    "SerialConfig",
    "SerialTransport",
    "ServoState",
    "SimulatedTransport",
    "Status",
    "TelemetrySample",
    "TelemetrySnapshot",
    "TelemetryService",
    "Transport",
    "TransportError",
    "VerdiController",
    "VerdiError",
    "WritesDisabled",
    "open_serial",
]
