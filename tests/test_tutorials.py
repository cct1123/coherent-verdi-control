"""TEST-011/012/013: workflows and operator entry points; all device peers are simulated."""

import ast
import runpy
import sys
from pathlib import Path

import nbformat
import pytest
from nbclient import NotebookClient

from coherent_verdi import (
    ConnectionUnusable,
    ControllerConfig,
    LaserState,
    Model,
    ProtocolError,
    Query,
    ResponseTimeout,
    SimulatedTransport,
    VerdiController,
    WritesDisabled,
)

ROOT = Path(__file__).resolve().parents[1]
TUTORIALS = ROOT / "examples" / "tutorials"
LESSONS = ("read_status", "set_power", "controlled_session", "handle_faults")


@pytest.fixture
def lessons():
    return runpy.run_path(str(TUTORIALS / "run_tutorial.py"))


def writes(sim):
    return [request for request in sim.requests if not request.startswith(b"?")]


@pytest.mark.parametrize("model", list(Model))
def test_reusable_workflows_all_models(lessons, model):
    sim = SimulatedTransport(model)
    with VerdiController(sim, ControllerConfig(model)) as laser:
        status = lessons["read_status"](laser)
        assert status.simulated and status.model == model
        assert status.laser_state == LaserState.STANDBY
        assert not status.shutter_open and not status.faults
        assert writes(sim) == []
    sim = SimulatedTransport(model)
    with VerdiController(
        sim, ControllerConfig(model, allow_writes=True, power_limit_w=0.5)
    ) as laser:
        assert lessons["set_standby_power"](laser, 0.25) == 0.25
        assert laser.laser_state() == LaserState.STANDBY
        assert laser.power_w() == 0
        sim.set_key(True)
        assert lessons["controlled_session"](laser, 0.25) == 0.25
        assert laser.laser_state() == LaserState.STANDBY
        assert laser.query(Query.SHUTTER) == 0
        assert laser.query(Query.SET_POWER) == 0.25
        assert writes(sim) == [
            b"P=0.2500\r\n",
            b"P=0.2500\r\n",
            b"L=1\r\n",
            b"S=1\r\n",
            b"S=0\r\n",
            b"L=0\r\n",
        ]


@pytest.mark.parametrize("name", LESSONS)
def test_entrypoints_repeat_and_release_simulators(lessons, name, monkeypatch, capsys):
    instances = []

    def factory(*args, **kwargs):
        sim = SimulatedTransport(*args, **kwargs)
        instances.append(sim)
        return sim

    main = lessons[f"simulate_{name}"]
    monkeypatch.setitem(main.__globals__, "SimulatedTransport", factory)
    main()
    first_output = capsys.readouterr().out
    main()
    assert capsys.readouterr().out == first_output
    assert len(instances) == (4 if name == "handle_faults" else 2)
    for sim in instances:
        with pytest.raises(ConnectionUnusable):
            sim.exchange(b"?L\r\n")
    if name == "read_status":
        assert "Expected WritesDisabled" in first_output
        assert not any(writes(sim) for sim in instances)
    elif name == "set_power":
        assert "Expected rejection before transmission" in first_output
        assert writes(instances[0]) == [b"P=0.2500\r\n", b"P=0.0000\r\n"]
    elif name == "controlled_session":
        expected = [
            b"?L",
            b"?K",
            b"?S",
            b"?P",
            b"?SP",
            b"?D1C",
            b"?D1T",
            b"?D1HST",
            b"?BT",
            b"?LBOT",
            b"?LBOSS",
            b"?ET",
            b"?VT",
            b"?F",
            b"?FH",
            b"P=0.2500",
            b"?SP",
            b"L=1",
            b"?L",
            b"?F",
            b"?S",
            b"S=1",
            b"?S",
            b"?F",
            b"?P",
            b"S=0",
            b"?S",
            b"L=0",
            b"?L",
        ]
        assert instances[0].requests == tuple(request + b"\r\n" for request in expected)
    else:
        assert "known=False" in first_output and "Outcome UNKNOWN" in first_output
        assert writes(instances[0]) == []
        assert instances[1].requests == (b"P=0.2500\r\n",)


