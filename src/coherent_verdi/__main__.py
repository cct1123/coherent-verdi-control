"""Read-only Verdi CLI. Supply --port and --model for hardware; otherwise simulate."""

import argparse
import json
import sys
from collections.abc import Sequence
from time import sleep
from typing import Any

from .controller import QUERIES, VerdiController, VerdiError
from .simulator import SimulatedVerdi


def _print_transaction(record: dict[str, Any]) -> None:
    """JSONL preserves exact wire bytes as hex."""
    encoded = dict(record)
    encoded["request_hex"] = encoded.pop("request").hex()
    encoded["response_hex"] = encoded.pop("response").hex()
    print(json.dumps(encoded, allow_nan=False), flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", dest="serial_port", help="Serial port before the subcommand, e.g. COM3"
    )
    parser.add_argument("--model", choices=["V2", "V5", "V6"], help="Required for hardware")
    parser.add_argument("--baudrate", type=int, default=19200, help="Match the front-panel baud")
    parser.add_argument("--timeout-s", type=float, default=1.0)
    parser.add_argument("--active-fault-clear-reply", help="Independently verified ?F clear text")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "diagnostics"):
        commands.add_parser(name)
    commands.add_parser("query").add_argument("query", choices=sorted(QUERIES))
    commission = commands.add_parser(
        "commission", help="Read-only raw query capture; no interpretation"
    )
    commission.add_argument(
        "--query",
        action="append",
        choices=sorted(QUERIES),
        help="Repeat for each exact query; default: one ?SV",
    )
    watch = commands.add_parser("watch")
    watch.add_argument("--count", type=int, default=10)
    watch.add_argument("--interval", type=float, default=1.0)
    commands.add_parser("gui").add_argument(
        "--port", dest="http_port", type=int, default=8050, help="HTTP port (default: 8050)"
    )
    args = parser.parse_args(argv)
    if args.serial_port is not None and args.model is None:
        parser.error("--port requires --model V2, V5 or V6; the model is not discovered")
    if args.command == "commission" and args.serial_port is None:
        parser.error("commission requires an explicit --port and --model")
    if args.serial_port is None and (
        args.baudrate != 19200 or args.timeout_s != 1.0 or args.active_fault_clear_reply is not None
    ):
        parser.error("serial connection settings require --port")
    try:
        laser = (
            VerdiController(
                args.serial_port,
                model=args.model,
                baudrate=args.baudrate,
                timeout_s=args.timeout_s,
                active_fault_clear_reply=args.active_fault_clear_reply,
            )
            if args.serial_port is not None
            else SimulatedVerdi(args.model or "V5")
        )
        # Validate client settings and dependencies before opening a physical port.
        if args.command in ("watch", "gui"):
            from .gui import Monitor, create_app

            if args.command == "watch" and not 1 <= args.count <= 100000:
                raise ValueError("count must be in [1, 100000]")
            monitor = Monitor(laser, interval_s=args.interval if args.command == "watch" else 1.0)
            if args.command == "gui":
                if not 1 <= args.http_port <= 65535:
                    raise ValueError("HTTP port must be in [1, 65535]")
                app = create_app(monitor)
        with laser:
            if args.command == "commission":
                for query in args.query or ["?SV"]:
                    try:
                        laser.capture(query)
                    finally:
                        if record := laser.last_transaction:
                            _print_transaction(record)
                return 0
            if args.command in ("status", "diagnostics", "query"):
                result = (
                    laser.status()
                    if args.command == "status"
                    else laser.read_diagnostics()
                    if args.command == "diagnostics"
                    else laser.read(args.query)
                )
                print(json.dumps(result, indent=2, allow_nan=False))
                return 0

            if args.command == "watch":
                failed = False
                for i in range(args.count):
                    sample = monitor.poll_once()
                    failed |= sample["status"] is None
                    print(json.dumps(sample, allow_nan=False), flush=True)
                    if i + 1 < args.count:
                        sleep(monitor.interval_s)
                return 2 if failed else 0

            from threading import Event, Thread

            stop = Event()

            def poll() -> None:
                while not stop.is_set():
                    monitor.poll_once()
                    stop.wait(monitor.interval_s)

            worker = Thread(target=poll, name="verdi-monitor")
            worker.start()
            try:
                app.run(host="127.0.0.1", port=args.http_port, debug=False, use_reloader=False)
            finally:
                stop.set()
                worker.join()  # Drain acquisition before disconnect, including Ctrl+C.
        return 0
    except KeyboardInterrupt:
        return 130
    except (VerdiError, ValueError, ImportError) as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
