"""Table 5-3 named setters and byte commands, without physical serial access."""

import json

import pytest
import serial
from fakes import FaultyVerdi, RecordingVerdi

from coherent_verdi import VerdiController, VerdiError
from coherent_verdi.__main__ import main as cli_main
from coherent_verdi.controller import QUERIES, normalize_query

# Independent Table 5-3 transcription. POWER and LIGHT are the same operation;
# PRINT is a query prefix, tested against every Table 5-4 long name below.
MANUAL_COMMANDS = [
    ("BAUDRATE = 9600", "B:9600", b"B=9600\r\n", "set_baudrate", (9600,), {}),
    ("CHILLER = ON", "CHILLER:ON", b"CHILLER=ON\r\n", "chiller_on", (), {}),
    (
        "CHILLER = 20.0",
        "CHILLER:20.0",
        b"CHILLER=20.0\r\n",
        "set_chiller_temperature_c",
        (20,),
        {},
    ),
    ("ECHO = 1", "E:1", b"E=1\r\n", "set_echo", (), {"enabled": True}),
    ("EXIT SCREEN = 1", "EXIT:1", b"EXIT=1\r\n", "exit_screen", (), {}),
    ("FLASH = 1", "FL:1", b"FL=1\r\n", "flash", (), {}),
    ("KNOB DOWN = 1", "KNOBDN:1", b"KNOBDN=1\r\n", "knob_down", (), {}),
    ("LASER = 1", "L:1", b"L=1\r\n", "start", (), {}),
    ("LASER = 0", "L:0", b"L=0\r\n", "stop", (), {}),
    (
        "LBO HEATER = 0",
        "LBOH:0",
        b"LBOH=0\r\n",
        "set_lbo_heater",
        (),
        {"enabled": False},
    ),
    ("LBO OPTIMIZE = 1", "LBOOPT:1", b"LBOOPT=1\r\n", "optimize_lbo", (), {}),
    ("LIGHT = 0.25", "P:0.25", b"P=0.2500\r\n", "set_power_w", (0.25,), {}),
    ("POWER = 0.25", "P=0.25", b"P=0.2500\r\n", "set_power_w", (0.25,), {}),
    (
        "LOCK FRONT PANEL = 1",
        "LFP:1",
        b"LFP=1\r\n",
        "set_front_panel_lock",
        (1,),
        {},
    ),
    ("MENU DOWN = 1", "MENUDN:1", b"MENUDN=1\r\n", "menu_down", (), {}),
    ("MENU SELECT = 1", "SELECT:1", b"SELECT=1\r\n", "menu_select", (), {}),
    ("MENU UP = 1", "MENUUP:1", b"MENUUP=1\r\n", "menu_up", (), {}),
    ("PROMPT = 0", ">=0", b"PROMPT=0\r\n", "set_prompt", (), {"enabled": True}),
    ("PROMPT = 1", ">:1", b"PROMPT=1\r\n", "set_prompt", (), {"enabled": False}),
    ("SHUTTER = 1", "S:1", b"S=1\r\n", "set_shutter", (), {"open": True}),
]


@pytest.mark.parametrize("long,short,wire,method,args,kwargs", MANUAL_COMMANDS)
@pytest.mark.parametrize("echo,prompt", [(False, False), (True, True)])
def test_every_named_manual_command(long, short, wire, method, args, kwargs, echo, prompt):
    with RecordingVerdi(allow_writes=True, echo=echo, prompt=prompt) as laser:
        getattr(laser, method)(*args, **kwargs)
        assert laser.requests == (wire,)
        assert laser.last_transaction["outcome"] == "acknowledged"
        assert laser.get_value("?SV") == "SIMULATOR"  # Session remains aligned.