@pytest.mark.parametrize("target", [-0.1, 0.6, float("nan"), float("inf"), True, "0.25"])
def test_bad_setpoints_never_transmit(lessons, target):
    sim = SimulatedTransport()
    with VerdiController(
        sim, ControllerConfig(Model.V5, allow_writes=True, power_limit_w=0.5)
    ) as c:
        with pytest.raises(ValueError):
            lessons["set_standby_power"](c, target)
        assert not writes(sim)


@pytest.mark.parametrize("state", ["key_off", "cold", "fault", "already_on", "open_shutter"])
def test_session_preconditions_prevent_writes(lessons, state):
    sim = SimulatedTransport(clock=lambda: 0.0, warmup_s=10 if state == "cold" else 0)
    sim.set_key(state != "key_off")
    with VerdiController(sim, ControllerConfig(Model.V5, allow_writes=True)) as c:
        if state == "fault":
            sim.set_faults(999)
        if state in ("already_on", "open_shutter"):
            c.enable_laser()
        if state == "open_shutter":
            c.set_shutter(open=True)
        before = writes(sim)
        with pytest.raises(RuntimeError):
            lessons["controlled_session"](c, 0.25)
        assert writes(sim) == before


@pytest.mark.parametrize("state", ["on", "fault", "writes_disabled"])
def test_standby_setpoint_preconditions(lessons, state):
    sim = SimulatedTransport()
    with VerdiController(
        sim, ControllerConfig(Model.V5, allow_writes=state != "writes_disabled")
    ) as c:
        if state == "on":
            sim.set_key(True)
            c.enable_laser()
        elif state == "fault":
            sim.set_faults(2)
            c.standby()  # Standby does not clear the active fixture fault.
        before = writes(sim)
        with pytest.raises((RuntimeError, WritesDisabled)):
            lessons["set_standby_power"](c, 0.25)
        assert writes(sim) == before


@pytest.mark.parametrize("instruction", [b"P=0.2500", b"L=1", b"S=1", b"S=0", b"L=0"])
def test_session_lost_ack_stops_without_replay_or_cleanup(lessons, instruction, monkeypatch):
    sim = SimulatedTransport()
    sim.set_key(True)
    exchange = sim.exchange

    def fail_selected(request):
        if request == instruction + b"\r\n":
            sim.inject_timeout(after_apply=True)
        return exchange(request)

    monkeypatch.setattr(sim, "exchange", fail_selected)
    with VerdiController(sim, ControllerConfig(Model.V5, allow_writes=True)) as c:
        with pytest.raises(ResponseTimeout):
            lessons["controlled_session"](c, 0.25)
    assert sim.requests[-1] == instruction + b"\r\n"
    assert sim.requests.count(instruction + b"\r\n") == 1


@pytest.mark.parametrize(
    ("instruction", "response"),
    [(b"?SP", b"0.1\r\n"), (b"?SP", b"bad\r\n"), (b"S=1", KeyboardInterrupt())],
)
def test_session_bad_readback_or_interrupt_stops(lessons, instruction, response, monkeypatch):
    sim = SimulatedTransport()
    sim.set_key(True)
    exchange = sim.exchange

    def fail_selected(request):
        # First ?SP is part of preflight status. Fail only after the power write.
        if request == instruction + b"\r\n" and writes(sim):
            if isinstance(response, BaseException):
                raise response
            sim.inject(response)
        return exchange(request)

    monkeypatch.setattr(sim, "exchange", fail_selected)
    with VerdiController(sim, ControllerConfig(Model.V5, allow_writes=True)) as c:
        with pytest.raises((RuntimeError, ProtocolError, KeyboardInterrupt)):
            lessons["controlled_session"](c, 0.25)
    assert b"S=0\r\n" not in writes(sim) and b"L=0\r\n" not in writes(sim)
    if instruction == b"?SP":
        assert b"L=1\r\n" not in writes(sim)


def test_fault_evidence_preserved_without_enable(lessons):
    sim = SimulatedTransport()
    sim.set_faults(2, 999)
    with VerdiController(sim, ControllerConfig(Model.V5)) as c:
        active, history = lessons["read_fault_report"](c)
        assert [fault.code for fault in active] == [2, 999]
        assert not active[1].known and active == history
        sim.set_faults()
        after, retained = lessons["read_fault_report"](c)
        assert after == () and retained == history
        assert c.laser_state() == LaserState.FAULT
    assert writes(sim) == []


