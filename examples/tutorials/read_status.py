"""Tutorial 1: read identity, status and diagnostics without changing settings."""

from coherent_verdi import (
    ControllerConfig,
    Model,
    Query,
    SimulatedTransport,
    Status,
    VerdiController,
    VerdiError,
    WritesDisabled,
)


# %% Read-only application code: accepts an already prepared controller.
def read_status(laser: VerdiController) -> Status:
    version = laser.query(Query.SOFTWARE)  # ?SV: query, not model discovery.
    status = laser.status()  # Fourteen sequential queries, not one atomic reading.
    diagnostics = laser.diagnostics()
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
def main() -> None:
    sim = SimulatedTransport(Model.V5)
    try:
        with VerdiController(sim, ControllerConfig(Model.V5)) as laser:
            read_status(laser)
            try:
                laser.set_power_w(0.25)
            except WritesDisabled:
                print("Expected WritesDisabled: the attempted write sent no command.")
    except VerdiError as exc:
        print(f"STOP: {type(exc).__name__}: {exc}. No retry; readings are incomplete.")
        raise
    print("Connection released; close() sends no laser commands.")


if __name__ == "__main__":
    main()
