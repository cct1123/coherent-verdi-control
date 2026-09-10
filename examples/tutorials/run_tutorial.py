"""Run a simulator lesson, or an explicitly configured human-operated hardware session."""

import argparse
import runpy
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from coherent_verdi import (
    ControllerConfig,
    Model,
    Query,
    SerialConfig,
    VerdiController,
    open_serial,
)

LESSONS = {
    "read-status": ("read_status", "read_status"),
    "set-power": ("set_power", "set_standby_power"),
    "controlled-session": ("controlled_session", "controlled_session"),
    "faults": ("handle_faults", "read_fault_report"),
}
WRITE_LESSONS = {"set-power", "controlled-session"}


def hardware_power_config(
    model: Model,
    *,
    allow_writes: bool = False,
    target_w: float | None = None,
    power_limit_w: float | None = None,
) -> ControllerConfig:
    """Validate explicit hardware power settings before opening a connection."""
    config = ControllerConfig(model, allow_writes=allow_writes, power_limit_w=power_limit_w)
    if allow_writes:
        if power_limit_w is None:
            raise ValueError("Supply the approved power_limit_w; there is no hardware default")
        if (
            isinstance(target_w, bool)
            or not isinstance(target_w, (int, float))
            or not 0 <= target_w <= config.effective_power_limit_w
            or float(f"{target_w:.4f}") > config.effective_power_limit_w
        ):
            raise ValueError("target_w must be finite, nonnegative and within the approved ceiling")
    elif target_w is not None or power_limit_w is not None:
        raise ValueError("Read-only lessons do not accept power settings")
    return config


@contextmanager
def hardware_connection(
    serial_config: SerialConfig,
    config: ControllerConfig,
) -> Iterator[VerdiController | None]:
    """Ask CONNECT, read ?SV first, and release the connection on leaving the block."""
    print(f"HARDWARE: {config.model}, port={serial_config.port}, baud={serial_config.baudrate}")
    print(f"Timeout: {serial_config.timeout_s} s. First interaction: ?SV only.")
    if input("With candidate/connection approval recorded, type CONNECT: ").strip() != "CONNECT":
        print("Cancelled before opening the port.")
        yield None
        return
    try:
        with VerdiController(open_serial(serial_config, hardware_allowed=True), config) as laser:
            print(f"Reported software: {laser.query(Query.SOFTWARE)}")
            yield laser
    except BaseException:
        print("STOP: session failed/interrupted. No reconnect, retries or blind cleanup writes.")
        print("Physical state may be unknown. Use the operator's approved abort procedure.")
        raise
    finally:
        print("Communication scope ended; releasing a connection does not shut down the laser.")


def run_hardware(
    lesson: str,
    *,
    port: str,
    model: Model,
    baudrate: int,
    timeout_s: float = 1.0,
    target_w: float | None = None,
    power_limit_w: float | None = None,
    identify_only: bool = False,
) -> bool:
    """Human entry point. False means cancelled; exceptions mean STOP, never retry.

    Complete the project's hardware review procedure before using this function.
    Prompts confirm an operator's intended actions; they do not supply site approval.
    Configuration is validated before opening. No fallback to simulation is made.
    """
    if lesson not in LESSONS:
        raise ValueError(f"Choose a lesson from {tuple(LESSONS)}")
    if identify_only and lesson != "read-status":
        raise ValueError("identify_only is available only for read-status")
    writes = lesson in WRITE_LESSONS
    serial_config = SerialConfig(port, baudrate=baudrate, timeout_s=timeout_s)
    config = hardware_power_config(
        model, allow_writes=writes, target_w=target_w, power_limit_w=power_limit_w
    )

    script, function = LESSONS[lesson]
    # Loading definitions does not run the script's simulator main().
    namespace = runpy.run_path(str(Path(__file__).with_name(f"{script}.py")))
    with hardware_connection(serial_config, config) as laser:
        if laser is None:
            return False
        if identify_only:
            print("Identification query complete. No further queries or writes requested.")
            return True
        if writes:
            print(f"Requested setpoint {target_w:.4f} W; ceiling {power_limit_w} W.")
            if lesson == "controlled-session":
                print("Plan: verify readiness/history, set power, enable, open shutter ONCE,")
                print("read power once, close shutter and enter STANDBY with readbacks.")
                print("L=1 clears fault history. The setpoint remains stored after STANDBY.")
            else:
                print("Plan: require STANDBY/closed shutter/no faults, set power and verify.")
                print("The requested setpoint remains stored. No enable or shutter opening.")
            print("Confirm the approved beam conditions, limits and physical abort procedure.")
        else:
            print(f"Plan: {lesson} queries with writes disabled. No injected faults or resets.")
        if input("Verify the device/version and approved scope, then type RUN: ").strip() != "RUN":
            print("Cancelled after ?SV; no lesson commands sent.")
            return False
        if writes:
            namespace[function](laser, target_w)
        else:
            namespace[function](laser)
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("lesson", choices=LESSONS, nargs="?", default="read-status")
    parser.add_argument(
        "--hardware", action="store_true", help="Explicit human-operated serial mode"
    )
    parser.add_argument("--port", help="Operator-verified native port; never discovered")
    parser.add_argument("--model", choices=[model.value for model in Model])
    parser.add_argument("--baudrate", type=int, help="Must match the front-panel setting")
    parser.add_argument(
        "--timeout-s", type=float, help="Hardware transaction deadline (default: 1 s)"
    )
    parser.add_argument(
        "--target-w", type=float, help="Operator-approved target, required for writes"
    )
    parser.add_argument(
        "--power-limit-w", type=float, help="Approved site ceiling, required for writes"
    )
    parser.add_argument("--identify-only", action="store_true", help="read-status: stop after ?SV")
    args = parser.parse_args(argv)
    if not args.hardware:
        hardware_settings = (
            args.port,
            args.model,
            args.baudrate,
            args.timeout_s,
            args.target_w,
            args.power_limit_w,
        )
        if any(value is not None for value in hardware_settings) or args.identify_only:
            parser.error(
                "Hardware settings require --hardware; simulator lessons use their fixtures"
            )
        print("SIMULATOR: running the original lesson; no physical connection.")
        script = LESSONS[args.lesson][0]
        runpy.run_path(str(Path(__file__).with_name(f"{script}.py")), run_name="__main__")
        return
    if args.port is None or args.model is None or args.baudrate is None:
        parser.error("--hardware requires explicit --port, --model and --baudrate")
    try:
        run_hardware(
            args.lesson,
            port=args.port,
            model=Model(args.model),
            baudrate=args.baudrate,
            timeout_s=1.0 if args.timeout_s is None else args.timeout_s,
            target_w=args.target_w,
            power_limit_w=args.power_limit_w,
            identify_only=args.identify_only,
        )
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
