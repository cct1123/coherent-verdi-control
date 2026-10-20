"""Lesson 2: read operating state, power and temperatures from your Verdi.

Complete lesson 1 and the hardware setup guide first. Edit the settings below,
then run: python examples/02_read_status.py
This script reads information; it does not change any laser settings.
"""

from coherent_verdi import VerdiController, VerdiError

PORT = "<PORT>"  # The same known serial port used in lesson 1.
MODEL = "<MODEL>"  # V2, V5 or V6.
BAUDRATE = 19200  # Must match the front panel.
ACTIVE_FAULT_CLEAR_REPLY = None  # Set to the independently verified no-fault text.


def main() -> None:
    if PORT == "<PORT>" or ACTIVE_FAULT_CLEAR_REPLY is None:
        raise ValueError(
            "Fill in the connection and verified fault-clear settings; see examples/README.md."
        )
    laser = VerdiController(
        PORT,
        model=MODEL,
        baudrate=BAUDRATE,
        active_fault_clear_reply=ACTIVE_FAULT_CLEAR_REPLY,
    )
    print(f"Read-only status from {MODEL}, {PORT}, {BAUDRATE} baud.")
    if input("Verify the settings and type CONNECT: ").strip() != "CONNECT":
        print("Cancelled. No connection was opened.")
        return

    with laser:
        print(f"Software version: {laser.read('?SV')}")
        # status() performs 14 queries and returns a Python dictionary.
        status = laser.status()
        state_name = ("STANDBY", "ON", "FAULT")[status["laser_state"]]
        print(f"Laser: {state_name}")
        print(f"Key ON: {status['keyswitch_on']}; shutter open: {status['shutter_open']}")
        print(f"Power setpoint: {status['set_power_w']:.4f} W")
        print(f"Reported power: {status['power_w']:.3f} W")
        print(f"Diode current: {status['diode_current_a']:.2f} A")
        for label, field in (
            ("Diode", "diode_temp_c"),
            ("LBO", "lbo_temp_c"),
            ("Etalon", "etalon_temp_c"),
            ("Vanadate", "vanadate_temp_c"),
        ):
            print(f"{label} temperature: {status[field]:.2f} degC")
        print(f"Active fault codes: {status['faults']}")
        if status["faults"]:
            print("Diagnose these faults with lesson 3 before changing settings.")

    print("Compare these readings with the front panel. Port released; laser state unchanged.")


if __name__ == "__main__":
    try:
        main()
    except (VerdiError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}")
        print("Readings may be incomplete. No retry or reset was requested.")
        raise SystemExit(1) from None
