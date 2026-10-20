"""Execute the hardware tutorials through fake serial I/O, never a physical port."""

import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest
import serial
from fakes import FaultyVerdi

from coherent_verdi import DeviceError, VerdiError

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SCRIPTS = tuple(path.name for path in sorted(EXAMPLES.glob("0*.py")))
WRITERS = ("04_set_power.py", "05_controlled_session.py")


def prepare(name, **settings):
    namespace = runpy.run_path(str(EXAMPLES / name))
    main = namespace["main"]
    configured = dict(
        PORT="FAKE-ONLY",
        MODEL="V5",
        BAUDRATE=9600,
        ACTIVE_FAULT_CLEAR_REPLY="SYSTEM OK",
        TARGET_W=0.25,
        POWER_LIMIT_W=0.5,
    )
    configured.update(settings)
    for key, value in configured.items():
        if key in main.__globals__:
            main.__globals__[key] = value
    return main


def writes(hardware):
    return [request for request in hardware.sim.requests if not request.startswith(b"?")]


@pytest.fixture
def hardware(monkeypatch):
    fixture = SimpleNamespace(
        sim=FaultyVerdi("V5"),
        ports=[],
        overrides={},
        fail_on=None,
        interrupt_on=None,
    )
    fixture.sim.set_key(True)

    class Peer:
        def __init__(self, **settings):
            self.settings = settings
            self.sim = fixture.sim
            self.pending = bytearray()
            self.opens = self.closes = 0
            fixture.ports.append(self)

        def open(self):
            self.opens += 1
            self.sim.connect()

        def close(self):
            self.closes += 1
            self.sim.disconnect()

        def write(self, request):
            assert not self.pending, "overlapping serial transactions"
            if request == fixture.fail_on:
                self.sim.inject_timeout(after_apply=True)
            reply = self.sim._exchange(request)
            if request == fixture.interrupt_on:
                raise KeyboardInterrupt()
            self.pending.extend(fixture.overrides.get(request, reply))
            return len(request)

        def read(self, size):
            chunk = bytes(self.pending[:size])
            del self.pending[:size]
            return chunk

        @property
        def in_waiting(self):
            return len(self.pending)

    monkeypatch.setattr(serial, "Serial", Peer)
    answers = iter(["CONNECT", "SET", "RUN"])

    def confirm(prompt):
        # Each script has CONNECT and at most one write confirmation.
        if "RUN" in prompt:
            return "RUN"
        return next(answers)

    monkeypatch.setattr("builtins.input", confirm)
    yield fixture
    fixture.sim.disconnect()


@pytest.mark.parametrize("name", SCRIPTS)
def test_examples_import_and_disabled_defaults_never_open(hardware, name, capsys):
    runpy.run_path(str(EXAMPLES / name))  # Importing defines main; no prompt or I/O.
    assert not hardware.ports and not hardware.sim.requests
    with pytest.raises(SystemExit) as error:
        runpy.run_path(str(EXAMPLES / name), run_name="__main__")
    assert error.value.code == 1
    assert "STOP: ValueError" in capsys.readouterr().out
    assert not hardware.ports and not hardware.sim.requests


@pytest.mark.parametrize("model", ["V2", "V5", "V6"])
@pytest.mark.parametrize("name", SCRIPTS)
def test_hardware_lessons_all_models_and_exact_write_scope(hardware, name, model, capsys):
    hardware.sim = FaultyVerdi(model)
    hardware.sim.set_key(True)
    prepare(name, MODEL=model)()
    output = capsys.readouterr().out
    assert "Software version" in output or "software version" in output
    assert hardware.sim.requests[0] == b"?SV\r\n"
    assert len(hardware.ports) == 1
    port = hardware.ports[0]
    assert port.port == "FAKE-ONLY" and port.settings["baudrate"] == 9600
    assert port.opens == port.closes == 1
    expected = (
        [b"P=0.2500\r\n"]
        if name == "04_set_power.py"
        else [b"P=0.2500\r\n", b"L=1\r\n", b"S=1\r\n", b"S=0\r\n", b"L=0\r\n"]
        if name == "05_controlled_session.py"
        else []
    )
    assert writes(hardware) == expected
    if name == "01_connect.py":
        assert hardware.sim.requests == (b"?SV\r\n",)
    elif name == "03_read_faults.py":
        assert hardware.sim.requests == (b"?SV\r\n", b"?L\r\n", b"?F\r\n", b"?FH\r\n")
    elif name in WRITERS:
        # Read the fixture directly; its real-controller connection is already closed.
        assert hardware.sim._exchange(b"?SP\r\n") == b"0.2500\r\n"
        assert hardware.sim._exchange(b"?L\r\n") == b"0\r\n"
        assert hardware.sim._exchange(b"?S\r\n") == b"0\r\n"


@pytest.mark.parametrize("name", SCRIPTS)
def test_cancel_before_connection(hardware, monkeypatch, name):
    monkeypatch.setattr("builtins.input", lambda prompt: "cancel")
    prepare(name)()
    assert not hardware.ports and not hardware.sim.requests