@pytest.mark.parametrize("after_apply", [False, True])
def test_unknown_write_outcome_is_not_retried(lessons, after_apply, capsys):
    sim = SimulatedTransport()
    with VerdiController(sim, ControllerConfig(Model.V5, allow_writes=True)) as c:
        sim.inject_timeout(after_apply=after_apply)
        assert lessons["set_power_once"](c, 0.25) is False
    assert sim.requests == (b"P=0.2500\r\n",)
    assert "Outcome UNKNOWN" in capsys.readouterr().out


@pytest.mark.parametrize(
    "hardware_path", [False, True], ids=["default", "operator-path-with-simulator"]
)
@pytest.mark.parametrize("name", LESSONS)
def test_notebook_definitions_match_and_execute(name, hardware_path, tmp_path, monkeypatch):
    index = LESSONS.index(name) + 1
    path = TUTORIALS / f"{index:02}_{name}.ipynb"
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    runner = ast.parse((TUTORIALS / "run_tutorial.py").read_text(encoding="utf-8"))
    reference_functions = {
        node.name: ast.dump(node) for node in runner.body if isinstance(node, ast.FunctionDef)
    }
    all_code = "\n\n".join(cell.source for cell in notebook.cells if cell.cell_type == "code")
    notebook_tree = ast.parse(all_code)
    functions = {
        node.name: ast.dump(node)
        for node in notebook_tree.body
        if isinstance(node, ast.FunctionDef)
    }
    assert {f"simulate_{name}", "hardware_power_config", "hardware_connection"} <= functions.keys()
    for function, definition in functions.items():
        assert definition == reference_functions[function], f"Notebook drift: {function}"
    for node in ast.walk(notebook_tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = (
                [node.module] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names]
            )
            assert all(
                m.split(".")[0] in {"coherent_verdi", "collections", "contextlib"} for m in modules
            )
    assert all(
        len(cell.source.splitlines()) <= 30 for cell in notebook.cells if cell.cell_type == "code"
    )

    # Pytest's process-local hardware guard cannot protect a separate Jupyter kernel.
    guard = nbformat.v4.new_code_cell(
        "import coherent_verdi, serial, serial.tools.list_ports\n"
        "def prohibited(*args, **kwargs):\n"
        "    raise AssertionError('Hardware access prohibited in tutorial notebooks')\n"
        "coherent_verdi.open_serial = prohibited\n"
        "coherent_verdi.SerialTransport = prohibited\n"
        "serial.Serial = prohibited\n"
        "serial.serial_for_url = prohibited\n"
        "serial.tools.list_ports.comports = prohibited\n"
        "serial.tools.list_ports.grep = prohibited\n"
    )
    notebook.cells.insert(0, guard)
    original_setup = None
    if hardware_path:
        guard.source += (
            "from coherent_verdi import SimulatedTransport, Model\n"
            "def simulated_serial(config, *, hardware_allowed):\n"
            "    assert hardware_allowed is True\n"
            "    assert config.port == 'SIMULATED_TEST_PORT'\n"
            "    sim = SimulatedTransport(Model.V5)\n"
            "    sim.set_key(True)\n"
            "    return sim\n"
            "coherent_verdi.open_serial = simulated_serial\n"
            "answers = iter(['CONNECT', 'RUN'])\n"
            # A notebook global survives IPykernel's per-cell builtins.input reset.
            "input = lambda prompt: next(answers)\n"
        )
        setup = next(
            cell for cell in notebook.cells if "hardware-setup" in cell.metadata.get("tags", [])
        )
        original_setup = setup.source
        setup.source = (
            "RUN_HARDWARE = True\n"
            "HARDWARE_PORT = 'SIMULATED_TEST_PORT'\n"
            "HARDWARE_MODEL = Model.V5\n"
            "HARDWARE_BAUDRATE = 19200\n"
            "HARDWARE_TIMEOUT_S = 1.0\n"
            "TARGET_W = 0.25\n"
            "POWER_LIMIT_W = 0.5\n"
            "IDENTIFY_ONLY = False\n"
        )
    monkeypatch.setenv("IPYTHONDIR", str(tmp_path / "ipython"))
    monkeypatch.setenv("JUPYTER_RUNTIME_DIR", str(tmp_path))
    client = NotebookClient(
        notebook,
        timeout=30,
        kernel_name="python3",
        record_timing=False,
        # No adjacent tutorial scripts: the notebook must supply all demonstration code.
        resources={"metadata": {"path": str(tmp_path)}},
    )
    manager = client.create_kernel_manager()
    # Use the interpreter running pytest, not a user's unrelated registered kernel.
    manager.kernel_spec.argv = [
        sys.executable,
        "-m",
        "ipykernel_launcher",
        "-f",
        "{connection_file}",
    ]
    client.execute(cleanup_kc=True)
    notebook.cells.pop(0)
    if hardware_path:
        setup.source = original_setup
        notebook.metadata["verdi_validation"] = {
            "scope": "operator hardware path exercised with simulator substitution only",
            "configuration": "source settings restored to disabled defaults after execution",
        }
    nbformat.validate(notebook)
    output = "".join(
        item.get("text", "")
        for cell in notebook.cells
        if cell.cell_type == "code"
        for item in cell.outputs
    )
    expected = {
        "read_status": "Expected WritesDisabled",
        "set_power": "Setpoint after rejection: 0.2500 W",
        "controlled_session": "Shutter closed; STANDBY confirmed.",
        "handle_faults": "Outcome UNKNOWN",
    }
    assert expected[name] in output
    assert "Connection released" in output
    if hardware_path:
        assert "HARDWARE: V5, port=SIMULATED_TEST_PORT" in output
        assert "Reported software: SIMULATOR-0.1" in output
    else:
        assert "Hardware section skipped" in output
    destination = ROOT / "records" / "tutorial-notebooks"
    destination.mkdir(exist_ok=True)
    output_name = f"{path.stem}-operator-path.ipynb" if hardware_path else path.name
    nbformat.write(notebook, destination / output_name)


