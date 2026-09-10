"""Tutorial 4: preserve fault evidence and stop after a lost acknowledgment."""

from coherent_verdi import (
    ControllerConfig,
    Fault,
    Model,
    ProtocolError,
    SimulatedTransport,
    TransportError,
    VerdiController,
    VerdiError,
)


# %% Application code: diagnosis reads do not clear faults or restart the laser.
def read_fault_report(laser: VerdiController) -> tuple[tuple[Fault, ...], tuple[Fault, ...]]:
    state = laser.laser_state()  # ?L
    active = laser.faults()  # ?F
    history = laser.faults(history=True)  # ?FH
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
        with VerdiController(sim, ControllerConfig(Model.V5)) as laser:
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
    config = ControllerConfig(Model.V5, allow_writes=True, power_limit_w=0.5)
    with VerdiController(sim, config) as laser:
        sim.inject_timeout(after_apply=True)  # Fake applies P, then drops its acknowledgment.
        if not set_power_once(laser, 0.25):
            print("Ending this session now. No reconnect, state replay or enable.")
    print(f"Simulator wire requests: {sim.requests!r}")
    print("Connection released. Communication close did not undo the attempted setpoint.")


# %% Run the two independent simulator exercises.
def main() -> None:
    demonstrate_faults()
    demonstrate_lost_reply()


if __name__ == "__main__":
    main()
