"""Lesson 5: set power, enable, open the safety shutter once, then return to standby.

This example can produce a laser beam. Use an attended, site-approved setup.
Edit all settings, then run: python examples/05_controlled_session.py
Complete warmup and the operator's beam/cooling/interlock checks before running.
"""

from coherent_verdi import VerdiController, VerdiError

PORT = "<PORT>"
MODEL = "<MODEL>"  # V2, V5 or V6.
BAUDRATE = 19200
ACTIVE_FAULT_CLEAR_REPLY = None
TARGET_W = None  # Site-approved target in watts. No default is safe for every setup.
POWER_LIMIT_W = None  # Site-approved maximum for this session, in watts.


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
        print("Plan: set power, enable, open shutter once, read power, close shutter, standby.")
        print(
            "Confirm the beam path, cooling, interlocks and physical abort plan with the operator."
        )
        if input("To perform this emission sequence, type RUN: ").strip() != "RUN":
            print("Cancelled. No settings were changed.")
            return

        # Step 1: check AFTER confirmation; no keyboard waits follow these checks.
        # These observations do not replace physical safeguards.
        before = laser.status()
        if before["laser_state"] != 0 or before["shutter_open"] or before["faults"]:
            raise RuntimeError("Require STANDBY, shutter closed and no active faults.")
        if not before["keyswitch_on"]:
            raise RuntimeError("Require the operator's established key-ON / standby configuration.")
        for query in ("?D1SS", "?LBOSS", "?ESS", "?VSS"):
            if laser.read(query) != 1:  # Manual servo code 1 means LOCKED.
                raise RuntimeError(f"Temperature servo {query} is not LOCKED; do not enable.")
        # L=1 clears fault history, so display it before any enable command.
        print(f"Fault history before enable: {laser.read_faults(history=True)}")

        # Step 2: store and verify the setpoint while the shutter is still closed.
        laser.set_power_w(TARGET_W)
        if laser.read("?SP") != float(f"{TARGET_W:.4f}"):
            raise RuntimeError("Setpoint readback mismatch; enable was not requested.")
        laser.start()  # L=1: enable AND reset faults/history. Never repeat as recovery.
        if laser.read_laser_state() != 1 or laser.read_faults() or laser.read("?S") != 0:
            raise RuntimeError("ON with no faults and a closed shutter was not confirmed.")

        # Step 3: one safety-shutter opening, with no interactive wait while open.
        laser.set_shutter(open=True)
        if laser.read("?S") != 1 or laser.read_faults():
            raise RuntimeError("Open shutter without faults was not confirmed.")
        power_w = laser.read_power_w()  # One immediate reading; not a settling test.

        # Step 4: normal completion is explicit and verified.
        laser.set_shutter(open=False)
        if laser.read("?S") != 0:
            raise RuntimeError("Shutter closure was not confirmed.")
        laser.stop()  # L=0: standby; temperature servos remain powered.
        if laser.read_laser_state() != 0:
            raise RuntimeError("Standby was not confirmed.")
        print(f"Immediate reported power while open: {power_w:.3f} W (not a calibration).")
        print("Shutter closed and STANDBY confirmed. The power setpoint remains stored.")

    print("Port released. Complete heater/cooling shutdown separately using the manual.")


if __name__ == "__main__":
    try:
        main()
    except (VerdiError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}")
        print(
            "Laser state may be unknown. Use the physical abort plan; disconnect is not shutdown."
        )
        print("No retries, re-enable or blind cleanup commands are sent after a failed step.")
        raise SystemExit(1) from None
