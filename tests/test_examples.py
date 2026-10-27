"""Execute the hardware tutorial notebooks through fake serial I/O, never a physical port."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import serial
import serial.tools.list_ports
from fakes import FaultyVerdi, SerialPeer

from coherent_verdi import VerdiController, VerdiError
from coherent_verdi.controller import QUERIES

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
DISCOVERY = "00_device_discovery.ipynb"
# Lessons that connect; discovery only reads the operating system's port list.
NOTEBOOKS = tuple(path.name for path in sorted(EXAMPLES.glob("0*.ipynb")) if path.name != DISCOVERY)
WRITERS = ("05_set_power.ipynb", "06_controlled_session.ipynb")
SETTINGS = dict(
    PORT="FAKE-ONLY",
    MODEL="V5",
    BAUDRATE=9600,
    ACTIVE_FAULT_CLEAR_REPLY="SYSTEM OK",
    TARGET_W=0.25,
    POWER_LIMIT_W=0.5,
)


def code_cells(name):
    notebook = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    return [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]


def run(name, namespace=None, *, configure=True, **settings):
    """Run every code cell in order, like Run All; settings replace the parameters cell."""
    namespace = {} if namespace is None else namespace
    for cell in code_cells(name):
        exec(compile("".join(cell["source"]), name, "exec"), namespace)
        if configure and "parameters" in cell["metadata"].get("tags", ()):
            configured = dict(SETTINGS)
            if name in WRITERS:
                configured["ACTIVE_FAULT_CLEAR_REPLY"] = b"SYSTEM OK"
            namespace.update(configured, **settings)
    return namespace


def run_disconnect_cell(name, namespace):
    # Interactive use may leave an empty cell after the Disconnect section.
    cell = next(
        cell
        for cell in reversed(code_cells(name))
        if "".join(cell["source"]).strip() == "laser.disconnect()"
    )
    exec("".join(cell["source"]), namespace)


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
        startup_input=b"",
        purge_failure=None,
    )
    fixture.sim.set_key(True)

    class Peer(SerialPeer):
        def __init__(self, **settings):
            super().__init__(**settings)
            self.sim = fixture.sim
            self.purges = []
            self.events = []
            fixture.ports.append(self)

        def open(self):
            self.events.append("open")
            self.opens += 1
            self.sim.connect()
            self.pending.extend(fixture.startup_input)

        def reset_input_buffer(self):
            self.events.append("purge_rx")
            self.purges.append("rx")
            if fixture.purge_failure == "rx":
                raise OSError("RX purge failed")
            self.pending.clear()

        def reset_output_buffer(self):
            self.events.append("purge_tx")
            self.purges.append("tx")
            if fixture.purge_failure == "tx":
                raise OSError("TX purge failed")

        def close(self):
            self.closes += 1
            self.sim.disconnect()

        def write(self, request):
            self.events.append(request)
            assert not self.pending, "overlapping serial transactions"
            if request == fixture.fail_on:
                self.sim.inject_timeout(after_apply=True)
            reply = self.sim._simulate_response(request)
            if request == fixture.interrupt_on:
                raise KeyboardInterrupt()
            self.pending.extend(fixture.overrides.get(request, reply))
            self.pending.extend(
                {"V2": b"Verdi V-2>", "V5": b"Verdi V-5>", "V6": b"Verdi V-6>"}[self.sim.model]
            )
            return len(request)

    monkeypatch.setattr(serial, "Serial", Peer)
    # Each write cell asks for the word it names; answer with exactly that word.
    monkeypatch.setattr("builtins.input", lambda prompt: "RUN" if "RUN" in prompt else "SET")
    yield fixture
    fixture.sim.disconnect()


def fake_port(device, serial_number=None):
    return SimpleNamespace(
        device=device,
        description=f"USB Serial Port ({device})",
        hwid=f"USB VID:PID=0403:6001 SER={serial_number}",
        serial_number=serial_number,
    )


@pytest.fixture
def port_list(monkeypatch):
    """Answer comports() from a script of lists; serial.Serial stays prohibited."""
    other, verdi = fake_port("COM6", "SYNTH-1"), fake_port("COM3", "FT-VERDI")
    listings = SimpleNamespace(
        script=[[other, verdi], [other], [other, verdi], [other, verdi]], calls=0
    )

    def comports():
        listings.calls += 1
        return listings.script[min(listings.calls, len(listings.script)) - 1]

    monkeypatch.setattr(serial.tools.list_ports, "comports", comports)
    return listings


def test_discovery_finds_replugged_adapter_without_opening_ports(port_list, capsys):
    # conftest still forbids serial.Serial: any attempt to open a port fails the test.
    namespace = run(DISCOVERY, ADAPTER_SERIAL=None)
    assert [port.device for port in namespace["added"]] == ["COM3"]
    output = capsys.readouterr().out
    assert "PORT = 'COM3'" in output and "Expected exactly one" not in output
    assert "Enter ADAPTER_SERIAL" in output


def test_discovery_looks_up_port_by_adapter_serial(port_list, capsys):
    run(DISCOVERY, ADAPTER_SERIAL="FT-VERDI")
    assert capsys.readouterr().out.rstrip().endswith("['COM3']")


def test_discovery_reports_when_no_single_port_appears(port_list, capsys):
    port_list.script = [[]]  # Nothing changes between the unplug and replug steps.
    namespace = run(DISCOVERY, configure=False)
    assert namespace["added"] == []
    assert "Expected exactly one new port, found 0." in capsys.readouterr().out


def test_discovery_layout():
    cells = code_cells(DISCOVERY)
    assert [cell["metadata"].get("tags") for cell in cells].count(["parameters"]) == 1
    source = "".join("".join(cell["source"]) for cell in cells)
    assert "serial.Serial" not in source and "VerdiController" not in source


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_notebook_layout(name):
    notebook = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    cells = code_cells(name)
    assert notebook["cells"][0]["cell_type"] == "markdown"
    assert [cell["metadata"].get("tags") for cell in cells].count(["parameters"]) == 1
    nonempty = [cell for cell in cells if "".join(cell["source"]).strip()]
    assert "".join(nonempty[-1]["source"]).strip() == "laser.disconnect()"


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_missing_port_setting_stops_before_opening(hardware, name):
    with pytest.raises(ValueError, match="section 1"):
        run(name, PORT="<PORT>")
    assert not hardware.ports and not hardware.sim.requests


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_connection_section_only_opens_port_and_reports_status(hardware, name):
    namespace = {}
    for cell in code_cells(name):
        exec(compile("".join(cell["source"]), name, "exec"), namespace)
        if "parameters" in cell["metadata"].get("tags", ()):
            configured = dict(SETTINGS)
            if name in WRITERS:
                configured["ACTIVE_FAULT_CLEAR_REPLY"] = b"SYSTEM OK"
            namespace.update(configured)
        if "connection" in cell["metadata"].get("tags", ()):
            break
    else:
        pytest.fail("Notebook needs a dedicated connection cell")
    assert namespace["connected"] is True
    assert hardware.ports[0].events == ["open"]
    assert not hardware.sim.requests and not hardware.ports[0].purges
    run_disconnect_cell(name, namespace)


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_tutorial_sequences_and_exact_write_scope(hardware, name):
    model = "V2"
    hardware.sim = FaultyVerdi(model)
    hardware.sim.set_key(True)
    run(name, MODEL=model)
    assert hardware.sim.requests[0] == b"?SV\r\n"
    assert len(hardware.ports) == 1
    port = hardware.ports[0]
    assert port.port == "FAKE-ONLY" and port.settings["baudrate"] == 9600
    assert port.opens == port.closes == 1
    assert port.purges == ["tx", "rx"]
    assert port.events[:4] == ["open", "purge_tx", "purge_rx", b"?SV\r\n"]
    expected = (
        [b"P=0.2500\r\n"]
        if name == "05_set_power.ipynb"
        else [b"P=0.2500\r\n", b"L=1\r\n", b"S=1\r\n", b"S=0\r\n", b"L=0\r\n"]
        if name == "06_controlled_session.ipynb"
        else []
    )
    assert writes(hardware) == expected
    if name == "01_connect.ipynb":
        assert hardware.sim.requests == (b"?SV\r\n",)
    elif name == "03_health_check.ipynb":
        # A version check, then every survey query except the rejected ?DIOS.
        survey = hardware.sim.requests[1:]
        assert len(survey) == 41
        assert {request[:-2] for request in survey} == {
            query.encode("ascii") for query in QUERIES if query != "?DIOS"
        }
    elif name == "04_pre_key_on_readiness.ipynb":
        assert hardware.sim.requests[1:] == tuple(
            query + b"\r\n"
            for query in (
                b"?L",
                b"?K",
                b"?S",
                b"?F",
                b"?LBOSS",
                b"?LBOT",
                b"?LBOST",
                b"?D1SS",
                b"?ESS",
                b"?VSS",
                b"?SP",
            )
        )
    elif name in WRITERS:
        # Read the fixture directly; its real-controller connection is already closed.
        assert hardware.sim._simulate_response(b"?SP\r\n") == b"0.2500\r\n"
        assert hardware.sim._simulate_response(b"?L\r\n") == b"0\r\n"
        assert hardware.sim._simulate_response(b"?S\r\n") == b"0\r\n"


@pytest.mark.parametrize("name", WRITERS)
def test_cancel_stops_before_any_write(hardware, monkeypatch, name):
    monkeypatch.setattr("builtins.input", lambda prompt: "cancel")
    with pytest.raises(RuntimeError, match="Cancelled"):
        run(name)
    assert writes(hardware) == []


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_startup_purge_discards_host_input_before_first_query(hardware, name):
    hardware.startup_input = b"old host RX bytes\r\n"
    run(name)
    port = hardware.ports[0]
    assert port.purges == ["tx", "rx"]
    assert port.events[:4] == ["open", "purge_tx", "purge_rx", b"?SV\r\n"]
    assert not port.pending
    assert hardware.sim.requests[0] == b"?SV\r\n"


@pytest.mark.parametrize("name", NOTEBOOKS)
@pytest.mark.parametrize("direction", ["tx", "rx"])
def test_startup_purge_error_stops_before_any_query_or_setting(hardware, name, direction):
    hardware.purge_failure = direction
    namespace = {}
    with pytest.raises(VerdiError, match="serial buffer purge failed"):
        run(name, namespace)
    assert not hardware.sim.requests
    assert namespace["laser"].failed
    assert namespace["laser"].last_transaction is None
    assert hardware.ports[0].purges == (["tx"] if direction == "tx" else ["tx", "rx"])
    run_disconnect_cell(name, namespace)
    assert hardware.ports[0].closes == 1


def test_cancel_at_run_leaves_laser_in_standby(hardware, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "SET" if "SET" in prompt else "no")
    with pytest.raises(RuntimeError, match="not enabled"):
        run("06_controlled_session.ipynb")
    assert writes(hardware) == [b"P=0.2500\r\n"]


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_failure_stops_later_cells_and_disconnect_cell_releases_port(hardware, name):
    hardware.overrides[b"?SV\r\n"] = b"partial"
    namespace = {}
    with pytest.raises(VerdiError, match="timed out"):
        run(name, namespace)
    assert hardware.sim.requests == (b"?SV\r\n",)
    assert hardware.ports[0].closes == 0
    run_disconnect_cell(name, namespace)  # The step each notebook tells the operator to take.
    assert hardware.ports[0].closes == 1


def test_raw_status_stops_on_missing_prompt_and_preserves_evidence(hardware, capsys):
    hardware.overrides[b"?P\r\n"] = b"partial"
    namespace = {}
    with pytest.raises(VerdiError, match="timed out"):
        run("02_quick_status.ipynb", namespace)
    assert hardware.sim.requests == (b"?SV\r\n", b"?P\r\n")
    assert namespace["laser"].last_transaction["response"].startswith(b"partial")
    evidence = next(
        cell for cell in code_cells("02_quick_status.ipynb") if cell["id"] == "lesson02-evidence"
    )
    exec("".join(evidence["source"]), namespace)
    assert "partial" in capsys.readouterr().out
    run_disconnect_cell("02_quick_status.ipynb", namespace)
    assert hardware.ports[0].closes == 1


@pytest.mark.parametrize(
    "name,settings",
    [
        ("01_connect.ipynb", {"PORT": None}),
        ("03_health_check.ipynb", {"MODEL": "V9"}),
        ("05_set_power.ipynb", {"BAUDRATE": 12345}),
    ],
)
def test_bad_connection_settings_rejected_before_open(hardware, name, settings):
    with pytest.raises(ValueError):
        run(name, **settings)
    assert not hardware.ports and not hardware.sim.requests


@pytest.mark.parametrize("name", WRITERS)
def test_verified_fault_clear_text_required_before_open(hardware, name):
    with pytest.raises(ValueError):
        run(name, ACTIVE_FAULT_CLEAR_REPLY=None)
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
        run(name, **settings)
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
        run(name)
    assert writes(hardware) == []


@pytest.mark.parametrize("query", ["?D1SS", "?LBOSS", "?ESS", "?VSS"])
def test_every_temperature_servo_must_be_locked(hardware, query):
    hardware.overrides[query.encode() + b"\r\n"] = b"2\r\n"
    with pytest.raises(RuntimeError, match="not LOCKED"):
        run("06_controlled_session.ipynb")
    assert writes(hardware) == []


def test_controlled_session_requires_operator_key_configuration(hardware):
    hardware.sim.set_key(False)
    with pytest.raises(RuntimeError, match="key-ON"):
        run("06_controlled_session.ipynb")
    assert writes(hardware) == []


@pytest.mark.parametrize("name", WRITERS)
def test_conditions_are_checked_after_operator_confirmation(hardware, name, monkeypatch):
    def confirm(prompt):
        hardware.sim.set_faults(999)  # Condition changed while the operator was deciding.
        return "RUN" if "RUN" in prompt else "SET"

    monkeypatch.setattr("builtins.input", confirm)
    with pytest.raises(RuntimeError):
        run(name)
    assert writes(hardware) == []


def test_run_rechecks_readiness_after_setpoint_is_stored(hardware, monkeypatch):
    def confirm(prompt):
        if "RUN" in prompt:
            hardware.sim.set_faults(999)  # A fault appears between sections 6 and 7.
            return "RUN"
        return "SET"

    monkeypatch.setattr("builtins.input", confirm)
    with pytest.raises(RuntimeError, match="no active faults"):
        run("06_controlled_session.ipynb")
    assert writes(hardware) == [b"P=0.2500\r\n"]


@pytest.mark.parametrize(
    ("name", "instruction"),
    [
        ("05_set_power.ipynb", b"P=0.2500\r\n"),
        *(
            ("06_controlled_session.ipynb", command + b"\r\n")
            for command in [b"P=0.2500", b"L=1", b"S=1", b"S=0", b"L=0"]
        ),
    ],
)
def test_lost_ack_stops_without_retry_or_cleanup(hardware, name, instruction):
    hardware.fail_on = instruction
    with pytest.raises(VerdiError, match="timeout"):
        run(name)
    assert hardware.sim.requests[-1] == instruction
    assert hardware.sim.requests.count(instruction) == 1


@pytest.mark.parametrize("name", WRITERS)
def test_setpoint_mismatch_stops_before_enable(hardware, name):
    hardware.overrides[b"?SP\r\n"] = b"0.1\r\n"
    with pytest.raises(RuntimeError, match="readback mismatch"):
        run(name)
    assert writes(hardware) == [b"P=0.2500\r\n"]


@pytest.mark.parametrize("echo", [False, True])
def test_raw_setpoint_uses_only_byte_api_and_preserves_replies(hardware, monkeypatch, echo):
    hardware.sim._echo = echo

    def forbidden(*args, **kwargs):
        raise AssertionError("lesson 5 must use only raw read/write exchanges")

    for method in ("get_value", "get_status", "set_power_w"):
        monkeypatch.setattr(VerdiController, method, forbidden)
    namespace = run("05_set_power.ipynb")
    assert namespace["acknowledgment"] == ((b"P=0.2500" if echo else b"") + b"\r\nVerdi V-5>")
    assert namespace["after"][b"?SP"] == b"0.2500"
    assert writes(hardware) == [b"P=0.2500\r\n"]
    assert hardware.sim.requests[-4:] == (b"?SP\r\n", b"?L\r\n", b"?S\r\n", b"?F\r\n")


def test_raw_setpoint_rejection_stops_without_verification_or_retry(hardware):
    hardware.overrides[b"P=0.2500\r\n"] = b"RANGE ERROR: P=0.2500\r\n"
    namespace = {}
    with pytest.raises(RuntimeError, match="Unexpected command acknowledgment"):
        run("05_set_power.ipynb", namespace)
    assert namespace["acknowledgment"] == b"RANGE ERROR: P=0.2500\r\nVerdi V-5>"
    assert hardware.sim.requests[-1] == b"P=0.2500\r\n"
    assert writes(hardware) == [b"P=0.2500\r\n"]
    run_disconnect_cell("05_set_power.ipynb", namespace)


def test_raw_setpoint_detects_post_write_state_change_without_cleanup(hardware, monkeypatch):
    exchange = hardware.sim._simulate_response

    def change_state(request):
        reply = exchange(request)
        if request == b"P=0.2500\r\n":
            hardware.sim._apply("L=1")  # Simulate an external change, not a tutorial command.
        return reply

    monkeypatch.setattr(hardware.sim, "_simulate_response", change_state)
    namespace = {}
    with pytest.raises(RuntimeError, match="State or faults changed"):
        run("05_set_power.ipynb", namespace)
    assert namespace["after"][b"?L"] == b"1"
    assert writes(hardware) == [b"P=0.2500\r\n"]
    run_disconnect_cell("05_set_power.ipynb", namespace)


def test_unknown_fault_codes_are_preserved_without_reset(hardware):
    hardware.sim.set_faults(2, 999)
    namespace = run("03_health_check.ipynb")
    faults = namespace["health"]["Faults and identification"]
    assert faults[b"?F"] == faults[b"?FH"] == b"2&999"
    assert writes(hardware) == []


def test_health_check_skips_rejected_dios_and_keeps_remaining_raw_replies(hardware):
    hardware.overrides[b"?DIOS\r\n"] = b" Query Error:?DIOS\r\n"
    hardware.overrides[b"?D1PC\r\n"] = b"\x16\xe1\r\n"
    namespace = run("03_health_check.ipynb", ACTIVE_FAULT_CLEAR_REPLY=None)
    health = namespace["health"]
    assert list(health) == [
        "Output and operating state",
        "Faults and identification",
        "Operating hours",
        "Laser head",
        "LBO",
        "Etalon",
        "Vanadate",
        "Diode 1",
        "Diode optimization and aging",
    ]
    replies = [reply for section in health.values() for reply in section.values()]
    assert len(replies) == 41 and all(isinstance(reply, bytes) for reply in replies)
    assert health["Diode 1"][b"?D1PC"] == b"\x16\xe1"
    assert b"?DIOS\r\n" not in hardware.sim.requests
    assert hardware.sim.requests[-1] == b"?ACAD\r\n"
    assert b"\r\n" not in health["Diode optimization and aging"][b"?ACAD"]
    assert not writes(hardware)


def test_health_check_stops_mid_section_and_retains_earlier_results(hardware):
    hardware.overrides[b"?LBOSS\r\n"] = b"partial"
    namespace = {}
    with pytest.raises(VerdiError, match="timed out"):
        run("03_health_check.ipynb", namespace)
    assert hardware.sim.requests[-1] == b"?LBOSS\r\n"
    assert b"?LBOD\r\n" not in hardware.sim.requests
    assert list(namespace["health"]["LBO"]) == [b"?LBOT", b"?LBOST"]
    assert b"\r\n" not in namespace["health"]["Operating hours"][b"?HH"]
    run_disconnect_cell("03_health_check.ipynb", namespace)
    assert hardware.ports[0].closes == 1


def test_health_check_rejected_version_stops_before_status_queries(hardware):
    hardware.overrides[b"?SV\r\n"] = b" Query Error:?*UH?SV\r\n"
    namespace = {}
    with pytest.raises(RuntimeError, match="Device rejected"):
        run("03_health_check.ipynb", namespace)
    assert hardware.sim.requests == (b"?SV\r\n",)
    assert namespace["version_reply"] == b" Query Error:?*UH?SV"
    assert (
        namespace["laser"].last_transaction["response"]
        == namespace["version_reply"] + b"\r\nVerdi V-5>"
    )
    run_disconnect_cell("03_health_check.ipynb", namespace)


def test_version_diagnostic_records_one_same_connection_query_without_purge(hardware, capsys):
    hardware.overrides[b"?SV\r\n"] = b" Query Error:?*?SV\r\n"
    namespace = {}
    with pytest.raises(RuntimeError, match="Device rejected"):
        run("03_health_check.ipynb", namespace)
    before = namespace["laser"].last_transaction
    hardware.overrides.pop(b"?SV\r\n")
    diagnostic = next(
        cell
        for cell in code_cells("03_health_check.ipynb")
        if cell["id"] == "lesson03-version-diagnostic"
    )
    source = "".join(diagnostic["source"]).replace(
        "RUN_VERSION_DIAGNOSTIC = False", "RUN_VERSION_DIAGNOSTIC = True"
    )
    exec(source, namespace)
    assert namespace["previous_transaction"] == before
    assert namespace["diagnostic_reply"] == b"SIMULATOR"
    assert (
        namespace["diagnostic_transaction"]["response"]
        == namespace["diagnostic_reply"] + b"\r\nVerdi V-5>"
    )
    assert hardware.sim.requests == (b"?SV\r\n", b"?SV\r\n")
    assert hardware.ports[0].opens == 1 and hardware.ports[0].purges == ["tx", "rx"]
    assert "Previous transaction:" in capsys.readouterr().out
    run_disconnect_cell("03_health_check.ipynb", namespace)


def test_version_diagnostic_refuses_failed_exchange_without_transmission(hardware):
    hardware.overrides[b"?SV\r\n"] = b"partial"
    namespace = {}
    with pytest.raises(VerdiError, match="timed out"):
        run("03_health_check.ipynb", namespace)
    diagnostic = next(
        cell
        for cell in code_cells("03_health_check.ipynb")
        if cell["id"] == "lesson03-version-diagnostic"
    )
    source = "".join(diagnostic["source"]).replace(
        "RUN_VERSION_DIAGNOSTIC = False", "RUN_VERSION_DIAGNOSTIC = True"
    )
    with pytest.raises(RuntimeError, match="complete rejected"):
        exec(source, namespace)
    assert hardware.sim.requests == (b"?SV\r\n",)
    run_disconnect_cell("03_health_check.ipynb", namespace)


def test_health_check_device_error_stops_later_queries_and_keeps_raw_reply(hardware):
    hardware.overrides[b"?L\r\n"] = b"  Command Error:~L\r\n"
    namespace = {}
    with pytest.raises(RuntimeError, match="Device rejected"):
        run("03_health_check.ipynb", namespace)
    assert hardware.sim.requests[-1] == b"?L\r\n"
    assert b"?S\r\n" not in hardware.sim.requests
    assert namespace["health"]["Output and operating state"][b"?L"] == (b"  Command Error:~L")
    run_disconnect_cell("03_health_check.ipynb", namespace)


def test_pre_key_on_readiness_preserves_warmup_readings_without_actuation(hardware):
    hardware.overrides.update(
        {
            b"?LBOSS\r\n": b"2\r\n",
            b"?LBOT\r\n": b"118.25\r\n",
            b"?LBOST\r\n": b"149.20\r\n",
        }
    )
    namespace = run("04_pre_key_on_readiness.ipynb", ACTIVE_FAULT_CLEAR_REPLY=None)
    assert namespace["pre_key_on"][b"?LBOSS"] == b"2"
    assert namespace["pre_key_on"][b"?LBOT"] == b"118.25"
    assert namespace["pre_key_on"][b"?LBOST"] == b"149.20"
    assert not writes(hardware)
    assert hardware.ports[0].closes == 1


def test_interrupt_after_enable_does_not_send_blind_cleanup(hardware):
    hardware.interrupt_on = b"L=1\r\n"
    with pytest.raises(KeyboardInterrupt):
        run("06_controlled_session.ipynb")
    assert hardware.sim.requests[-1] == b"L=1\r\n"


def test_fault_history_is_captured_before_enable(hardware):
    namespace = run("06_controlled_session.ipynb")
    assert hardware.sim.requests.index(b"?FH\r\n") < hardware.sim.requests.index(b"L=1\r\n")
    assert namespace["history_before_enable"] == b"SYSTEM OK"


def test_device_rejection_stops_the_sequence(hardware):
    hardware.overrides[b"P=0.2500\r\n"] = b"RANGE ERROR: P=0.2500\r\n"
    with pytest.raises(RuntimeError, match="Unexpected command acknowledgment"):
        run("06_controlled_session.ipynb")
    assert writes(hardware) == [b"P=0.2500\r\n"]


@pytest.mark.parametrize("echo", [False, True])
def test_controlled_session_uses_raw_api_and_verifies_normal_completion(
    hardware, monkeypatch, echo
):
    hardware.sim._echo = echo

    def forbidden(*args, **kwargs):
        raise AssertionError("lesson 6 must use only raw read/write exchanges")

    for method in (
        "get_value",
        "get_status",
        "set_power_w",
        "set_laser_state",
        "set_value",
        "set_shutter",
        "get_power_w",
        "get_faults",
        "get_laser_state",
    ):
        monkeypatch.setattr(VerdiController, method, forbidden)
    namespace = run("06_controlled_session.ipynb")
    expected = [b"P=0.2500", b"L=1", b"S=1", b"S=0", b"L=0"]
    assert [instruction for instruction, wire in namespace["acknowledgments"]] == expected
    assert writes(hardware) == [instruction + b"\r\n" for instruction in expected]
    assert namespace["final_payloads"] == {
        b"?L": b"0",
        b"?S": b"0",
        b"?F": b"SYSTEM OK",
        b"?SP": b"0.2500",
    }
    assert isinstance(namespace["power_reply"], bytes)
    assert namespace["power_reply"] == b"0.250"
    assert all(isinstance(wire, bytes) for query, wire in namespace["replies"])


@pytest.mark.parametrize("instruction", [b"L=1", b"S=1", b"S=0", b"L=0"])
def test_rejected_sequence_command_stops_without_retry_or_cleanup(hardware, instruction):
    hardware.overrides[instruction + b"\r\n"] = b"Command Error: rejected\r\n"
    namespace = {}
    with pytest.raises(RuntimeError, match="Unexpected command acknowledgment"):
        run("06_controlled_session.ipynb", namespace)
    assert hardware.sim.requests[-1] == instruction + b"\r\n"
    assert writes(hardware).count(instruction + b"\r\n") == 1
    run_disconnect_cell("06_controlled_session.ipynb", namespace)


def test_failed_enable_readback_prevents_shutter_open(hardware):
    hardware.overrides[b"?L\r\n"] = b"0\r\n"  # Standby even after the enable acknowledgment.
    namespace = {}
    with pytest.raises(RuntimeError, match="ON with no faults"):
        run("06_controlled_session.ipynb", namespace)
    assert writes(hardware) == [b"P=0.2500\r\n", b"L=1\r\n"]
    run_disconnect_cell("06_controlled_session.ipynb", namespace)


def test_fault_history_query_rejection_prevents_all_writes(hardware):
    hardware.overrides[b"?FH\r\n"] = b"Query Error:?FH\r\n"
    namespace = {}
    with pytest.raises(RuntimeError, match="Unexpected fault history reply"):
        run("06_controlled_session.ipynb", namespace)
    assert writes(hardware) == []
    run_disconnect_cell("06_controlled_session.ipynb", namespace)


@pytest.mark.parametrize(
    "name", ["01_connect.ipynb", "02_quick_status.ipynb", "03_health_check.ipynb"]
)
def test_read_only_tutorials_replay_successful_v2_run(v2_serial, v2_replies, name):
    namespace = run(name, MODEL="V2", BAUDRATE=19200)
    assert v2_serial.opens == v2_serial.closes == 1
    assert not v2_serial.pending
    assert all(request.startswith(b"?") for request in v2_serial.writes)
    if name == "01_connect.ipynb":
        assert namespace["version_reply"] == b"6.05"
    elif name == "02_quick_status.ipynb":
        assert namespace["status"] == {query: v2_replies[query] for query in namespace["queries"]}
    else:
        actual = {
            query: payload
            for section in namespace["health"].values()
            for query, payload in section.items()
        }
        assert actual == v2_replies
        assert v2_serial.writes == [b"?SV\r\n"] + [q + b"\r\n" for q in v2_replies]
        assert b"?DIOS\r\n" not in v2_serial.writes
