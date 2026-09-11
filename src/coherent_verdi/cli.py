"""Hardware-free command line. No physical-port option is exposed in this phase."""

import argparse
import sys
from collections.abc import Sequence
from time import sleep

from .controller import VerdiController
from .errors import VerdiError
from .models import ControllerConfig, Model
from .protocol import Query
from .serialization import to_json
from .simulator import SimulatedTransport
from .telemetry import TelemetryService


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
    config = ControllerConfig(model, allow_writes=args.allow_writes or args.demo)
    try:
        with VerdiController(sim, config) as controller:
            sim.set_key(args.sim_key_on or args.demo)
            if args.demo:
                controller.set_power_w(1.0)
                controller.enable_laser()
                controller.set_shutter(open=True)
            result: object
            if args.command == "status":
                result = controller.status()
            elif args.command == "diagnostics":
                result = controller.diagnostics()
            elif args.command == "query":
                result = controller.query(Query(args.query))
            elif args.command in ("set-power", "standby", "enable", "shutter"):
                if args.command == "set-power":
                    controller.set_power_w(args.watts)
                elif args.command == "standby":
                    controller.standby()
                elif args.command == "enable":
                    controller.enable_laser()
                else:
                    controller.set_shutter(open=args.state == "open")
                result = controller.status()
            elif args.command == "watch":
                if not 1 <= args.count <= 100000:
                    raise ValueError("count must be in [1, 100000]")
                service = TelemetryService(controller, interval_s=args.interval)
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
                from .gui import create_app

                with TelemetryService(controller) as service:
                    app = create_app(service)
                    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)
                return 0
            print(to_json({"simulated": True, "result": result}))
        return 0
    except KeyboardInterrupt:
        return 130
    except (VerdiError, ValueError, ImportError) as exc:
        print(
            to_json({"error": str(exc), "type": type(exc).__name__, "simulated": True}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
