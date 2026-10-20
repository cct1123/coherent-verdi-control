"""Lesson 3: inspect active faults and their history without resetting them.

Edit the settings, then run: python examples/03_read_faults.py
Use this example when diagnosing a problem. It never enables or resets the laser.
"""

from coherent_verdi import VerdiController, VerdiError

PORT = "<PORT>"
MODEL = "<MODEL>"  # V2, V5 or V6.
BAUDRATE = 19200  # Match the front panel.
ACTIVE_FAULT_CLEAR_REPLY = None  # Independently verified text for ?F, not ?FH.


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
    print(f"Read-only fault report from {MODEL}, {PORT}, {BAUDRATE} baud.")
    if input("Verify the settings and type CONNECT: ").strip() != "CONNECT":
        print("Cancelled. No connection was opened.")
        return

    with laser:
        print(f"Software version: {laser.read('?SV')}")
        print(f"Laser state code: {laser.read_laser_state()} (0 standby, 1 on, 2 fault)")
        active = laser.read_faults()  # ?F: faults currently reported as active.
        print(f"Active faults: {active}")
        history = laser.read_faults(history=True)  # ?FH: recorded fault history.
        print(f"Fault history: {history}")

    print("[] means no faults reported in that list. Keep every code, including unknown ones.")
    print("Look up codes in docs/PROTOCOL.md and the operator manual; do not guess a reset.")
    print("start() clears fault history as well as enabling the laser. This script never calls it.")
    print("Port released. No faults were cleared and the laser was not restarted.")


if __name__ == "__main__":
    try:
        main()
    except (VerdiError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}")
        print("The fault report may be incomplete. Preserve the error; do not auto-reset.")
        raise SystemExit(1) from None
