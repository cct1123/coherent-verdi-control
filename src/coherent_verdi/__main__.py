"""Verdi CLI. Supply --port and --model for hardware; otherwise simulate.

Reads are the default; the command subcommand requires --allow-writes.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from threading import Event
from typing import Any

from .controller import (
    VerdiController,
    VerdiError,
    json_ready,
    normalize_query,
    transaction_evidence,
)
from .simulator import SimulatedVerdi


def _print_transaction(record: dict[str, Any]) -> None:
    """JSONL preserves exact wire bytes as hex."""
    print(json.dumps(transaction_evidence(record), allow_nan=False), flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", dest="serial_port", help="Serial port before the subcommand, e.g. COM3"
    )
    parser.add_argument("--model", choices=["V2", "V5", "V6"], help="Required for hardware")
    parser.add_argument("--baudrate", type=int, default=19200, help="Match the front-panel baud")
    parser.add_argument("--timeout-s", type=float, default=1.0)
    parser.add_argument("--active-fault-clear-reply", help="Independently verified ?F clear text")
    parser.add_argument("--no-prompt", action="store_true", help="Device prompt is disabled")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "diagnostics"):
        commands.add_parser(name)
    commands.add_parser("query").add_argument("query", type=normalize_query)
    command = commands.add_parser("command", help="Execute one documented write, explicitly")
    command.add_argument("instruction", help='One canonical setting, e.g. "LBOH=1"')
    command.add_argument("--allow-writes", action="store_true", help="Required to enable writes")
    command.add_argument("--power-limit-w", type=float, help="Site ceiling for power writes")
    commission = commands.add_parser(
        "commission", help="Read-only raw query capture; no interpretation"
    )
    commission.add_argument(
        "--query",
        action="append",
        type=normalize_query,
        help="Repeat for each exact query; default: one ?SV",
    )
    watch = commands.add_parser("watch")
    watch.add_argument("--count", type=int, default=10)
    watch.add_argument("--interval", type=float, default=1.0)
    gui = commands.add_parser("gui", help="Disconnected dashboard; connect and monitor explicitly")
    gui.add_argument(
        "--port", dest="http_port", type=int, default=8050, help="HTTP port (default: 8050)"
    )
    gui.add_argument("--allow-writes", action="store_true", help="Enable GUI control actions")
    gui.add_argument("--power-limit-w", type=float, help="Site ceiling for GUI power writes")
    args = parser.parse_args(argv)
    if args.serial_port is not None and args.model is None:
        parser.error("--port requires --model V2, V5 or V6; the model is not discovered")
    if args.command == "commission" and args.serial_port is None:
        parser.error("commission requires an explicit --port and --model")
    if args.command == "command" and not args.allow_writes:
        parser.error("command requires --allow-writes explicitly")
    if (
        args.command != "gui"
        and args.serial_port is None
        and (
            args.baudrate != 19200
            or args.timeout_s != 1.0
            or args.active_fault_clear_reply is not None
        )
    ):
        parser.error("serial connection settings require --port")
    try:
        write_options: dict[str, Any] = (
            {"allow_writes": args.allow_writes, "power_limit_w": args.power_limit_w}
            if args.command in ("command", "gui")
            else {}
        )
        if args.command == "gui":
            from .gui import GuiSession, create_app, run_gui

            if not 1 <= args.http_port <= 65535:
                raise ValueError("HTTP port must be in [1, 65535]")
            session = GuiSession(
                port=args.serial_port,
                model=args.model or "V5",
                baudrate=args.baudrate,
                timeout_s=args.timeout_s,
                clear_reply=args.active_fault_clear_reply,
                prompt_enabled=not args.no_prompt,
                **write_options,
            )
            app = create_app(session.monitor, session=session)
            run_gui(session, app, args.http_port)
            return 0
        laser = (
            VerdiController(
                args.serial_port,
                model=args.model,
                baudrate=args.baudrate,
                timeout_s=args.timeout_s,
                active_fault_clear_reply=args.active_fault_clear_reply,
                prompt_enabled=not args.no_prompt,
                **write_options,
            )
            if args.serial_port is not None
            else SimulatedVerdi(args.model or "V5", **write_options)
        )
        # Validate client settings and dependencies before opening a physical port.
        if args.command == "watch":
            from .monitor import Monitor

            if not 1 <= args.count <= 100000:
                raise ValueError("count must be in [1, 100000]")
            monitor = Monitor(laser, interval_s=args.interval)
        with laser:
            if args.command == "command":
                try:
                    laser.set_value(args.instruction)
                finally:
                    if record := laser.last_transaction:
                        _print_transaction(record)
                return 0
            if args.command == "commission":
                for query in args.query or ["?SV"]:
                    try:
                        laser.get_capture(query)
                    finally:
                        if record := laser.last_transaction:
                            _print_transaction(record)
                return 0
            if args.command in ("status", "diagnostics", "query"):
                result = (
                    laser.get_status()
                    if args.command == "status"
                    else laser.get_diagnostics()
                    if args.command == "diagnostics"
                    else laser.get_value(args.query)
                )
                print(json.dumps(json_ready(result), indent=2, allow_nan=False))
                return 0

            if args.command == "watch":
                failed = False
                stop = Event()
                for i in range(args.count):
                    sample = monitor.poll_once()
                    failed |= sample["status"] is None
                    print(json.dumps(sample, allow_nan=False), flush=True)
                    if i + 1 < args.count:
                        monitor.wait(stop)
                return 2 if failed else 0

        return 0
    except KeyboardInterrupt:
        return 130
    except (VerdiError, ValueError, ImportError) as exc:
        print(json.dumps({"error": str(exc), "type": type(exc).__name__}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
