"""Tutorial 3: one explicit enable, safety-shutter opening, closure and standby."""

from coherent_verdi import (
    ControllerConfig,
    LaserState,
    Model,
    Query,
    ServoState,
    SimulatedTransport,
    VerdiController,
)


# %% Check the starting state before any writes.
def check_ready(laser: VerdiController) -> None:
    before = laser.status()
    if before.laser_state != LaserState.STANDBY or before.shutter_open:
        raise RuntimeError("Start from operator-confirmed STANDBY with shutter closed.")
    if not before.keyswitch_on or before.lbo_servo != ServoState.LOCKED or before.faults:
        raise RuntimeError("Require key ON, LBO LOCKED and no active faults; do not auto-enable.")
    print(f"Fault history before enable: {laser.faults(history=True)}")


# %% Set power and enable while retaining a closed shutter.
def enable_at_power(laser: VerdiController, target_w: float) -> None:
    laser.set_power_w(target_w)
    if laser.query(Query.SET_POWER) != float(f"{target_w:.4f}"):
        raise RuntimeError("Setpoint readback mismatch; enable was not requested.")
    laser.enable_laser()  # L=1 also resets faults and clears their history.
    if laser.laser_state() != LaserState.ON or laser.faults():
        raise RuntimeError("Enable did not produce ON without faults.")
    if laser.query(Query.SHUTTER) != 0:
        raise RuntimeError("Shutter unexpectedly open after enable.")
    print("Laser ON; shutter still closed.")


# %% Open the safety shutter once and take one immediate reading.
def sample_with_shutter_open(laser: VerdiController) -> float:
    laser.set_shutter(open=True)
    if laser.query(Query.SHUTTER) != 1 or laser.faults():
        raise RuntimeError("Open-shutter state was not verified without faults.")
    power_w = laser.power_w()
    print(f"Shutter open; reported power: {power_w:.3f} W")
    return power_w


# %% Normal completion must be commanded and verified, not inferred from close().
def close_and_standby(laser: VerdiController) -> None:
    laser.set_shutter(open=False)
    if laser.query(Query.SHUTTER) != 0:
        raise RuntimeError("Shutter closure was not confirmed.")
    laser.standby()
    if laser.laser_state() != LaserState.STANDBY:
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
        print("On hardware, use the operator's physical abort procedure; close() is not shutdown.")
        raise


# %% Simulator-only setup. set_key is a fixture operation, never an RS-232 command.
def main() -> None:
    sim = SimulatedTransport(Model.V5)  # Warm by default; no artificial warmup wait.
    sim.set_key(True)
    config = ControllerConfig(Model.V5, allow_writes=True, power_limit_w=0.5)
    with VerdiController(sim, config) as laser:
        controlled_session(laser, 0.25)
    print("Connection released after the verified normal-completion sequence.")


if __name__ == "__main__":
    main()