@pytest.mark.parametrize("long,short,wire,method,args,kwargs", MANUAL_COMMANDS)
def test_all_writes_require_opt_in(long, short, wire, method, args, kwargs):
    with RecordingVerdi() as laser:
        for action in (
            lambda: laser.set(wire[:-2]),
            lambda: getattr(laser, method)(*args, **kwargs),
        ):
            with pytest.raises(PermissionError):
                action()
        assert laser.requests == ()
        assert laser.last_transaction is None


@pytest.mark.parametrize("long,short,wire,method,args,kwargs", MANUAL_COMMANDS)
def test_every_command_uses_real_serial_transaction_path(
    monkeypatch, long, short, wire, method, args, kwargs
):
    from test_serial import FakeSerial

    peer = FakeSerial()
    reply = b"\r\n" + (b"Verdi>" if wire == b"PROMPT=0\r\n" else b"")
    peer.responses.append(reply)
    monkeypatch.setattr(serial, "Serial", lambda **settings: peer)
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=False) as laser:
        getattr(laser, method)(*args, **kwargs)
        assert laser.last_transaction["outcome"] == "acknowledged"
        assert laser.last_transaction["response"] == reply
    assert peer.writes == [wire]
    assert peer.opens == peer.closes == 1


@pytest.mark.parametrize(
    "instruction",
    [
        "",
        None,
        [],
        1,
        "BOGUS=1",
        "?P",
        "PRINT LIGHT",
        "L=1;S=1",
        "L=1\r\nS=1",
        "L=1\x00",
        "é=1",
        "L=1=1",
        "L=1:0",
        "L=2",
        "S=True",
        "E=-1",
        "PROMPT=ON",
        "LBOH=2",
        "FL=0",
        "KNOBDN=2",
        "EXIT=0",
        "LBOOPT=0",
        "SELECT=2",
        "MENUUP=0",
        "MENUDN=0",
        "B=115200",
        "B=9600.0",
        "B=True",
        "B=1e4",
        "LFP=True",
        "LFP=1.1",
        "CHILLER=OFF",
        "CHILLER=nan",
        "CHILLER=1e1",
        "P=1e0",
        "P=nan",
        "P=-1",
        "P=6",
        "L=1" + " " * 128,
    ],
)
def test_invalid_commands_never_transmit_or_replace_evidence(instruction):
    with RecordingVerdi(allow_writes=True) as laser:
        laser.get_value("?SV")
        previous = laser.last_transaction
        with pytest.raises((ValueError, TypeError)):
            laser.set(
                instruction.encode("ascii")
                if isinstance(instruction, str) and instruction.isascii()
                else instruction
            )
        assert laser.requests == (b"?SV\r\n",)
        assert laser.last_transaction == previous
        assert laser.get_value("?L") == 0


@pytest.mark.parametrize("value", [True, None, "20.0", float("inf"), float("nan"), 10**1000, 1e200])
def test_chiller_temperature_rejects_invalid_or_oversized_wire_values(value):
    with RecordingVerdi(allow_writes=True) as laser:
        with pytest.raises(ValueError):
            laser.set_chiller_temperature_c(value)
        assert laser.requests == ()


@pytest.mark.parametrize("value", [True, None, "1", 1.0, 10**124, -(10**123)])
def test_front_panel_lock_requires_a_bounded_integer(value):
    with RecordingVerdi(allow_writes=True) as laser:
        with pytest.raises(ValueError):
            laser.set_front_panel_lock(value)
        assert laser.requests == ()


@pytest.mark.parametrize("value", [True, "9600", 9600.0, 115200])
def test_baudrate_type_and_manual_rate_validation(value):
    with RecordingVerdi(allow_writes=True) as laser:
        with pytest.raises(ValueError):
            laser.set_baudrate(value)
        assert laser.requests == ()


@pytest.mark.parametrize("enabled", [0, 1, "False", None])
def test_lbo_heater_requires_boolean(enabled):
    with RecordingVerdi(allow_writes=True) as laser:
        with pytest.raises(ValueError):
            laser.set_lbo_heater(enabled=enabled)
        assert laser.requests == ()


def main(args):
    return cli_main(["--no-prompt", *args])