@pytest.fixture
def operator_runner(monkeypatch):
    namespace = runpy.run_path(str(TUTORIALS / "run_tutorial.py"))
    run = namespace["run_hardware"]
    sim = SimulatedTransport(Model.V5)
    sim.set_key(True)
    opened = []

    def substitute(config, *, hardware_allowed):
        opened.append((config, hardware_allowed))
        return sim

    monkeypatch.setitem(run.__globals__, "open_serial", substitute)
    answers = iter(["CONNECT", "RUN"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    yield namespace, sim, opened
    sim.close()


@pytest.mark.parametrize("lesson", ["read-status", "set-power", "controlled-session", "faults"])
def test_operator_path_uses_configured_connection_without_fixtures(
    operator_runner, monkeypatch, lesson
):
    namespace, sim, opened = operator_runner
    if lesson == "faults":
        sim.set_faults(2, 999)

    def prohibited(*args, **kwargs):
        raise AssertionError("The operator path must not use simulator fixtures")

    for method in ("__init__", "set_key", "set_faults", "inject", "inject_timeout"):
        monkeypatch.setattr(SimulatedTransport, method, prohibited)
    writes_allowed = lesson in {"set-power", "controlled-session"}
    power = {"target_w": 0.25, "power_limit_w": 0.5} if writes_allowed else {}
    assert (
        namespace["run_hardware"](
            lesson,
            port="SIMULATED_TEST_PORT",
            model=Model.V5,
            baudrate=9600,
            timeout_s=2.0,
            **power,
        )
        is True
    )
    assert len(opened) == 1
    config, allowed = opened[0]
    assert allowed and config.port == "SIMULATED_TEST_PORT"
    assert config.baudrate == 9600 and config.timeout_s == 2.0
    assert sim.requests[0] == b"?SV\r\n"
    if lesson == "set-power":
        assert writes(sim) == [b"P=0.2500\r\n"]  # No fixture demo/reset-to-zero.
    elif lesson == "controlled-session":
        assert writes(sim) == [b"P=0.2500\r\n", b"L=1\r\n", b"S=1\r\n", b"S=0\r\n", b"L=0\r\n"]
    else:
        assert writes(sim) == []
        if lesson == "faults":
            assert sim.requests == (b"?SV\r\n", b"?L\r\n", b"?F\r\n", b"?FH\r\n")
    with pytest.raises(ConnectionUnusable):
        sim.exchange(b"?L\r\n")


@pytest.mark.parametrize("answers", [["cancel"], ["CONNECT", "cancel"]])
def test_operator_can_cancel_before_connection_or_commands(operator_runner, monkeypatch, answers):
    namespace, sim, opened = operator_runner
    responses = iter(answers)
    monkeypatch.setattr("builtins.input", lambda prompt: next(responses))
    assert (
        namespace["run_hardware"](
            "controlled-session",
            port="SIMULATED_TEST_PORT",
            model=Model.V5,
            baudrate=19200,
            target_w=0.25,
            power_limit_w=0.5,
        )
        is False
    )
    assert len(opened) == len(answers) - 1
    assert sim.requests == (() if len(answers) == 1 else (b"?SV\r\n",))


def test_identify_only_is_one_read(operator_runner):
    namespace, sim, _ = operator_runner
    namespace["run_hardware"](
        "read-status",
        port="SIMULATED_TEST_PORT",
        model=Model.V5,
        baudrate=19200,
        identify_only=True,
    )
    assert sim.requests == (b"?SV\r\n",)


@pytest.mark.parametrize(
    "changed",
    [
        {"port": None},
        {"model": None},
        {"baudrate": None},
        {"baudrate": 12345},
        {"target_w": None},
        {"target_w": float("nan")},
        {"target_w": float("inf")},
        {"target_w": 0.6},
        {"target_w": -1},
        {"power_limit_w": None},
        {"power_limit_w": 6},
        {"identify_only": True},
        {"lesson": "faults"},
        {"timeout_s": 0},
    ],
)
def test_operator_configuration_rejected_before_open(operator_runner, changed):
    namespace, sim, opened = operator_runner
    options = dict(
        lesson="set-power",
        port="SIMULATED_TEST_PORT",
        model=Model.V5,
        baudrate=19200,
        target_w=0.25,
        power_limit_w=0.5,
    )
    options.update(changed)
    with pytest.raises(ValueError):
        namespace["run_hardware"](**options)
    assert opened == [] and sim.requests == ()


def test_operator_timeout_never_reconnects_or_continues(operator_runner):
    namespace, sim, opened = operator_runner
    sim.inject_timeout()
    with pytest.raises(ResponseTimeout):
        namespace["run_hardware"](
            "controlled-session",
            port="SIMULATED_TEST_PORT",
            model=Model.V5,
            baudrate=19200,
            target_w=0.25,
            power_limit_w=0.5,
        )
    assert len(opened) == 1 and sim.requests == (b"?SV\r\n",)
    with pytest.raises(ConnectionUnusable):
        sim.exchange(b"?L\r\n")


def test_operator_open_failure_never_falls_back_to_simulation(operator_runner, monkeypatch):
    namespace, _, _ = operator_runner

    def fail_open(*args, **kwargs):
        raise OSError("injected open failure")

    monkeypatch.setitem(namespace["run_hardware"].__globals__, "open_serial", fail_open)
    with pytest.raises(OSError, match="injected open failure"):
        namespace["run_hardware"](
            "read-status",
            port="SIMULATED_TEST_PORT",
            model=Model.V5,
            baudrate=19200,
        )


@pytest.mark.parametrize("lesson", ["read-status", "set-power", "controlled-session", "faults"])
def test_operator_cli_defaults_to_simulator(operator_runner, lesson, capsys):
    namespace, _, opened = operator_runner
    namespace["main"]([lesson])
    assert not opened
    assert "SIMULATOR: running the lesson" in capsys.readouterr().out


@pytest.mark.parametrize("options", [["--timeout-s", "2"], ["--port", "TEST_PORT"], ["--hardware"]])
def test_operator_cli_rejects_incomplete_mode_settings(operator_runner, options):
    namespace, sim, opened = operator_runner
    with pytest.raises(SystemExit) as error:
        namespace["main"](["read-status", *options])
    assert error.value.code == 2
    assert not opened and sim.requests == ()


def test_operator_cli_parses_hardware_parameters(operator_runner):
    namespace, sim, opened = operator_runner
    namespace["main"](
        [
            "set-power",
            "--hardware",
            "--port",
            "SIMULATED_TEST_PORT",
            "--model",
            "V5",
            "--baudrate",
            "9600",
            "--target-w",
            "0.25",
            "--power-limit-w",
            "0.5",
        ]
    )
    assert len(opened) == 1 and writes(sim) == [b"P=0.2500\r\n"]
