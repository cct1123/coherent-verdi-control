"""Four Verdi lessons: simulator demos and explicitly approved human hardware sessions."""

import argparse
from collections.abc import Iterator
from contextlib import contextmanager

from coherent_verdi import (
    Fault,
    LaserState,
    Model,
    ProtocolError,
    Query,
    ServoState,
    SimulatedTransport,
    Status,
    TransportError,
    VerdiController,
    VerdiError,
)


# %% Read-only application code: accepts an already prepared controller.
def read_status(laser: VerdiController) -> Status:
    version = laser.read(Query.SOFTWARE)  # ?SV: query, not model discovery.
    status = laser.status()  # Fourteen sequential queries, not one atomic reading.
    diagnostics = laser.read_diagnostics()
    source = "SIMULATOR" if status.simulated else "HARDWARE"
    print(f"Source: {source}; configured model: {status.model}; software: {version}")
    print(
        f"State: {status.laser_state.name}; key ON: {status.keyswitch_on}; "
        f"shutter open: {status.shutter_open}"
    )
    print(f"Setpoint: {status.set_power_w:.4f} W; reported power: {status.power_w:.3f} W")
    print(f"LBO: {status.lbo_temp_c:.2f} degC / {status.lbo_servo.name}")
    print(f"Head operating hours: {diagnostics.head_hours:.1f} h")
    print(f"Active faults: {status.faults}; history: {diagnostics.fault_history}")
    if status.faults:
        print("STOP: active faults need diagnosis; this tutorial never resets or enables.")
    return status


# %% Simulator-only entry point; run again to create a fresh fixture.
def simulate_read_status() -> None:
    sim = SimulatedTransport(Model.V5)
    try:
        with VerdiController(sim, model=Model.V5) as laser:
            read_status(laser)
            try:
                laser.set_power_w(0.25)
            except PermissionError:
                print("Expected PermissionError: the attempted write sent no command.")
    except VerdiError as exc:
        print(f"STOP: {type(exc).__name__}: {exc}. No retry; readings are incomplete.")
        raise
    print("Connection released; disconnect() sends no laser commands.")


# %% Application code: target and ceiling are explicit, in watts.
def set_standby_power(laser: VerdiController, target_w: float) -> float:
    if laser.read_laser_state() != LaserState.STANDBY or laser.read(Query.SHUTTER) != 0:
        raise RuntimeError("Require STANDBY and a closed shutter before changing the setpoint.")
    if laser.read_faults():
        raise RuntimeError("Active faults require diagnosis before changing settings.")
    laser.set_power_w(target_w)  # Validates finite value, ceiling and rounded wire value.
    readback = float(laser.read(Query.SET_POWER))  # ?SP, not the measured-power query ?P.
    expected = float(f"{target_w:.4f}")
    if readback != expected:
        raise RuntimeError(f"Setpoint mismatch: requested {expected:.4f} W, read {readback} W.")
    if laser.read_laser_state() != LaserState.STANDBY or laser.read(Query.SHUTTER) != 0:
        raise RuntimeError("State changed unexpectedly; stop and verify with the operator.")
    print(f"Verified setpoint: {readback:.4f} W; STANDBY; shutter closed.")
    print(f"Reported power: {laser.read_power_w():.3f} W (separate from the setpoint).")
    return readback


# %% Simulator-only entry point; these numbers are exercises, not safe hardware limits.
def simulate_set_power() -> None:
    sim = SimulatedTransport(Model.V5)
    try:
        with VerdiController(sim, allow_writes=True, power_limit_w=0.5) as laser:
            set_standby_power(laser, 0.25)
            try:
                laser.set_power_w(0.6)  # Above this exercise's 0.5 W software ceiling.
            except ValueError as exc:
                print(f"Expected rejection before transmission: {exc}")
            print(f"Setpoint after rejection: {laser.read(Query.SET_POWER):.4f} W")
            set_standby_power(laser, 0.0)  # Explicit normal completion, not implicit close.
    except (VerdiError, ValueError, RuntimeError) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}. No retry or further state changes.")
        raise
    print("Connection released; no enable or shutter-open command was sent.")