def test_software_power_ceiling_cannot_be_bypassed_by_aliases():
    with RecordingVerdi(allow_writes=True, power_limit_w=0.25) as laser:
        for instruction in ("P=0.3", "LIGHT:0.3", "P=0.3"):
            with pytest.raises(ValueError):
                laser.set(instruction.encode("ascii"))
        assert laser.requests == ()


def test_service_fixture_state_and_no_invented_thermal_or_optical_dynamics():
    with RecordingVerdi(allow_writes=True) as laser:
        laser.set_baudrate(9600)
        assert laser.get_value("?B") == 9600
        laser.set_lbo_heater(enabled=False)
        assert laser.get_value("?LBOH") == 0
        laser.set_lbo_heater(enabled=True)
        assert laser.get_value("?LBOH") == 1
        laser.chiller_on()
        laser.set_chiller_temperature_c(20.16)
        assert laser._chiller_on is True
        assert laser._chiller_temperature_c == 20.2
        laser.set_front_panel_lock(7)  # No undocumented firmware range assertion.
        assert laser._front_panel_lock == 7
        for method, name in (
            ("exit_screen", "EXIT"),
            ("knob_down", "KNOBDN"),
            ("menu_down", "MENUDN"),
            ("menu_select", "SELECT"),
            ("menu_up", "MENUUP"),
        ):
            getattr(laser, method)()
            assert laser._panel_action == name
        laser.optimize_lbo()  # Table's operand-less short spelling.
        laser.flash()
        assert laser._lbo_optimizations == laser._flash_count == 1
        assert laser.get_value("?LBOT") == 148  # Deliberately static fixture.
        assert laser.read_laser_state() == 0


@pytest.mark.parametrize("command", ["CHILLER=ON", "LBOOPT=1", "B=9600", "LFP=1"])
def test_service_command_loss_of_ack_retires_session_without_replay(command):
    with FaultyVerdi(allow_writes=True) as laser:
        laser.inject_timeout(after_apply=True)
        with pytest.raises(VerdiError) as caught:
            laser.set(command.encode("ascii"))
        assert caught.value.transaction["outcome"] == "unknown"
        with pytest.raises(VerdiError, match="failed"):
            laser.set(command.encode("ascii"))
        assert len(laser.requests) == 1


@pytest.mark.parametrize("command", ["CHILLER=20.0", "LFP=1", "B=9600"])
def test_device_range_rejection_preserves_session(command):
    with FaultyVerdi(allow_writes=True) as laser:
        laser.inject(("RANGE ERROR: " + command + "\r\n").encode())
        assert laser.set(command.encode("ascii")) == ("RANGE ERROR: " + command + "\r\n").encode()
        assert laser.last_transaction["outcome"] == "received"
        assert laser.get_value("?B") == 19200
        assert laser._baudrate == 19200


class BaudPeer:
    """Assert the write and acknowledgement happen at the original host rate."""

    def __init__(self):
        self._baudrate = 19200
        self.fail_switch = False
        self.pending = bytearray()
        self.writes = []
        self.events = []

    @property
    def baudrate(self):
        return self._baudrate

    @baudrate.setter
    def baudrate(self, value):
        self.events.append(("baud", value))
        if self.fail_switch:
            raise OSError("adapter cannot change baud")
        self._baudrate = value

    @property
    def in_waiting(self):
        return len(self.pending)

    def open(self):
        pass

    def close(self):
        pass

    def write(self, data):
        self.events.append(("write", self.baudrate))
        self.writes.append(data)
        self.pending.extend(b"\r\n" if data.startswith(b"B=") else b"9600\r\n")
        return len(data)

    def read_until(self, expected=b"\n", size=None):
        self._timeout = self.timeout
        return serial.SerialBase.read_until(self, expected, size)

    def read(self, count):
        self.events.append(("read", self.baudrate))
        result = self.pending[:count]
        del self.pending[:count]
        return bytes(result)


