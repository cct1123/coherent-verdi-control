"""Async stacks can offload the synchronous API without creating another serial owner."""

import asyncio

from coherent_verdi import ControllerConfig, Model, SimulatedTransport, VerdiController


async def main() -> None:
    with VerdiController(SimulatedTransport(Model.V2), ControllerConfig(Model.V2)) as laser:
        status, diagnostics = await asyncio.gather(
            asyncio.to_thread(laser.status), asyncio.to_thread(laser.diagnostics)
        )
        print(f"{status.model.value}: {status.power_w:.3f} W; {diagnostics.software_version}")


if __name__ == "__main__":
    asyncio.run(main())