# %% Check the starting state before any writes.
def check_ready(laser: VerdiController) -> None:
    before = laser.status()
    if before.laser_state != LaserState.STANDBY or before.shutter_open:
        raise RuntimeError("Start from operator-confirmed STANDBY with shutter closed.")
    if not before.keyswitch_on or before.lbo_servo != ServoState.LOCKED or before.faults:
        raise RuntimeError("Require key ON, LBO LOCKED and no active faults; do not auto-enable.")
    for query in (Query.DIODE_SERVO, Query.ETALON_SERVO, Query.VANADATE_SERVO):
        if laser.read(query) != ServoState.LOCKED:
            raise RuntimeError(f"Require all temperature servos LOCKED; {query} is not ready.")
    print(f"Fault history before enable: {laser.read_faults(history=True)}")


# %% Set power and enable while retaining a closed shutter.
def enable_at_power(laser: VerdiController, target_w: float) -> None:
    laser.set_power_w(target_w)
    if laser.read(Query.SET_POWER) != float(f"{target_w:.4f}"):
        raise RuntimeError("Setpoint readback mismatch; enable was not requested.")
    laser.start()  # L=1 also resets faults and clears their history.
    if laser.read_laser_state() != LaserState.ON or laser.read_faults():
        raise RuntimeError("Enable did not produce ON without faults.")
    if laser.read(Query.SHUTTER) != 0:
        raise RuntimeError("Shutter unexpectedly open after enable.")
    print("Laser ON; shutter still closed.")


# %% Open the safety shutter once and take one immediate reading.
def sample_with_shutter_open(laser: VerdiController) -> float:
    laser.set_shutter(open=True)
    if laser.read(Query.SHUTTER) != 1 or laser.read_faults():
        raise RuntimeError("Open-shutter state was not verified without faults.")
    power_w = laser.read_power_w()
    print(f"Shutter open; reported power: {power_w:.3f} W")
    return power_w


# %% Normal completion must be commanded and verified, not inferred from disconnect().
def close_and_standby(laser: VerdiController) -> None:
    laser.set_shutter(open=False)
    if laser.read(Query.SHUTTER) != 0:
        raise RuntimeError("Shutter closure was not confirmed.")
    laser.stop()
    if laser.read_laser_state() != LaserState.STANDBY:
        raise RuntimeError("STANDBY was not confirmed.")
    print("Shutter closed; STANDBY confirmed. Setpoint retained for inspection.")


# %% Keep the approved sequence together; a failed step stops subsequent commands.
def controlled_session(laser: VerdiController, target_w: float) -> float:
    try:
        check_ready(laser)
        enable_at_power(laser, target_w)
        power_w = sample_with_shutter_open(laser)
        close_and_standby(laser)
        return power_w
    except BaseException:
        # Also covers Ctrl+C. A lost reply may mean the command already executed.
        print("STOP: state may be unknown. No retries or blind cleanup commands.")
        print("Use the physical abort procedure; disconnect() is not laser shutdown.")
        raise


# %% Simulator-only setup. set_key is a fixture operation, never an RS-232 command.
def simulate_controlled_session() -> None:
    sim = SimulatedTransport(Model.V5)  # Warm by default; no artificial warmup wait.
    sim.set_key(True)
    with VerdiController(sim, allow_writes=True, power_limit_w=0.5) as laser:
        controlled_session(laser, 0.25)
    print("Connection released after the verified normal-completion sequence.")


# %% Application code: diagnosis reads do not clear faults or restart the laser.
def read_fault_report(laser: VerdiController) -> tuple[tuple[Fault, ...], tuple[Fault, ...]]:
    state = laser.read_laser_state()  # ?L
    active = laser.read_faults()  # ?F
    history = laser.read_faults(history=True)  # ?FH
    print(f"Laser state: {state.name}")
    for label, faults in (("Active", active), ("History", history)):
        print(f"{label} fault codes: {[fault.code for fault in faults]}")
        for fault in faults:
            print(f"  {fault.code}: {fault.description}; known={fault.known}")
    if active:
        print("STOP: diagnose every active code, including unknown codes. No automatic reset.")
    return active, history


def set_power_once(laser: VerdiController, target_w: float) -> bool:
    """One attempted write in an already approved state; caller closes on False."""
    try:
        laser.set_power_w(target_w)
    except (TransportError, ProtocolError) as exc:
        print(f"{type(exc).__name__}: {exc}")
        print("Outcome UNKNOWN: the setpoint may have changed. Do not retry or continue querying.")
        return False
    return True  # Acknowledged only; this alone is not state or optical verification.


