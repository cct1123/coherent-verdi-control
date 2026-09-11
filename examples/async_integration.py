"""Offload a complete synchronous session; keep operation and cleanup in one worker."""

import asyncio

from coherent_verdi import SimulatedVerdi


def read_in_worker() -> tuple[dict, dict]:
    with SimulatedVerdi("V2") as laser:
        return laser.status(), laser.read_diagnostics()


async def main() -> None:
    # Cancelling the await cannot stop serial I/O. The application must drain its
    # executor before exit; asyncio.run does so here, including on cancellation.
    status, diagnostics = await asyncio.to_thread(read_in_worker)
    print(f"{status['model']}: {status['power_w']:.3f} W; {diagnostics['software_version']}")


if __name__ == "__main__":
    asyncio.run(main())
