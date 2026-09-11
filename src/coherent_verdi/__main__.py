"""Hardware-free command line. No physical-port option is exposed in this phase."""

import argparse
import sys
from collections.abc import Sequence
from time import sleep

from .controller import VerdiController
from .errors import VerdiError
from .monitor import Monitor, to_json
from .protocol import Model, Query
from .simulator import SimulatedTransport


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Verdi controller — hardware-free simulator CLI")
    p.add_argument("--model", choices=[m.value for m in Model], default="V5")
    p.add_argument("--allow-writes", action="store_true", help="allow explicit simulated commands")
    p.add_argument("--sim-key-on", action="store_true", help="set the simulated physical key ON")
    p.add_argument("--demo", action="store_true", help="explicitly prepare a 1 W simulated beam")
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("status", "diagnostics", "standby", "enable"):
        commands.add_parser(name)
    commands.add_parser("query").add_argument("query", choices=[q.value for q in Query])
    commands.add_parser("set-power").add_argument("watts", type=float)
    commands.add_parser("shutter").add_argument("state", choices=["open", "closed"])
    watch = commands.add_parser("watch")
    watch.add_argument("--count", type=int, default=10)
    watch.add_argument("--interval", type=float, default=1.0)
    gui = commands.add_parser("gui")
    gui.add_argument("--port", type=int, default=8050, help="loopback HTTP port (not serial)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    model = Model(args.model)
    sim = SimulatedTransport(model)
    try:
        with VerdiController(
            sim, model=model, allow_writes=args.allow_writes or args.demo
        ) as controller:
            sim.set_key(args.sim_key_on or args.demo)
            if args.demo:
                controller.set_power_w(1.0)
                controller.start()
                controller.set_shutter(open=True)
            result: object
            if args.command == "status":
                result = controller.status()
            elif args.command == "diagnostics":
                result = controller.read_diagnostics()
            elif args.command == "query":
                result = controller.read(Query(args.query))
            elif args.command in ("set-power", "standby", "enable", "shutter"):
                if args.command == "set-power":
                    controller.set_power_w(args.watts)
                elif args.command == "standby":
                    controller.stop()
                elif args.command == "enable":
                    controller.start()
                else:
                    controller.set_shutter(open=args.state == "open")
                result = controller.status()
            elif args.command == "watch":
                if not 1 <= args.count <= 100000:
                    raise ValueError("count must be in [1, 100000]")
                service = Monitor(controller, interval_s=args.interval)
                failed = False
                for i in range(args.count):
                    sample = service.poll_once()
                    failed |= sample.status is None
                    print(to_json({"simulated": True, "sample": sample}, indent=None), flush=True)
                    if i + 1 < args.count:
                        sleep(service.interval_s)
                return 2 if failed else 0
            else:
                if not 1 <= args.port <= 65535:
                    raise ValueError("HTTP port must be in [1, 65535]")
                # The launcher explicitly owns the polling thread; the driver and
                # Monitor never create one. Server callbacks only read the cache.
                from threading import Event, Thread

                from .gui import create_app

                service = Monitor(controller)
                app = create_app(service)
                stop = Event()

                def poll() -> None:
                    while not stop.is_set():
                        service.poll_once()
                        stop.wait(service.interval_s)

                worker = Thread(target=poll, name="verdi-monitor")
                worker.start()
                try:
                    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)
                finally:
                    stop.set()
                    worker.join()  # Finish the bounded sample before releasing the connection.
                return 0
            print(to_json({"simulated": True, "result": result}))
        return 0
    except KeyboardInterrupt:
        return 130
    except (VerdiError, PermissionError, ValueError, ImportError) as exc:
        print(
            to_json({"error": str(exc), "type": type(exc).__name__, "simulated": True}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