# %% First simulator exercise: inspect and retain fault evidence.
def demonstrate_faults() -> None:
    sim = SimulatedTransport(Model.V5)
    sim.set_faults(2, 999)  # External interlock plus an intentionally unknown fixture code.
    try:
        with VerdiController(sim, model=Model.V5) as laser:
            read_fault_report(laser)
            sim.set_faults()  # Remove synthetic active conditions; NOT a real reset command.
            print("\nFixture conditions removed; read again without enabling:")
            read_fault_report(laser)
    except VerdiError as exc:
        print(f"STOP: incomplete fault report: {exc}. Preserve evidence; no retry.")
        raise


# %% Second simulator exercise: a write can execute before its reply is lost.
def demonstrate_lost_reply() -> None:
    sim = SimulatedTransport(Model.V5)
    with VerdiController(sim, allow_writes=True, power_limit_w=0.5) as laser:
        sim.inject_timeout(after_apply=True)  # Fake applies P, then drops its acknowledgment.
        if not set_power_once(laser, 0.25):
            print("Ending this session now. No reconnect, state replay or enable.")
    print(f"Simulator wire requests: {sim.requests!r}")
    print("Connection released. Communication close did not undo the attempted setpoint.")


# %% Run the two independent simulator exercises.
def simulate_handle_faults() -> None:
    demonstrate_faults()
    demonstrate_lost_reply()


# Each lesson has a controller operation and a separate simulator demonstration.
LESSONS = {
    "read-status": (read_status, simulate_read_status),
    "set-power": (set_standby_power, simulate_set_power),
    "controlled-session": (controlled_session, simulate_controlled_session),
    "faults": (read_fault_report, simulate_handle_faults),
}
WRITE_LESSONS = {"set-power", "controlled-session"}


def validate_power(
    model: Model, target_w: float | None, power_limit_w: float | None, *, allow_writes: bool
) -> None:
    """Require site values before a physical write; simulator defaults are not limits."""
    if not allow_writes:
        if target_w is not None or power_limit_w is not None:
            raise ValueError("Read-only lessons do not accept power settings")
        return
    if (
        isinstance(power_limit_w, bool)
        or not isinstance(power_limit_w, (int, float))
        or not 0 <= power_limit_w <= model.rated_power_w
    ):
        raise ValueError("Supply the approved power_limit_w within the model rating")
    if (
        isinstance(target_w, bool)
        or not isinstance(target_w, (int, float))
        or not 0 <= target_w <= power_limit_w
        or float(f"{target_w:.4f}") > power_limit_w
    ):
        raise ValueError("target_w must be finite, nonnegative and within the approved ceiling")


@contextmanager
def hardware_connection(laser: VerdiController) -> Iterator[VerdiController | None]:
    """Operator confirmation, passive connect, one ?SV, and deterministic disconnect."""
    if input("With candidate/connection approval recorded, type CONNECT: ").strip() != "CONNECT":
        print("Cancelled before opening the port.")
        yield None
        return
    try:
        with laser:
            print(f"Reported software: {laser.read(Query.SOFTWARE)}")
            yield laser
    except BaseException:
        print("STOP: state may be unknown. No retries or blind cleanup writes.")
        print("Use the operator's approved physical abort procedure.")
        raise
    finally:
        print("Connection released; disconnect does not shut down the laser.")


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
    active_fault_clear_reply: str | None = None,
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
    model = Model(model)
    validate_power(model, target_w, power_limit_w, allow_writes=writes)
    controller = VerdiController(
        port,
        model=model,
        baudrate=baudrate,
        timeout_s=timeout_s,
        allow_writes=writes,
        power_limit_w=power_limit_w,
        active_fault_clear_reply=active_fault_clear_reply,
    )
    print(f"HARDWARE: {model}, port={port}, baud={baudrate}; timeout={timeout_s} s.")
    print("First interaction: ?SV only.")
    operation, _ = LESSONS[lesson]
    with hardware_connection(controller) as laser:
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
            operation(laser, target_w)
        else:
            operation(laser)
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
    parser.add_argument(
        "--active-fault-clear-reply",
        help="Exact ?F clear text verified for this firmware in Stage 1",
    )
    args = parser.parse_args(argv)
    if not args.hardware:
        hardware_settings = (
            args.port,
            args.model,
            args.baudrate,
            args.timeout_s,
            args.target_w,
            args.power_limit_w,
            args.active_fault_clear_reply,
        )
        if any(value is not None for value in hardware_settings) or args.identify_only:
            parser.error(
                "Hardware settings require --hardware; simulator lessons use their fixtures"
            )
        print("SIMULATOR: running the lesson; no physical connection.")
        _, demonstrate = LESSONS[args.lesson]
        demonstrate()
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
            active_fault_clear_reply=args.active_fault_clear_reply,
        )
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
