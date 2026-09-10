"""Malformed integer responses use the protocol failure and recovery contract."""

import sys

import pytest

from coherent_verdi import (
    ConnectionUnusable,
    ControllerConfig,
    Model,
    ProtocolError,
    Query,
    SimulatedTransport,
    VerdiController,
)


@pytest.mark.parametrize("query", [Query.LASER, Query.BAUDRATE, Query.FAULTS, Query.FAULT_HISTORY])
def test_integer_conversion_limit_invalidates_session(query):
    original_limit = sys.get_int_max_str_digits()
    sim = SimulatedTransport()
    with VerdiController(sim, ControllerConfig(Model.V5)) as controller:
        try:
            # Exercise the interpreter guard deterministically, even when the
            # invoking process has disabled or increased its default limit.
            sys.set_int_max_str_digits(640)
            sim.inject(b"9" * 641 + b"\r\n")
            with pytest.raises(ProtocolError, match="conversion limit"):
                controller.query(query)
            before = sim.requests
            with pytest.raises(ConnectionUnusable):
                controller.laser_state()
            assert sim.requests == before
        finally:
            sys.set_int_max_str_digits(original_limit)

        replacement = SimulatedTransport()
        controller.replace_transport(replacement)
        assert replacement.requests == ()
        assert controller.power_w() == 0