def test_baud_ack_then_host_switch_and_transaction_configuration(monkeypatch):
    peer = BaudPeer()
    monkeypatch.setattr(serial, "Serial", lambda **settings: peer)
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=False) as laser:
        laser.set_baudrate(9600)
        assert peer.events[0] == ("write", 19200)
        assert peer.events[-1] == ("baud", 9600)
        assert peer.events[1:-1] and all(event == ("read", 19200) for event in peer.events[1:-1])
        assert peer.baudrate == 9600
        assert laser.get_value("?B") == 9600
        assert peer.baudrate == 9600
        laser.disconnect()
        laser.connect()
        assert laser._baudrate == 9600


def test_failed_host_baud_switch_preserves_ack_evidence_and_retires_session(monkeypatch):
    peer = BaudPeer()
    peer.fail_switch = True
    monkeypatch.setattr(serial, "Serial", lambda **settings: peer)
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=False) as laser:
        with pytest.raises(VerdiError, match="host baud") as caught:
            laser.set_baudrate(9600)
        record = caught.value.transaction
        assert record == laser.last_transaction
        assert record["outcome"] == "acknowledged"
        assert record["response"] == b"\r\n"
        assert "adapter cannot change baud" in record["error"]
        for action in (lambda: laser.set_baudrate(9600), laser.read_power_w, laser.connect):
            with pytest.raises(VerdiError, match="failed"):
                action()
        assert peer.writes == [b"B=9600\r\n"]


@pytest.mark.parametrize("prefix", ["?", "PRINT "])
def test_every_manual_long_query_alias(prefix):
    # Reuse the independent source transcription, not the production alias map.
    from test_protocol import MANUAL_QUERIES

    assert len(MANUAL_QUERIES) == len(QUERIES) == 42
    with RecordingVerdi() as laser:
        for short, long, *_ in MANUAL_QUERIES:
            alias = prefix + long
            assert normalize_query(alias) == short
            assert laser.get_value(alias) == laser.get_value(short)
            captured = laser.capture(alias)
            assert captured["instruction"] == short.encode("ascii")
            assert captured["request"] == (short + "\r\n").encode()
            assert normalize_query("PRINT " + short[1:]) == short


@pytest.mark.parametrize("alias", ["PRINT LIGHT;L=1", "?LIGHT\n", "PRINT\tLIGHT", "?MISSING"])
def test_bad_query_aliases_never_transmit(alias):
    with RecordingVerdi() as laser:
        for action in (laser.get_value, laser.capture):
            with pytest.raises(ValueError):
                action(alias)
        assert laser.requests == ()


def test_cli_requires_explicit_write_enable_before_open(monkeypatch):
    monkeypatch.setattr(serial, "Serial", lambda **settings: pytest.fail("must not open"))
    with pytest.raises(SystemExit) as caught:
        main(["--port", "FAKE-ONLY", "--model", "V5", "command", "LBOH=1"])
    assert caught.value.code == 2


def test_cli_command_and_query_aliases(capsys):
    assert main(["command", "LBOH=0", "--allow-writes"]) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["request_hex"] == b"LBOH=0\r\n".hex()
    assert record["outcome"] == "received"
    assert main(["query", "PRINT LIGHT"]) == 0
    assert json.loads(capsys.readouterr().out) == 0


def test_cli_power_ceiling_and_command_failure_evidence(monkeypatch, capsys):
    assert main(["command", "P=0.3", "--allow-writes", "--power-limit-w", "0.25"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["type"] == "ValueError"
    laser = FaultyVerdi(allow_writes=True)
    laser.inject_timeout(after_apply=True)
    monkeypatch.setattr("coherent_verdi.__main__.SimulatedVerdi", lambda *args, **kwargs: laser)
    assert main(["command", "LBOOPT=1", "--allow-writes"]) == 2
    captured = capsys.readouterr()
    assert json.loads(captured.out)["outcome"] == "unknown"
    assert json.loads(captured.err)["type"] == "VerdiError"
