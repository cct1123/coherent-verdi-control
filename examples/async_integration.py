"""Async stacks can offload the synchronous API without creating another serial owner."""

import asyncio

from coherent_verdi import (
    ControllerConfig,
    Diagnostics,
    Model,
    SimulatedTransport,
    Status,
    VerdiController,
)


def read_in_worker() -> tuple[Status, Diagnostics]:
    """Keep operation and cleanup ownership together, including after cancellation."""
    with VerdiController(SimulatedTransport(Model.V2), ControllerConfig(Model.V2)) as laser:
        return laser.status(), laser.diagnostics()


async def main() -> None:
    # Cancellation stops awaiting this result, not the worker or its command.
    # asyncio.run drains its executor before exit; a larger stack must also drain.
    status, diagnostics = await asyncio.to_thread(read_in_worker)
    print(f"{status.model.value}: {status.power_w:.3f} W; {diagnostics.software_version}")


if __name__ == "__main__":
    asyncio.run(main())
