"""Stable public exceptions; uncertain writes must never be retried automatically."""


class VerdiError(Exception):
    """Base class for controller and transport failures."""


class TransportError(VerdiError):
    """Communication failed; a write may already have reached the laser."""


class ResponseTimeout(TransportError):
    """A complete reply did not arrive before the deadline."""


class ConnectionUnusable(TransportError):
    """Closed or desynchronized connection; explicit replacement is required."""


class ProtocolError(VerdiError):
    """Reply does not conform to the expected documented representation."""


class DeviceError(VerdiError):
    """A documented RANGE ERROR, Command Error, or Query Error reply."""

    def __init__(self, instruction: str, response: str) -> None:
        self.instruction = instruction
        self.response = response
        super().__init__(f"{instruction}: {response}")


class WritesDisabled(VerdiError):
    """The caller has not explicitly enabled controller writes."""
