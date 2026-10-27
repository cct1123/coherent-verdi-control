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
# The multi-point sweep has its own execution/abort tests in test_power_current_sweep_example.py.
NOTEBOOKS = tuple(
    path.name
    for path in sorted(EXAMPLES.glob("0*.ipynb"))
    if path.name not in (DISCOVERY, "07_power_current_sweep.ipynb")
)
WRITERS = ("05_set_power.ipynb", "06_key_on_and_run.ipynb")
SETTINGS = dict(
    PORT="FAKE-ONLY",
    MODEL="V5",
    BAUDRATE=9600,
    TARGET_W=0.25,
    POWER_LIMIT_W=0.5,
)


def code_cells(name):
    notebook = json.loads((EXAMPLES / name).read_text(encoding="utf-8"))
    return [cell for cell in notebook["cells"] if cell["cell_type"] == "code"]


def perform_operator_step(name, cell):
    """Test hook for establishing initial state or simulating external state changes."""


def run(name, namespace=None, *, configure=True, **settings):
    """Run code cells with external-state hooks; settings replace the parameters cell."""
    namespace = {} if namespace is None else namespace
    for cell in code_cells(name):
        perform_operator_step(name, cell)
        exec(compile("".join(cell["source"]), name, "exec"), namespace)
        if configure and "parameters" in cell["metadata"].get("tags", ()):
            configured = dict(SETTINGS)
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
        silent_on=None,
        interrupt_on=None,
        startup_input=b"",
        purge_failure=None,
        key_on=True,
        key_on_laser_state=None,
    )
    fixture.sim.set_key(False)

    def operator_step(name, cell):
        if name == "06_key_on_and_run.ipynb" and cell["id"] == "lesson06-parameters":
            fixture.sim.set_key(fixture.key_on)
            if fixture.key_on_laser_state is not None:
                fixture.sim._laser = fixture.key_on_laser_state

    monkeypatch.setattr(__import__(__name__), "perform_operator_step", operator_step)

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
            reply = fixture.overrides.get(request, reply)
            if request == fixture.silent_on:
                return len(request)
            self.pending.extend(reply)
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
    hardware.sim.set_key(False)
    run(name, MODEL=model)
    assert hardware.sim.requests[0] == b"?SV\r\n"
    assert len(hardware.ports) == 1
    port = hardware.ports[0]
    assert port.port == "FAKE-ONLY" and port.settings["baudrate"] == 9600
    assert port.opens == port.closes == 1
    assert not port.pending
    assert port.purges == ["tx", "rx"]
    assert port.events[:4] == ["open", "purge_tx", "purge_rx", b"?SV\r\n"]
    expected = (
        [b"P=0.2500\r\n"]
        if name == "05_set_power.ipynb"
        else [b"P=0.2500\r\n", b"L=1\r\n", b"S=1\r\n", b"S=0\r\n"]
        if name == "06_key_on_and_run.ipynb"
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
    elif name == "04_check_readiness.ipynb":
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
        expected_state = b"1\r\n" if name == "06_key_on_and_run.ipynb" else b"0\r\n"
        assert hardware.sim._simulate_response(b"?L\r\n") == expected_state
        assert hardware.sim._simulate_response(b"?S\r\n") == b"0\r\n"


def test_api_tour_reads_typed_faults_and_status_without_configuration(hardware):
    namespace = run("08_controller_api_ref.ipynb")
    assert namespace["laser"].is_simulated is False  # Real controller through fake serial I/O.
    assert namespace["fault_capture"]["payload"] == b"SYSTEM OK"
    assert namespace["fault_capture"]["outcome"] == "captured"
    assert namespace["diagnostics"]["software_version"] == "SIMULATOR"
    assert namespace["status"]["faults"] == []
    assert namespace["status"]["simulated"] is False
    assert hardware.sim.requests.count(b"?F\r\n") == 3  # Capture, getter and status.
    assert writes(hardware) == []
    assert hardware.ports[0].closes == 1
    assert not hardware.ports[0].pending


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


@pytest.mark.parametrize("initial_state", [0, 1])
def test_cancel_at_run_leaves_existing_laser_state_unchanged(hardware, monkeypatch, initial_state):
    hardware.key_on_laser_state = initial_state
    monkeypatch.setattr("builtins.input", lambda prompt: "SET" if "SET" in prompt else "no")
    with pytest.raises(RuntimeError, match="No emission commands sent"):
        run("06_key_on_and_run.ipynb")
    assert writes(hardware) == [b"P=0.2500\r\n"]
    assert hardware.sim._key and hardware.sim._laser == initial_state
    assert hardware.sim._shutter is False


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


def test_quick_status_retains_successful_version_and_exact_empty_power_reply(hardware, capsys):
    hardware.sim = FaultyVerdi("V2")
    hardware.overrides[b"?SV\r\n"] = b"6.05\r\n"
    hardware.silent_on = b"?P\r\n"
    namespace = {}
    with pytest.raises(VerdiError, match="reply timed out or incomplete: b''"):
        run("02_quick_status.ipynb", namespace, MODEL="V2")
    assert namespace["version_reply"] == b"6.05"
    assert namespace["laser"].last_transaction == {
        "instruction": b"?P",
        "request": b"?P\r\n",
        "response": b"",
        "payload": None,
        "outcome": "failed",
        "error": "VerdiError: reply timed out or incomplete: b''",
    }
    assert namespace["status"] == {}
    with pytest.raises(VerdiError, match="failed"):
        namespace["laser"].read(b"?P")
    assert hardware.sim.requests == (b"?SV\r\n", b"?P\r\n")
    evidence = next(
        c for c in code_cells("02_quick_status.ipynb") if c["id"] == "lesson02-evidence"
    )
    exec("".join(evidence["source"]), namespace)
    assert "'response': b''" in capsys.readouterr().out
    run_disconnect_cell("02_quick_status.ipynb", namespace)
    assert hardware.ports[0].closes == 1 and not writes(hardware)


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
@pytest.mark.parametrize("target", [0.002, 0.015, 0.010000000001])
def test_power_lessons_reject_substep_target_before_open(hardware, name, target):
    with pytest.raises(ValueError, match="0.01 W increments"):
        run(name, TARGET_W=target)
    assert not hardware.ports and not hardware.sim.requests


@pytest.mark.parametrize(
    "name,condition",
    [(name, condition) for name in WRITERS for condition in ("open_shutter", "fault")]
    + [("05_set_power.ipynb", "on")],
)
def test_wrong_starting_state_blocks_writes(hardware, name, condition):
    if condition == "fault":
        hardware.sim.set_faults(999)
    else:
        # Fixture state operations only; not tutorial commands.
        hardware.sim.set_key(True)
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
        run("06_key_on_and_run.ipynb")
    assert writes(hardware) == []


def test_lesson05_requires_physical_key_off_even_in_remote_standby(hardware):
    hardware.sim.set_key(True)  # Fixture remains laser state 0; key position is independent.
    with pytest.raises(RuntimeError, match="key OFF"):
        run("05_set_power.ipynb")
    assert writes(hardware) == []


def test_controlled_session_requires_key_already_on_before_any_write(hardware):
    hardware.key_on = False
    with pytest.raises(RuntimeError, match="key already ON"):
        run("06_key_on_and_run.ipynb")
    assert writes(hardware) == []


def test_lesson05_fault_off_with_clear_active_faults_allows_key_off_preparation(hardware):
    # Reproduce the reported 6.05 combination without redefining state 2 as standby.
    hardware.sim._laser = 2
    hardware.sim._history = (5,)
    hardware.overrides[b"?SV\r\n"] = b"6.05\r\n"
    namespace = run("05_set_power.ipynb")
    assert b"?FH\r\n" in hardware.sim.requests
    assert namespace["before"][b"?L"] == namespace["after"][b"?L"] == b"2"
    assert namespace["before"][b"?K"] == namespace["after"][b"?K"] == b"0"
    assert namespace["before"][b"?FH"] == b"5"
    assert hardware.sim._history == (5,)
    assert writes(hardware) == [b"P=0.2500\r\n"]


def test_controlled_session_rejects_fault_off_even_when_active_fault_reply_is_clear(hardware):
    hardware.sim._laser = 2
    hardware.sim._history = (5,)
    with pytest.raises(RuntimeError, match="do not reset a faulted state"):
        run("06_key_on_and_run.ipynb")
    assert writes(hardware) == []
    assert hardware.sim._history == (5,)


def test_lesson05_key_on_during_set_confirmation_blocks_power_write(hardware, monkeypatch):
    def confirm(prompt):
        hardware.sim.set_key(True)  # Still remote standby, but key is no longer OFF.
        return "SET"

    monkeypatch.setattr("builtins.input", confirm)
    with pytest.raises(RuntimeError, match="key OFF"):
        run("05_set_power.ipynb")
    assert writes(hardware) == []


def test_already_enabled_laser_stays_on_during_preparation_and_skips_serial_enable(
    hardware, monkeypatch
):
    hardware.key_on_laser_state = 1
    hardware.sim._history = (5,)
    confirmations = []

    def confirm(prompt):
        assert hardware.sim._key is True
        assert hardware.sim._laser == 1 and hardware.sim._shutter is False
        confirmations.append(prompt)
        return "RUN" if "RUN" in prompt else "SET"

    monkeypatch.setattr("builtins.input", confirm)
    run("06_key_on_and_run.ipynb")
    assert len(confirmations) == 2
    assert writes(hardware) == [b"P=0.2500\r\n", b"S=1\r\n", b"S=0\r\n"]
    assert hardware.sim._key is True
    assert hardware.sim._laser == 1 and hardware.sim._shutter is False
    assert hardware.sim._history == (5,)  # No L=1 reset was sent.


@pytest.mark.parametrize("confirmation", ["SET", "RUN"])
def test_key_change_during_confirmation_stops_before_emission(hardware, monkeypatch, confirmation):
    def confirm(prompt):
        response = "RUN" if "RUN" in prompt else "SET"
        if response == confirmation:
            hardware.sim.set_key(False)  # External state change; no notebook key operation.
        return response

    monkeypatch.setattr("builtins.input", confirm)
    with pytest.raises(RuntimeError, match="key already ON"):
        run("06_key_on_and_run.ipynb")
    assert writes(hardware) == ([] if confirmation == "SET" else [b"P=0.2500\r\n"])


def test_lesson06_instructions_require_no_physical_key_transition():
    notebook = json.loads((EXAMPLES / "06_key_on_and_run.ipynb").read_text(encoding="utf-8"))
    source = "\n".join("".join(cell["source"]) for cell in notebook["cells"])
    assert "key OFF" not in source
    assert "key ON last" not in source
    assert all(
        "operator-key-on" not in cell["metadata"].get("tags", ()) for cell in notebook["cells"]
    )


@pytest.mark.parametrize("condition", ["key", "fault_off", "fault", "shutter", "servo", "power"])
def test_final_readiness_changes_stop_before_emission_commands(hardware, monkeypatch, condition):
    operator_step = perform_operator_step

    def change_before_emission(name, cell):
        operator_step(name, cell)
        if "emission-sequence" not in cell["metadata"].get("tags", ()):
            return
        if condition == "key":
            hardware.sim.set_key(False)
        elif condition == "fault_off":
            hardware.sim._laser = 2  # Even when ?F is clear, never enable from state 2.
        elif condition == "fault":
            hardware.sim.set_faults(5)
        elif condition == "shutter":
            hardware.sim._shutter = True
        elif condition == "servo":
            hardware.overrides[b"?LBOSS\r\n"] = b"2\r\n"
        else:
            hardware.sim._power = 0.3

    monkeypatch.setattr(__import__(__name__), "perform_operator_step", change_before_emission)
    namespace = {}
    with pytest.raises(RuntimeError):
        run("06_key_on_and_run.ipynb", namespace)
    assert "final_payloads" not in namespace
    assert writes(hardware) == [b"P=0.2500\r\n"]


def test_each_shutter_cycle_requires_explicit_run_confirmation(hardware, monkeypatch):
    namespace = run("06_key_on_and_run.ipynb")
    requests = hardware.sim.requests
    cell = next(c for c in code_cells("06_key_on_and_run.ipynb") if c["id"] == "lesson06-sequence")
    monkeypatch.setattr("builtins.input", lambda prompt: "cancel")
    with pytest.raises(RuntimeError, match="Cancelled"):
        exec("".join(cell["source"]), namespace)
    assert hardware.sim.requests == requests


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
        run("06_key_on_and_run.ipynb")
    assert writes(hardware) == [b"P=0.2500\r\n"]


@pytest.mark.parametrize(
    ("name", "instruction"),
    [
        ("05_set_power.ipynb", b"P=0.2500\r\n"),
        *(
            ("06_key_on_and_run.ipynb", command + b"\r\n")
            for command in [b"P=0.2500", b"L=1", b"S=1", b"S=0"]
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
def test_setpoint_uses_power_setter_and_preserves_byte_readbacks(hardware, monkeypatch, echo):
    hardware.sim._echo = echo
    acknowledgments = []
    set_power = VerdiController.set_power_w

    def forbidden(*args, **kwargs):
        raise AssertionError("lesson 5 state queries must retain their byte payloads")

    def record_set_power(laser, watts):
        set_power(laser, watts)
        acknowledgments.append(laser.last_transaction["response"])

    for method in ("get_value", "get_status"):
        monkeypatch.setattr(VerdiController, method, forbidden)
    monkeypatch.setattr(VerdiController, "set_power_w", record_set_power)
    namespace = run("05_set_power.ipynb")
    assert acknowledgments == [(b"P=0.2500" if echo else b"") + b"\r\nVerdi V-5>"]
    assert namespace["after"][b"?SP"] == b"0.2500"
    assert writes(hardware) == [b"P=0.2500\r\n"]
    assert hardware.sim.requests[-5:] == (b"?SP\r\n", b"?K\r\n", b"?L\r\n", b"?S\r\n", b"?F\r\n")


def test_setpoint_rejection_stops_without_verification_or_retry(hardware):
    hardware.overrides[b"P=0.2500\r\n"] = b"RANGE ERROR: P=0.2500\r\n"
    namespace = {}
    with pytest.raises(VerdiError, match="RANGE ERROR"):
        run("05_set_power.ipynb", namespace)
    assert namespace["laser"].last_transaction["response"] == (
        b"RANGE ERROR: P=0.2500\r\nVerdi V-5>"
    )
    assert hardware.sim.requests[-1] == b"P=0.2500\r\n"
    assert writes(hardware) == [b"P=0.2500\r\n"]
    run_disconnect_cell("05_set_power.ipynb", namespace)


def test_raw_setpoint_detects_post_write_state_change_without_cleanup(hardware, monkeypatch):
    exchange = hardware.sim._simulate_response

    def change_state(request):
        reply = exchange(request)
        if request == b"P=0.2500\r\n":
            hardware.sim.set_key(True)
            hardware.sim._apply("L=1")  # Simulate an external change, not a tutorial command.
        return reply

    monkeypatch.setattr(hardware.sim, "_simulate_response", change_state)
    namespace = {}
    with pytest.raises(RuntimeError, match="key OFF"):
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
    namespace = run("03_health_check.ipynb")
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
    namespace = run("04_check_readiness.ipynb")
    assert namespace["pre_key_on"][b"?LBOSS"] == b"2"
    assert namespace["pre_key_on"][b"?LBOT"] == b"118.25"
    assert namespace["pre_key_on"][b"?LBOST"] == b"149.20"
    assert not writes(hardware)
    assert hardware.ports[0].closes == 1


def test_interrupt_after_enable_does_not_send_blind_cleanup(hardware):
    hardware.interrupt_on = b"L=1\r\n"
    with pytest.raises(KeyboardInterrupt):
        run("06_key_on_and_run.ipynb")
    assert hardware.sim.requests[-1] == b"L=1\r\n"


def test_fault_history_is_captured_before_enable(hardware):
    namespace = run("06_key_on_and_run.ipynb")
    assert hardware.sim.requests.index(b"?FH\r\n") < hardware.sim.requests.index(b"L=1\r\n")
    assert namespace["history_before_enable"] == b"SYSTEM OK"


def test_device_rejection_stops_the_sequence(hardware):
    hardware.overrides[b"P=0.2500\r\n"] = b"RANGE ERROR: P=0.2500\r\n"
    with pytest.raises(VerdiError, match="RANGE ERROR"):
        run("06_key_on_and_run.ipynb")
    assert writes(hardware) == [b"P=0.2500\r\n"]


@pytest.mark.parametrize("echo", [False, True])
def test_controlled_session_uses_power_setter_and_byte_state_checks(hardware, monkeypatch, echo):
    hardware.sim._echo = echo
    setpoints = []
    laser_states = []
    shutter_states = []
    set_power = VerdiController.set_power_w
    set_laser_state = VerdiController.set_laser_state
    set_shutter = VerdiController.set_shutter

    def record_set_power(laser, watts):
        setpoints.append(watts)
        return set_power(laser, watts)

    def record_set_laser_state(laser, state):
        laser_states.append(state)
        return set_laser_state(laser, state)

    def record_set_shutter(laser, *, open):
        shutter_states.append(open)
        return set_shutter(laser, open=open)

    def forbidden(*args, **kwargs):
        raise AssertionError("lesson 6 state checks must retain byte payloads")

    for method in (
        "get_value",
        "get_status",
        "get_power_w",
        "get_faults",
        "get_laser_state",
    ):
        monkeypatch.setattr(VerdiController, method, forbidden)
    monkeypatch.setattr(VerdiController, "set_power_w", record_set_power)
    monkeypatch.setattr(VerdiController, "set_laser_state", record_set_laser_state)
    monkeypatch.setattr(VerdiController, "set_shutter", record_set_shutter)
    namespace = run("06_key_on_and_run.ipynb")
    assert setpoints == [0.25]
    assert laser_states == [1]
    assert shutter_states == [True, False]
    expected = [b"P=0.2500", b"L=1", b"S=1", b"S=0"]
    assert [instruction for instruction, wire in namespace["acknowledgments"]] == expected
    assert writes(hardware) == [instruction + b"\r\n" for instruction in expected]
    assert namespace["final_payloads"] == {
        b"?K": b"1",
        b"?L": b"1",
        b"?S": b"0",
        b"?F": b"SYSTEM OK",
        b"?SP": b"0.2500",
    }
    assert isinstance(namespace["power_reply"], bytes)
    assert namespace["power_reply"] == b"0.250"
    assert all(isinstance(wire, bytes) for query, wire in namespace["replies"])


def test_controlled_session_named_setters_use_current_notice_aware_parser(hardware):
    hardware.overrides[b"L=1\r\n"] = b"min current set\r\n\r\n"
    namespace = run("06_key_on_and_run.ipynb")
    assert namespace["acknowledgments"][1] == (b"L=1", b"min current set\r\n\r\nVerdi V-5>")
    assert namespace["final_payloads"][b"?L"] == b"1"
    assert namespace["final_payloads"][b"?K"] == b"1"
    assert writes(hardware).count(b"L=1\r\n") == 1


@pytest.mark.parametrize("instruction", [b"L=1", b"S=1", b"S=0"])
def test_rejected_sequence_command_stops_without_retry_or_cleanup(hardware, instruction):
    hardware.overrides[instruction + b"\r\n"] = b"Command Error: rejected\r\n"
    namespace = {}
    with pytest.raises(VerdiError, match="Command Error"):
        run("06_key_on_and_run.ipynb", namespace)
    assert hardware.sim.requests[-1] == instruction + b"\r\n"
    assert writes(hardware).count(instruction + b"\r\n") == 1
    run_disconnect_cell("06_key_on_and_run.ipynb", namespace)


def test_failed_enable_readback_prevents_shutter_open(hardware):
    hardware.overrides[b"?L\r\n"] = b"0\r\n"  # Standby even after the enable acknowledgment.
    namespace = {}
    with pytest.raises(RuntimeError, match="Readback mismatch"):
        run("06_key_on_and_run.ipynb", namespace)
    assert writes(hardware) == [b"P=0.2500\r\n", b"L=1\r\n"]
    run_disconnect_cell("06_key_on_and_run.ipynb", namespace)


@pytest.mark.parametrize("query,payload", [(b"?L", b"0"), (b"?S", b"1")])
def test_final_readback_mismatch_does_not_send_standby(hardware, monkeypatch, query, payload):
    exchange = hardware.sim._simulate_response

    def override_after_close(request):
        reply = exchange(request)
        if request == b"S=0\r\n":
            hardware.overrides[query + b"\r\n"] = payload + b"\r\n"
        return reply

    monkeypatch.setattr(hardware.sim, "_simulate_response", override_after_close)
    namespace = {}
    with pytest.raises(RuntimeError, match="Readback mismatch"):
        run("06_key_on_and_run.ipynb", namespace)
    assert writes(hardware) == [b"P=0.2500\r\n", b"L=1\r\n", b"S=1\r\n", b"S=0\r\n"]
    run_disconnect_cell("06_key_on_and_run.ipynb", namespace)


def test_fault_history_query_rejection_prevents_all_writes(hardware):
    hardware.overrides[b"?FH\r\n"] = b"Query Error:?FH\r\n"
    namespace = {}
    with pytest.raises(RuntimeError, match="Unexpected fault history reply"):
        run("06_key_on_and_run.ipynb", namespace)
    assert writes(hardware) == []
    run_disconnect_cell("06_key_on_and_run.ipynb", namespace)


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