@pytest.mark.parametrize("name", WRITERS)
def test_cancel_before_writes(hardware, monkeypatch, name):
    answers = iter(["CONNECT", "cancel"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    prepare(name)()
    assert hardware.sim.requests == (b"?SV\r\n",)
    assert hardware.ports[0].closes == 1


@pytest.mark.parametrize("name", SCRIPTS)
@pytest.mark.parametrize("settings", [{"PORT": None}, {"MODEL": "V9"}, {"BAUDRATE": 12345}])
def test_bad_connection_settings_rejected_before_open(hardware, name, settings):
    with pytest.raises(ValueError):
        prepare(name, **settings)()
    assert not hardware.ports and not hardware.sim.requests


@pytest.mark.parametrize("name", SCRIPTS[1:])
def test_verified_fault_clear_text_required_before_open(hardware, name):
    with pytest.raises(ValueError):
        prepare(name, ACTIVE_FAULT_CLEAR_REPLY=None)()
    assert not hardware.ports and not hardware.sim.requests


@pytest.mark.parametrize("name", WRITERS)
@pytest.mark.parametrize(
    "settings",
    [
        {"TARGET_W": None},
        {"TARGET_W": True},
        {"TARGET_W": -1},
        {"TARGET_W": float("nan")},
        {"TARGET_W": float("inf")},
        {"TARGET_W": 0.6},
        {"POWER_LIMIT_W": None},
        {"POWER_LIMIT_W": True},
        {"POWER_LIMIT_W": 6},
        {"TARGET_W": 0.12346, "POWER_LIMIT_W": 0.12346},
    ],
)
def test_bad_power_settings_rejected_before_open(hardware, name, settings):
    with pytest.raises(ValueError):
        prepare(name, **settings)()
    assert not hardware.ports and not hardware.sim.requests


@pytest.mark.parametrize("name", WRITERS)
@pytest.mark.parametrize("condition", ["on", "open_shutter", "fault"])
def test_wrong_starting_state_blocks_writes(hardware, name, condition):
    if condition == "fault":
        hardware.sim.set_faults(999)
    else:
        # Fixture state operations only; not tutorial commands.
        hardware.sim._apply("L=1")
        if condition == "open_shutter":
            hardware.sim._apply("S=1")
    with pytest.raises(RuntimeError):
        prepare(name)()
    assert writes(hardware) == []
    assert hardware.ports[0].closes == 1


@pytest.mark.parametrize("query", ["?D1SS", "?LBOSS", "?ESS", "?VSS"])
def test_every_temperature_servo_must_be_locked(hardware, query):
    hardware.overrides[query.encode() + b"\r\n"] = b"2\r\n"
    with pytest.raises(RuntimeError, match="not LOCKED"):
        prepare("05_controlled_session.py")()
    assert writes(hardware) == []


def test_controlled_session_requires_operator_key_configuration(hardware):
    hardware.sim.set_key(False)
    with pytest.raises(RuntimeError, match="key-ON"):
        prepare("05_controlled_session.py")()
    assert writes(hardware) == []


@pytest.mark.parametrize("name", WRITERS)
def test_conditions_are_checked_after_operator_confirmation(hardware, name, monkeypatch):
    def confirm(prompt):
        if "CONNECT" in prompt:
            return "CONNECT"
        hardware.sim.set_faults(999)  # Condition changed while the operator was deciding.
        return "SET" if name == "04_set_power.py" else "RUN"

    monkeypatch.setattr("builtins.input", confirm)
    with pytest.raises(RuntimeError):
        prepare(name)()
    assert writes(hardware) == []


@pytest.mark.parametrize(
    ("name", "instruction"),
    [
        ("04_set_power.py", b"P=0.2500\r\n"),
        *(
            ("05_controlled_session.py", command + b"\r\n")
            for command in [b"P=0.2500", b"L=1", b"S=1", b"S=0", b"L=0"]
        ),
    ],
)
def test_lost_ack_stops_without_retry_or_cleanup(hardware, name, instruction):
    hardware.fail_on = instruction
    with pytest.raises(VerdiError, match="timeout"):
        prepare(name)()
    assert hardware.sim.requests[-1] == instruction
    assert hardware.sim.requests.count(instruction) == 1
    assert hardware.ports[0].closes == 1


@pytest.mark.parametrize("name", WRITERS)
def test_setpoint_mismatch_stops_before_enable(hardware, name):
    hardware.overrides[b"?SP\r\n"] = b"0.1\r\n"
    with pytest.raises(RuntimeError, match="readback mismatch"):
        prepare(name)()
    assert writes(hardware) == [b"P=0.2500\r\n"]


def test_unknown_fault_codes_are_preserved_without_reset(hardware, capsys):
    hardware.sim.set_faults(2, 999)
    prepare("03_read_faults.py")()
    output = capsys.readouterr().out
    assert "Active faults: [2, 999]" in output
    assert "Fault history: [2, 999]" in output
    assert writes(hardware) == []


def test_read_failure_releases_port_and_does_not_continue(hardware):
    hardware.overrides[b"?SV\r\n"] = b"\xff\r\n"
    with pytest.raises(VerdiError, match="non-ASCII"):
        prepare("02_read_status.py")()
    assert hardware.sim.requests == (b"?SV\r\n",)
    assert hardware.ports[0].closes == 1


def test_interrupt_after_enable_does_not_send_blind_cleanup(hardware):
    hardware.interrupt_on = b"L=1\r\n"
    with pytest.raises(KeyboardInterrupt):
        prepare("05_controlled_session.py")()
    assert hardware.sim.requests[-1] == b"L=1\r\n"
    assert hardware.ports[0].closes == 1


def test_fault_history_is_captured_before_enable(hardware):
    prepare("05_controlled_session.py")()
    assert hardware.sim.requests.index(b"?FH\r\n") < hardware.sim.requests.index(b"L=1\r\n")


def test_device_rejection_stops_the_sequence(hardware):
    hardware.overrides[b"P=0.2500\r\n"] = b"RANGE ERROR: P=0.2500\r\n"
    with pytest.raises(DeviceError):
        prepare("05_controlled_session.py")()
    assert writes(hardware) == [b"P=0.2500\r\n"]
