"""Lesson 1: connect to your Verdi and read its software version.

Edit the three connection settings below, then run:
    python examples/01_connect.py
This example sends one query. It does not enable the laser or change settings.
"""

from coherent_verdi import VerdiController, VerdiError

# Step 1: copy these settings from your instrument and computer.
PORT = "<PORT>"  # For example, COM3 on Windows or /dev/ttyUSB0 on Linux.
MODEL = "<MODEL>"  # V2, V5 or V6. The software cannot discover the model.
BAUDRATE = 19200  # Match the front panel; 19200 is only the factory default.


def main() -> None:
    if PORT == "<PORT>":
        raise ValueError("Edit PORT, MODEL and BAUDRATE at the top of this script first.")

    # Construction validates the settings but does not open the port.
    laser = VerdiController(PORT, model=MODEL, baudrate=BAUDRATE, timeout_s=1.0)
    print(f"Connecting to {MODEL} on {PORT} at {BAUDRATE} baud; reads only.")
    if input("Verify the connection and safe setup, then type CONNECT: ").strip() != "CONNECT":
        print("Cancelled. No connection was opened.")
        return

    # Step 2: 'with' opens the port and closes it when this block ends.
    with laser:
        version = laser.read("?SV")  # '?' means query; SV means software version.
        print(f"Reported software version: {version}")

    # Step 3: compare that version with the actual instrument before lesson 2.
    print("Port released. Disconnecting does not change the laser's operating state.")


if __name__ == "__main__":
    try:
        main()
    except (VerdiError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(f"STOP: {type(exc).__name__}: {exc}")
        print("Do not retry automatically. Check the link with the operator.")
        raise SystemExit(1) from None
