"""Execute lesson 08's opt-in command cells without opening hardware ports."""

import ast
import inspect
import json
from pathlib import Path
from pprint import pprint

import pytest
from fakes import FaultyVerdi

from coherent_verdi import VerdiController, VerdiError

NOTEBOOK = Path(__file__).resolve().parents[1] / "examples" / "08_controller_api_ref.ipynb"
CELLS = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
COMMANDS = {
    "power": b"P=0.2500",
    "value": b"P=0.2500",
    "write": b"P=0.2500",
    "command": b"S=0",
    "enable": b"L=1",
    "standby": b"L=0",
    "shutter-open": b"S=1",
    "shutter-close": b"S=0",
    "heater-on": b"LBOH=1",
    "heater-off": b"LBOH=0",
    "lbo-optimization": b"LBOOPT=1",
    "flash": b"FL=1",
    "chiller-on": b"CHILLER=ON",
    "chiller-temperature": b"CHILLER=20.0",
    "menu-up": b"MENUUP=1",
    "menu-down": b"MENUDN=1",
    "menu-select": b"SELECT=1",
    "exit-screen": b"EXIT=1",
    "knob-down": b"KNOBDN=1",
    "front-panel-lock": b"LFP=7",  # Fixture operand, not a hardware lock/unlock mapping.
    "echo-on": b"E=1",
    "echo-off": b"E=0",
    "prompt-on": b"PROMPT=0",
    "prompt-off": b"PROMPT=1",
    "baudrate": b"B=9600",
}


def example(slug, *, enabled=False):
    cell = next(cell for cell in CELLS if cell["id"] == "lesson08-try-" + slug)
    tree = ast.parse("".join(cell["source"]))
    operands = dict(APPROVED_W=0.25, APPROVED_C=20.0, VERIFIED_OPERAND=7, VERIFIED_BAUD=9600)
    if enabled:
        operands["RUN_THIS_EXAMPLE"] = True
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in operands:
                node.value = ast.Constant(operands[target.id])
    return compile(ast.fix_missing_locations(tree), str(NOTEBOOK), "exec")


def test_every_public_controller_method_has_an_executable_example():
    methods = {
        name
        for name, member in inspect.getmembers(VerdiController, inspect.isfunction)
        if not name.startswith("_")
    }
    called = set()
    for cell in CELLS:
        if cell["cell_type"] != "code":
            continue
        for node in ast.walk(ast.parse("".join(cell["source"]))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    if node.func.value.id in {"laser", "writer", "reader"}:
                        called.add(node.func.attr)
    assert methods <= called, f"Missing executable API examples: {methods - called}"
    assert len({cell["id"] for cell in CELLS}) == len(CELLS)
    assert {
        cell["id"].removeprefix("lesson08-try-")
        for cell in CELLS
        if "optional-write" in cell["metadata"].get("tags", ())
    } == set(COMMANDS)


@pytest.mark.parametrize("slug", COMMANDS)
def test_write_examples_skip_by_default_even_with_a_writer(slug):
    with FaultyVerdi(allow_writes=True) as writer:
        exec(example(slug), {"writer": writer, "pprint": pprint})
        assert writer.requests == ()


@pytest.mark.parametrize("prompt", [False, True])
@pytest.mark.parametrize("echo", [False, True])
@pytest.mark.parametrize("slug, instruction", COMMANDS.items())
def test_enabled_example_sends_only_its_selected_write(slug, instruction, prompt, echo):
    with FaultyVerdi(allow_writes=True, power_limit_w=0.5, prompt=prompt, echo=echo) as writer:
        # Establish a fixture state in which opening the simulated shutter is meaningful.
        writer.set_key(True)
        writer.set_laser_state(1)
        previous = len(writer.requests)
        exec(example(slug, enabled=True), {"writer": writer, "pprint": pprint})
        requests = writer.requests[previous:]
        assert [request for request in requests if not request.startswith(b"?")] == [
            instruction + b"\r\n"
        ]
        assert writer.failed is False
        if slug == "power":
            assert writer.get_value("?SP") == 0.25
        elif slug == "shutter-open":
            assert writer.get_value("?S") == 1


@pytest.mark.parametrize("slug", COMMANDS)
def test_enabled_example_requires_a_writer(slug):
    with pytest.raises(RuntimeError, match="Open the write session"):
        exec(example(slug, enabled=True), {"writer": None, "pprint": pprint})


@pytest.mark.parametrize("slug", COMMANDS)
def test_uncertain_example_stops_without_retry_or_followup_queries(slug):
    with FaultyVerdi(allow_writes=True, power_limit_w=0.5) as writer:
        # Enable/reset preserves two pre-command fault queries for review.
        if slug == "enable":
            writer.inject(b"SYSTEM OK\r\n")
            writer.inject(b"SYSTEM OK\r\n")
        writer.inject_timeout(after_apply=True)
        with pytest.raises(VerdiError, match="timeout"):
            exec(example(slug, enabled=True), {"writer": writer, "pprint": pprint})
        assert writer.requests[-1] == COMMANDS[slug] + b"\r\n"
        assert writer.requests.count(COMMANDS[slug] + b"\r\n") == 1
        assert writer.failed
