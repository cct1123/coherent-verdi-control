"""Lesson 4: change the power setpoint while remaining in standby.

Edit the connection settings, verified fault-clear text and site-approved watts.
Run: python examples/04_set_power.py
The script never enables the laser or opens the shutter. The new setpoint remains stored.
"""

from coherent_verdi import VerdiController, VerdiError

PORT = "<PORT>"
MODEL = "<MODEL>"  # V2, V5 or V6.
BAUDRATE = 19200
ACTIVE_FAULT_CLEAR_REPLY = None
TARGET_W = None  # Enter the desired setpoint in watts; obtain it from the operator.
POWER_LIMIT_W = None  # Enter the site's approved ceiling, not simply the laser rating.


def main() -> None:
    if PORT == "<PORT>" or ACTIVE_FAULT_CLEAR_REPLY is None or POWER_LIMIT_W is None:
        raise ValueError(
            "Fill in the connection, fault-clear text and approved power settings first."
        )
    laser = VerdiController(
        PORT,
        model=MODEL,
        baudrate=BAUDRATE,
        allow_writes=True,
        power_limit_w=POWER_LIMIT_W,
        active_fault_clear_reply=ACTIVE_FAULT_CLEAR_REPLY,
    )
    # Validate the target before opening the port, including four-decimal rounding.
    if (
        type(TARGET_W) not in (int, float)
        or not 0 <= TARGET_W <= POWER_LIMIT_W
        or float(f"{TARGET_W:.4f}") > POWER_LIMIT_W
    ):
        raise ValueError("TARGET_W must be a finite number within POWER_LIMIT_W after rounding.")
    print(f"{MODEL}, {PORT}, {BAUDRATE} baud; target {TARGET_W:.4f} W; ceiling {POWER_LIMIT_W} W.")
    if input("Verify the settings and safe setup, then type CONNECT: ").strip() != "CONNECT":
        print("Cancelled. No connection was opened.")
        return

    with laser:
        print(f"Software version: {laser.read('?SV')}")
        print("Plan: check standby/shutter/faults, then store and verify the new setpoint.")
        if input("To store this new setpoint, type SET: ").strip() != "SET":
            print("Cancelled. No settings were changed.")
            return

        # Step 1: check AFTER confirmation so an operator wait cannot stale the checks.
        before = laser.status()
        if before["laser_state"] != 0 or before["shutter_open"] or before["faults"]:
            raise RuntimeError("Require STANDBY, shutter closed and no active faults.")
        print(f"Previous setpoint: {before['set_power_w']:.4f} W; new setpoint: {TARGET_W:.4f} W.")

        # Step 2: P changes the requested power; ?SP reads that request back.
        laser.set_power_w(TARGET_W)
        readback = laser.read("?SP")
        if readback != float(f"{TARGET_W:.4f}"):
            raise RuntimeError(f"Setpoint readback mismatch: received {readback} W.")
        if laser.read_laser_state() != 0 or laser.read("?S") != 0 or laser.read_faults():
            raise RuntimeError("State or faults changed unexpectedly after the write.")
        print(f"Verified setpoint: {readback:.4f} W; still in standby with shutter closed.")
        print("This is a stored request, not a measurement of emitted optical power.")

    print("Port released. Setpoint retained; no enable or shutter-open command was sent.")


if __name__ == "__main__":
    try:
        main()
    except (VerdiError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}")
        print("A write may have executed. Use the physical abort plan; do not retry.")
        raise SystemExit(1) from None
