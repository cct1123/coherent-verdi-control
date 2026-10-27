"""Real controller API through a fake pySerial handle, never a port."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from coherent_verdi import VerdiController, VerdiError
from coherent_verdi.__main__ import main as cli_main


@pytest.mark.parametrize(
    ("command", "reply", "expected"),
    [
        (["query", "?SV"], b"TEST-FIRMWARE\r\n", "TEST-FIRMWARE"),
        (["query", "?P"], b"0.125\r\n", 0.125),
    ],
)
def test_cli_hardware_reads_explicit_port_without_initialization(
    peer, capsys, command, reply, expected
):
    peer.responses.append(reply)
    assert main(["--port", "FAKE-ONLY", "--model", "V6", "--baudrate", "9600", *command]) == 0
    assert json.loads(capsys.readouterr().out) == expected
    assert peer.port == "FAKE-ONLY"
    assert peer.settings["baudrate"] == 9600
    assert peer.writes == [(command[1] + "\r\n").encode()]
    assert peer.opens == peer.closes == 1


@pytest.mark.parametrize(
    "options",
    [
        ["--port", "FAKE-ONLY", "query", "?SV"],
        ["--baudrate", "9600", "query", "?SV"],
    ],
)
def test_cli_incomplete_connection_settings_never_open(peer, options):
    with pytest.raises(SystemExit) as error:
        main(options)
    assert error.value.code == 2
    assert peer.opens == 0


@pytest.mark.parametrize(
    "options",
    [
        ["--baudrate", "12345", "query", "?SV"],
        ["--timeout-s", "nan", "query", "?SV"],
        ["watch", "--count", "0"],
        ["watch", "--interval", "nan"],
        ["gui", "--port", "0"],
    ],
)
def test_cli_invalid_hardware_configuration_never_open(peer, capsys, options):
    assert main(["--port", "FAKE-ONLY", "--model", "V5", *options]) == 2
    assert json.loads(capsys.readouterr().err)["type"] == "ValueError"
    assert peer.opens == 0


def main(args):
    return cli_main(["--no-prompt", *args])


def test_cli_hardware_open_failure_does_not_fall_back_to_simulation(peer, capsys):
    peer.open_failure = OSError("disconnected adapter")
    assert main(["--port", "FAKE-ONLY", "--model", "V5", "query", "?SV"]) == 2
    output = capsys.readouterr()
    assert not output.out
    assert "disconnected adapter" in json.loads(output.err)["error"]
    assert peer.opens == 1 and peer.writes == []


def test_cli_hardware_timeout_never_retries(peer, capsys):
    assert (
        main(["--port", "FAKE-ONLY", "--model", "V5", "--timeout-s", "0.001", "query", "?SV"]) == 2
    )
    assert "timed out" in json.loads(capsys.readouterr().err)["error"]
    assert peer.opens == peer.closes == 1
    assert peer.writes == [b"?SV\r\n"]


def test_commission_defaults_to_one_raw_version_query(peer, capsys):
    peer.responses.append(b"Version-TEST\r\n")
    assert main(["--port", "FAKE-ONLY", "--model", "V5", "commission"]) == 0
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert record["instruction"] == "?SV" and record["payload"] == "Version-TEST"
    assert bytes.fromhex(record["request_hex"]) == b"?SV\r\n"
    assert bytes.fromhex(record["response_hex"]) == b"Version-TEST\r\n"
    assert record["outcome"] == "captured"
    assert output.err == ""
    assert peer.writes == [b"?SV\r\n"] and peer.opens == peer.closes == 1


@pytest.mark.parametrize("command", ["query", "commission"])
def test_cli_preserves_non_ascii_reply_without_json_serialization_failure(peer, capsys, command):
    payload = b"6.\x9605"
    peer.responses.append(b"?SV" + payload + b"\r\n")
    args = ["--port", "FAKE-ONLY", "--model", "V2", command]
    if command == "query":
        args.append("?SV")
    assert main(args) == 0
    output = capsys.readouterr()
    result = json.loads(output.out)
    if command == "query":
        assert result == {"bytes_hex": payload.hex()}
    else:
        assert result["payload"] is None and result["payload_hex"] == payload.hex()
        assert result["outcome"] == "captured" and result["error"] is None
    assert not output.err and peer.writes == [b"?SV\r\n"]


@pytest.mark.parametrize("reply", [b"UNVERIFIED CLEAR\r\n", b"\r\n", b"0\r\n"])
def test_commission_captures_fault_reply_without_assuming_clear(peer, capsys, reply):
    peer.responses.extend([b"Version-TEST\r\n", reply])
    assert (
        main(
            [
                "--port",
                "FAKE-ONLY",
                "--model",
                "V5",
                "commission",
                "--query",
                "?SV",
                "--query",
                "?F",
            ]
        )
        == 0
    )
    rows = [json.loads(row) for row in capsys.readouterr().out.splitlines()]
    assert [row["instruction"] for row in rows] == ["?SV", "?F"]
    assert bytes.fromhex(rows[1]["response_hex"]) == reply
    assert rows[1]["outcome"] == "captured" and "faults" not in rows[1]
    assert peer.writes == [b"?SV\r\n", b"?F\r\n"]


@pytest.mark.parametrize(
    "args",
    [
        ["commission"],
        ["--port", "FAKE-ONLY", "--model", "V5", "commission", "--query", "L=1"],
    ],
)
def test_commission_requires_explicit_connection_and_whitelisted_queries(peer, args):
    with pytest.raises(SystemExit) as caught:
        main(args)
    assert caught.value.code == 2
    assert peer.opens == 0 and peer.writes == []


@pytest.mark.parametrize(
    ("reply", "outcome"),
    [
        (b"Query Error: ?SV\r\n", "rejected"),
        (b"Version-TEST\n", "failed"),
        (b"partial", "failed"),
    ],
)
def test_commission_records_failure_and_stops_remaining_queries(peer, capsys, reply, outcome):
    peer.responses.extend([reply, b"0\r\n"])
    assert (
        main(
            [
                "--port",
                "FAKE-ONLY",
                "--model",
                "V5",
                "commission",
                "--query",
                "?SV",
                "--query",
                "?F",
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    record = json.loads(output.out)
    assert record["outcome"] == outcome and record["error"]
    assert json.loads(output.err)["type"] in ("DeviceError", "VerdiError")
    assert peer.writes == [b"?SV\r\n"] and peer.closes == 1


@pytest.mark.parametrize(
    "options",
    [
        {"port": ""},
        {"port": "loop://"},
        {"port": None},
        {"baudrate": 115200},
        {"baudrate": 19200.0},
        {"timeout_s": 0},
        {"timeout_s": float("inf")},
        {"timeout_s": True},
    ],
)
def test_invalid_connection_settings_never_open(peer, options):
    with pytest.raises(ValueError):
        VerdiController(**({"port": "FAKE-ONLY"} | options), prompt_enabled=False)
    assert peer.opens == 0


def test_passive_explicit_lifecycle_and_framing(peer):
    laser = VerdiController("FAKE-ONLY", prompt_enabled=False)
    assert peer.opens == 0
    with pytest.raises(VerdiError, match="disconnected"):
        laser.get_power_w()
    assert laser.connect() is True
    assert laser.connect() is True
    assert peer.opens == 1 and not peer.writes
    assert peer.settings == dict(
        port=None,
        baudrate=19200,
        bytesize=8,
        parity="N",
        stopbits=1,
        timeout=1.0,
        write_timeout=1.0,
        xonxoff=False,
        rtscts=False,
        dsrdtr=False,
    )
    assert peer.port == "FAKE-ONLY" and peer.dtr is False and peer.rts is False
    peer.responses.append(b"1.234\r\n")
    assert laser.get_power_w() == 1.234
    assert 0 < peer.write_timeout <= 1 and 0 < peer.timeout <= 1
    laser.disconnect()
    laser.disconnect()
    assert peer.closes == 1 and peer.writes == [b"?P\r\n"]
    # Normal, fully acknowledged sessions can explicitly reopen; no state is replayed.
    laser.connect()
    laser.disconnect()
    assert peer.opens == peer.closes == 2
    assert peer.writes == [b"?P\r\n"]


@pytest.mark.parametrize(
    "reply,error",
    [
        (b"", "timed out"),
        (b"1.2", "timed out"),
        (b"1.2\r", "timed out"),
        (b"X" * 4096, "byte limit"),
        (b"nan\r\n", "expected decimal"),
        (b"\x001\r\n", "control character"),
    ],
)
def test_failed_read_blocks_late_replies_and_reconnect(peer, reply, error):
    peer.responses.extend([reply, b"9.000\r\n"])
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        with pytest.raises(VerdiError, match=error):
            laser.get_power_w()
        for action in (laser.get_power_w, laser.connect):
            with pytest.raises(VerdiError, match="failed"):
                action()
        laser.disconnect()
        with pytest.raises(VerdiError, match="failed"):
            laser.connect()
    assert peer.writes == [b"?P\r\n"]


@pytest.mark.parametrize("failure", ["partial", "write", "interrupt", "unexpected"])
def test_uncertain_write_is_never_replayed(peer, failure):
    peer.partial = failure == "partial"
    if failure == "write":
        peer.write_failure = OSError("cable loss")
    if failure == "interrupt":
        peer.read_failure = KeyboardInterrupt()
    if failure == "unexpected":
        peer.read_failure = RuntimeError("adapter failure")
    peer.responses.append(b"\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=False) as laser:
        with pytest.raises((VerdiError, KeyboardInterrupt, RuntimeError)):
            laser.set_laser_state(1)
        for action in (
            (lambda: laser.set_laser_state(1)),
            (lambda: laser.set_laser_state(0)),
            laser.get_power_w,
        ):
            with pytest.raises(VerdiError):
                action()
    assert peer.writes in ([], [b"L=1\r\n"])


def test_receive_timeout_stays_configured_through_reply_and_prompt(peer, monkeypatch):
    clock = [0.0]
    read = peer.read
    timeouts = []

    def record_timeout(size):
        timeouts.append(peer.timeout)
        clock[0] += 0.0002
        return read(size)

    monkeypatch.setattr("coherent_verdi.controller.monotonic", lambda: clock[0])
    monkeypatch.setattr(peer, "read", record_timeout)
    peer.responses.append(b"1\r\nVerdi V-2>")
    with VerdiController("FAKE-ONLY", model="V2", timeout_s=0.01) as laser:
        assert laser.read(b"?L") == b"1"
    assert peer.write_timeout == 0.01
    assert all(0 < t <= 0.01 for t in timeouts)
    assert set(timeouts) == {0.01}
    assert clock[0] < 0.01


def test_complete_frame_at_byte_limit_is_accepted(peer):
    payload = b"X" * 4094
    peer.responses.extend([payload + b"\r\n", b"1\r\n"])
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        assert laser.get_value("?SV") == payload.decode()
        assert laser.last_transaction["response"] == payload + b"\r\n"
        assert laser.get_laser_state() == 1
    assert peer.writes == [b"?SV\r\n", b"?L\r\n"]


def test_frame_over_byte_limit_preserves_partial_evidence_and_retires_session(peer):
    reply = b"X" * 4095 + b"\r\n"
    peer.responses.append(reply)
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        with pytest.raises(VerdiError, match="4096 byte limit") as caught:
            laser.get_value("?SV")
        assert caught.value.transaction["response"] == reply[:4096]
        assert laser.last_transaction == caught.value.transaction
        assert peer.pending == b"\n"
        with pytest.raises(VerdiError, match="failed"):
            laser.get_laser_state()
    assert peer.writes == [b"?SV\r\n"]


def test_many_callers_cannot_mix_replies(peer):
    peer.responses.extend([b"1.234\r\n"] * 80)
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        with ThreadPoolExecutor(max_workers=8) as pool:
            assert list(pool.map(lambda _: laser.get_power_w(), range(80))) == [1.234] * 80
    assert len(peer.writes) == 80


@pytest.mark.parametrize("failure", [OSError("open failure"), KeyboardInterrupt()])
def test_failed_open_cleans_up_without_commands(peer, failure):
    peer.open_failure = failure
    laser = VerdiController("FAKE-ONLY", prompt_enabled=False)
    with pytest.raises((VerdiError, KeyboardInterrupt)):
        laser.connect()
    assert peer.closes == 1 and not peer.writes
    with pytest.raises(VerdiError):
        laser.connect()


def test_cleanup_failure_can_be_retried_without_reviving_connection(peer):
    laser = VerdiController("FAKE-ONLY", prompt_enabled=False)
    laser.connect()
    peer.close_failure = OSError("close failure")
    with pytest.raises(VerdiError):
        laser.disconnect()
    with pytest.raises(VerdiError):
        laser.get_power_w()
    peer.close_failure = None
    laser.disconnect()
    laser.disconnect()
    assert peer.closes == 2
    with pytest.raises(VerdiError):
        laser.connect()


def test_primary_error_survives_failed_context_cleanup(peer):
    peer.close_failure = OSError("close failure")
    with pytest.raises(RuntimeError, match="experiment failure") as caught:
        with VerdiController("FAKE-ONLY", prompt_enabled=False):
            raise RuntimeError("experiment failure")
    assert "close failure" in caught.value.__notes__[0]


@pytest.mark.parametrize("reply", [b"0", b"OK", b"SYSTEM OK&30"])
def test_invalid_active_fault_reply_blocks_writes(peer, reply):
    peer.responses.append(reply + b"\r\n")
    with VerdiController("FAKE-ONLY", allow_writes=True, prompt_enabled=False) as laser:
        with pytest.raises(VerdiError):
            laser.get_faults()
        with pytest.raises(VerdiError):
            laser.set_laser_state(1)
    assert peer.writes == [b"?F\r\n"]


def test_display_source_flag_cannot_change_fault_parsing(peer):
    peer.responses.append(b"OK\r\n")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        laser.is_simulated = True
        with pytest.raises(VerdiError):
            laser.get_faults()
    assert peer.writes == [b"?F\r\n"]


def test_fault_queries_accept_system_ok_without_configuration(peer):
    peer.responses.extend([b"SYSTEM OK\r\n", b"SYSTEM OK\r\n", b"30&999\r\n"])
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        assert laser.get_faults() == laser.get_faults(history=True) == []
        known, unknown = laser.get_faults()
        assert known == 30
        assert unknown == 999


def test_native_reads_preserve_framing_and_all_wire_evidence(peer):
    peer.responses.append(b"1.234\r\n")
    with VerdiController("FAKE-ONLY", prompt_enabled=False) as laser:
        assert laser.get_power_w() == 1.234
        assert laser.last_transaction["response"] == b"1.234\r\n"


def test_trailing_prompt_cannot_exceed_the_response_limit(peer):
    peer.responses.append(b"x" * 4093 + b"\r\nVerdi V-2>")
    with VerdiController("FAKE-ONLY", model="V2", prompt_enabled=True) as laser:
        with pytest.raises(VerdiError, match="4096 byte limit"):
            laser.get_capture("?SV")
        assert len(laser.last_transaction["response"]) == 4096
    assert peer.writes == [b"?SV\r\n"]


def test_command_acknowledgment_and_device_rejection_with_terminal_prompts(peer):
    peer.responses.extend([b"\r\nVerdi V-2>", b"Query Error: unsupported\r\nVerdi V-2>"])
    with VerdiController("FAKE-ONLY", model="V2", allow_writes=True, prompt_enabled=False) as laser:
        laser.set_laser_state(0)
        assert laser.last_transaction["outcome"] == "acknowledged"
        with pytest.raises(VerdiError, match="Query Error"):
            laser.get_value("?SV")
        assert laser.last_transaction["outcome"] == "rejected"
        assert not laser.failed
    assert peer.writes == [b"L=0\r\n", b"?SV\r\n"]
