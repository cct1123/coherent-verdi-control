"""Tutorial 2: set and read back a bounded setpoint while remaining in standby."""

from coherent_verdi import (
    ControllerConfig,
    LaserState,
    Model,
    Query,
    SimulatedTransport,
    VerdiController,
    VerdiError,
)


# %% Application code: target and ceiling are explicit, in watts.
def set_standby_power(laser: VerdiController, target_w: float) -> float:
    if laser.laser_state() != LaserState.STANDBY or laser.query(Query.SHUTTER) != 0:
        raise RuntimeError("Require STANDBY and a closed shutter before changing the setpoint.")
    if laser.faults():
        raise RuntimeError("Active faults require diagnosis before changing settings.")
    laser.set_power_w(target_w)  # Validates finite value, ceiling and rounded wire value.
    readback = float(laser.query(Query.SET_POWER))  # ?SP, not the measured-power query ?P.
    expected = float(f"{target_w:.4f}")
    if readback != expected:
        raise RuntimeError(f"Setpoint mismatch: requested {expected:.4f} W, read {readback} W.")
    if laser.laser_state() != LaserState.STANDBY or laser.query(Query.SHUTTER) != 0:
        raise RuntimeError("State changed unexpectedly; stop and verify with the operator.")
    print(f"Verified setpoint: {readback:.4f} W; STANDBY; shutter closed.")
    print(f"Reported power: {laser.power_w():.3f} W (separate from the setpoint).")
    return readback


# %% Simulator-only entry point; these numbers are exercises, not safe hardware limits.
def main() -> None:
    sim = SimulatedTransport(Model.V5)
    config = ControllerConfig(Model.V5, allow_writes=True, power_limit_w=0.5)
    try:
        with VerdiController(sim, config) as laser:
            set_standby_power(laser, 0.25)
            try:
                laser.set_power_w(0.6)  # Above this exercise's 0.5 W software ceiling.
            except ValueError as exc:
                print(f"Expected rejection before transmission: {exc}")
            print(f"Setpoint after rejection: {laser.query(Query.SET_POWER):.4f} W")
            set_standby_power(laser, 0.0)  # Explicit normal completion, not implicit close.
    except (VerdiError, ValueError, RuntimeError) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}. No retry or further state changes.")
        raise
    print("Connection released; no enable or shutter-open command was sent.")


if __name__ == "__main__":
    main()
